from __future__ import annotations
import io, tempfile, unittest, os
from contextlib import closing
from unittest.mock import patch
from pathlib import Path
from openpyxl import Workbook
from fastapi.testclient import TestClient
from src.course_data import CourseCreate, CourseStore, get_course_store
from src.teaching_history import get_history_store
from src.web_api import app
from tests.auth_helpers import login_test_client

class ClassroomTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(); self.store=CourseStore(Path(self.tmp.name)/'db.sqlite'); app.dependency_overrides[get_course_store]=lambda:self.store; self.client=TestClient(app); login_test_client(self.client,self.store); self.course=self.client.post('/api/courses',json={'name':'课程'}).json()
 def tearDown(self):
  self.client.close(); app.dependency_overrides.clear(); self.tmp.cleanup()
 def xlsx(self, rows):
  wb=Workbook(); ws=wb.active; [ws.append(row) for row in rows]; out=io.BytesIO(); wb.save(out); out.seek(0); return out
 def test_unicode_roster_import_increment_and_rollback(self):
  klass=self.client.post(f"/api/courses/{self.course['id']}/classes",json={'name':'一班'}).json(); cid=klass['class_id']
  first=self.client.post(f'/api/classes/{cid}/import',files={'file':('r.xlsx',self.xlsx([['姓名','学号'],[' 张三\u00a0','0012']]))}); self.assertEqual(first.status_code,200)
  bad=self.client.post(f'/api/classes/{cid}/import',files={'file':('r.xlsx',self.xlsx([['姓名','学号'],['李四','0022'],['王五','0022']]))}); self.assertEqual(bad.status_code,400)
  conflict=self.client.post(f'/api/classes/{cid}/import',files={'file':('r.xlsx',self.xlsx([['姓名','学号'],['不同姓名','0012']]))}); self.assertEqual(conflict.status_code,400)
  self.assertEqual(self.client.post(f'/api/classes/{cid}/import',files={'file':('r.xlsx',self.xlsx([['姓名','学号'],['张三','0012'],['赵六','0033']]))}).json()['added'],1)
 def test_duplicate_name_pending_confirm_reject_end_and_message(self):
  klass=self.client.post(f"/api/courses/{self.course['id']}/classes",json={'name':'二班'}).json(); cid=klass['class_id']; self.client.post(f'/api/classes/{cid}/import',files={'file':('r.xlsx',self.xlsx([['姓名','学号'],['同名','1'],['同名','2']]))}); sess=self.client.post(f'/api/classes/{cid}/sessions').json();
  pending=self.client.post(f"/api/join/{sess['join_token']}",json={'name':'同名'}); self.assertEqual(pending.json()['status'],'pending'); self.assertNotIn('student_no',pending.text); self.assertNotIn('student_id',pending.text)
  pending_list=self.client.get(f"/api/sessions/{sess['session_id']}/pending"); self.assertEqual(pending_list.status_code,200); self.assertEqual(len(pending_list.json()[0]['candidates']),2); candidate=pending_list.json()[0]['candidates'][0]; application=pending_list.json()[0]['session_student_id']; confirmed=self.client.post(f"/api/sessions/{sess['session_id']}/students/{application}/confirm",params={'student_id':candidate['student_id']}); self.assertEqual(confirmed.status_code,200); self.assertEqual(self.client.post(f"/api/classes/{cid}/sessions").status_code,409); self.assertEqual(self.client.post(f"/api/sessions/{sess['session_id']}/end").status_code,200); self.assertEqual(self.client.post(f"/api/sessions/{sess['session_id']}/messages",json={'body':'x'}).status_code,403); self.assertEqual(self.client.delete(f"/api/classes/{cid}").status_code,409)
 def test_qrcode_png_https_url_and_expiry(self):
  import os
  klass=self.client.post(f"/api/courses/{self.course['id']}/classes",json={'name':'二维码班'}).json(); sess=self.client.post(f"/api/classes/{klass['class_id']}/sessions").json()
  with patch.dict(os.environ, {'PUBLIC_WEB_BASE_URL':'http://127.0.0.1:5173'}, clear=False):
   denied=self.client.get(f"/api/sessions/{sess['session_id']}/join-info",headers={'X-Join-Token':sess['join_token']}); self.assertEqual(denied.status_code,503); self.assertIn('公网HTTPS',denied.text)
  with patch.dict(os.environ, {'PUBLIC_WEB_BASE_URL':'https://school.example/app'}, clear=False):
   info=self.client.get(f"/api/sessions/{sess['session_id']}/join-info",headers={'X-Join-Token':sess['join_token']}); self.assertEqual(info.status_code,200); url=info.json()['join_url'];
   import sqlite3
   with closing(sqlite3.connect(self.store.db_path)) as check: self.assertIsNone(check.execute("SELECT 1 FROM sqlite_master WHERE name='classroom_session_secrets'").fetchone()); self.assertTrue(url.startswith('https://school.example/app/?join=')); self.assertNotIn(self.course['id'],url); self.assertNotIn(klass['class_id'],url)
   png=self.client.get(f"/api/sessions/{sess['session_id']}/qrcode",headers={'X-Join-Token':sess['join_token']}); self.assertEqual(png.status_code,200); self.assertEqual(png.headers['content-type'],'image/png'); self.assertTrue(png.content.startswith(b'\x89PNG'))
   from PIL import Image
   import zxingcpp
   decoded=zxingcpp.read_barcode(Image.open(io.BytesIO(png.content)))
   self.assertIsNotNone(decoded); self.assertEqual(decoded.text,url)
  self.client.post(f"/api/sessions/{sess['session_id']}/end")
  self.assertEqual(self.client.get(f"/api/sessions/{sess['session_id']}/qrcode",headers={'X-Join-Token':sess['join_token']}).status_code,404)

 def test_multidevice_reconnect_and_concurrent_messages(self):
  klass=self.client.post(f"/api/courses/{self.course['id']}/classes",json={'name':'多设备班'}).json(); cid=klass['class_id']; self.client.post(f'/api/classes/{cid}/import',files={'file':('r.xlsx',self.xlsx([['姓名','学号'],['张三','0001']]))}); sess=self.client.post(f'/api/classes/{cid}/sessions').json()
  first=self.client.post(f"/api/join/{sess['join_token']}",json={'name':'张三'}).json(); second=self.client.post(f"/api/join/{sess['join_token']}",json={'name':'张三'}).json(); self.assertNotEqual(first['student_token'],second['student_token'])
  self.client.headers['X-Student-Session']=first['student_token']; one=self.client.post(f"/api/sessions/{sess['session_id']}/messages",json={'body':'一'}); self.client.headers['X-Student-Session']=second['student_token']; two=self.client.post(f"/api/sessions/{sess['session_id']}/messages",json={'body':'二'}); self.assertEqual(one.status_code,200); self.assertEqual(two.status_code,200)
  messages=self.client.get(f"/api/sessions/{sess['session_id']}/messages").json(); self.assertEqual({x['body'] for x in messages},{'一','二'})
  state=self.client.get('/api/student/state',headers={'X-Student-Session':first['student_token']}); self.assertEqual(state.status_code,200); self.assertEqual(state.json()['status'],'confirmed')

 def test_cross_course_denial_and_migrations(self):
  other=self.store.create(CourseCreate(name='其他')); self.assertEqual(self.client.get(f"/api/courses/{other.id}/classes").status_code,404)

if __name__=='__main__': unittest.main()
