import tempfile, unittest
from pathlib import Path
from fastapi.testclient import TestClient
from src.course_data import CourseStore, get_course_store
from src.web_api import app
from tests.auth_helpers import login_test_client

class CollaborationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.store=CourseStore(Path(self.tmp.name)/'db.sqlite'); app.dependency_overrides[get_course_store]=lambda:self.store; self.c=TestClient(app); login_test_client(self.c,self.store)
        course=self.c.post('/api/courses',json={'name':'协作课程'}).json(); self.course=course
        cls=self.c.post(f"/api/courses/{course['id']}/classes",json={'name':'一班'}).json(); self.cls=cls
        self.session=self.c.post(f"/api/classes/{cls['class_id']}/sessions").json()
    def tearDown(self): app.dependency_overrides.clear(); self.c.close(); self.tmp.cleanup()
    def test_round_token_and_atomic_claim_accept_release(self):
        r=self.c.post('/api/collaboration/rounds',json={'class_id':self.cls['class_id'],'session_id':self.session['session_id'],'feature_type':'question_optimize'}); self.assertEqual(r.status_code,200); token=r.json()['round_token']; rid=r.json()['round_id']
        # No roster match means pending student cannot claim.
        joined=self.c.post(f"/api/join/{self.session['join_token']}",json={'name':'未登记'}).json(); self.assertEqual(joined['status'],'pending')
        self.assertEqual(self.c.post(f'/api/collaboration/tokens/{token}/claim',headers={'X-Student-Session':joined['student_token']}).status_code,403)
        self.assertEqual(self.c.post(f'/api/collaboration/rounds/{rid}/complete').status_code,200)
    def test_feature_rounds_are_independent_and_end_invalidates(self):
        a=self.c.post('/api/collaboration/rounds',json={'class_id':self.cls['class_id'],'session_id':self.session['session_id'],'feature_type':'question_optimize'}).json()
        b=self.c.post('/api/collaboration/rounds',json={'class_id':self.cls['class_id'],'session_id':self.session['session_id'],'feature_type':'answer_evaluate'}).json()
        self.assertNotEqual(a['round_id'],b['round_id']); self.assertEqual(self.c.post(f"/api/sessions/{self.session['session_id']}/end").status_code,200)
        self.assertEqual(self.c.post('/api/collaboration/rounds',json={'class_id':self.cls['class_id'],'session_id':self.session['session_id'],'feature_type':'presentation_questions'}).status_code,409)

if __name__=='__main__': unittest.main()
