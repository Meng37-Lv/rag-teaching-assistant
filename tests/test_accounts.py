from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.auth import AccountStore, SESSION_TTL_SECONDS, verify_password
from src.course_data import CourseStore, get_course_store
from src.migrations import migrate_accounts
from src.teaching_history import TeachingHistoryStore, get_history_store
from src.web_api import app


class AccountTests(unittest.TestCase):
    def test_authorized_mock_question_and_answer_preserve_history_isolation(self):
        from unittest.mock import Mock
        from src.rag_service import RAGService
        from src.retriever import RetrievedChunk
        from src.llm_client import LLMCompletion
        from tests.test_components import valid_question_data, valid_answer_data
        self.register_and_login(self.a)
        self.register_and_login(self.b, '13800000002')
        course = self.a.post('/api/courses', json={'name': '临时教学课程'}).json()
        self.store.set_status(course['id'], 'ready')
        service = RAGService.__new__(RAGService)
        service.settings = SimpleNamespace(max_context_chars=1800, max_chunk_chars=600)
        service.retriever = Mock()
        service.retriever.retrieve.return_value = [RetrievedChunk(1, '深度学习通过多层表示学习特征。', 270, 0.9, '第270页')]
        service.llm = Mock()
        service.llm.complete.side_effect = [LLMCompletion(json.dumps(valid_question_data(), ensure_ascii=False), 'stop', 100, 900),
                                            LLMCompletion(json.dumps(valid_answer_data(), ensure_ascii=False), 'stop', 100, 900)]
        runtime = SimpleNamespace(service=service, source_mapper=SimpleNamespace(sanitize_value=lambda value: value), settings=SimpleNamespace(default_top_k=3))
        with patch('src.web_api._get_course_runtime', return_value=runtime):
            question = self.a.post('/api/question-optimize', json={'course_id': course['id'], 'question': '什么是深度学习？'})
            self.assertEqual(question.status_code, 200)
            self.assertEqual(len(question.json()['optimized_questions']), 3)
            self.assertEqual(len(question.json()['deep_questions']), 2)
            answer = self.a.post('/api/answer-evaluate', json={'course_id': course['id'], 'question': '深度学习如何学习特征？', 'student_answer': '深度学习通过多层表示学习特征。'})
            self.assertEqual(answer.status_code, 200)
            self.assertEqual(answer.json()['score'], 75)
        self.assertEqual(service.llm.complete.call_count, 2)
        self.assertEqual(self.a.get(f"/api/courses/{course['id']}/history").json()['total'], 2)
        self.assertEqual(self.b.get(f"/api/courses/{course['id']}/history").status_code, 404)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = CourseStore(Path(self.tmp.name) / 'courses.db')
        self.history = TeachingHistoryStore(self.store.db_path)
        app.dependency_overrides[get_course_store] = lambda: self.store
        app.dependency_overrides[get_history_store] = lambda: self.history
        self.a = TestClient(app)
        self.b = TestClient(app)
        self.anonymous = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.tmp.cleanup()

    def register_and_login(self, client, phone='13800000001', name='同名教师', password=' x '):
        result = client.post('/api/auth/register', json=dict(account_name=name, phone=phone, password=password, confirm_password=password))
        self.assertEqual(result.status_code, 201)
        self.assertEqual(result.json()['message'], '注册成功，请登录')
        self.assertNotIn('password', result.text)
        login = client.post('/api/auth/login', json=dict(phone=phone, password=password))
        self.assertEqual(login.status_code, 200)
        client.headers['Authorization'] = 'Bearer ' + login.json()['token']
        return result.json()['account']

    def test_register_same_names_unique_phone_and_no_auto_claim(self):
        a = self.register_and_login(self.a)
        b = self.register_and_login(self.b, '13800000002')
        self.assertNotEqual(a['account_id'], b['account_id'])
        self.assertEqual(a['account_name'], b['account_name'])
        self.assertEqual(self.a.get('/api/courses').json(), [])
        self.assertEqual(self.b.get('/api/courses').json(), [])
        duplicate = self.anonymous.post('/api/auth/register', json=dict(account_name='不同名', phone=a['phone'], password='a', confirm_password='a'))
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(self.anonymous.post('/api/auth/login', json=dict(phone=a['phone'], password='x')).status_code, 401)
        self.assertEqual(self.a.get('/api/auth/me').json(), a)
        with closing(sqlite3.connect(self.store.db_path)) as connection:
            stored = connection.execute('SELECT password_hash FROM accounts WHERE account_id = ?', (a['account_id'],)).fetchone()[0]
        self.assertTrue(verify_password(' x ', stored))
        self.assertFalse(verify_password('x', stored))
        self.assertNotIn(' x ', stored)

    def test_registration_required_mismatch_and_simple_password(self):
        base = dict(account_name='教师', phone='13800000001', password='a', confirm_password='a')
        for key in base:
            invalid = {**base, key: ''}
            self.assertEqual(self.anonymous.post('/api/auth/register', json=invalid).status_code, 400)
        self.assertEqual(self.anonymous.post('/api/auth/register', json={**base, 'confirm_password': 'b'}).status_code, 400)
        self.assertEqual(self.anonymous.post('/api/auth/register', json=base).status_code, 201)
        self.assertEqual(self.anonymous.post('/api/auth/register', json={k: v for k, v in base.items() if k != 'password'}).status_code, 422)
        malformed = self.anonymous.post('/api/auth/login', json={'phone': '13800000001', 'password': {'secret': 'never-echo'}})
        self.assertEqual(malformed.status_code, 422)
        self.assertNotIn('never-echo', malformed.text)

    def test_login_logout_and_session_expiry(self):
        self.assertEqual(self.anonymous.post('/api/auth/login', json={'phone': '13800000009', 'password': 'wrong'}).status_code, 401)
        self.register_and_login(self.a)
        token = self.a.headers['Authorization']
        self.assertEqual(self.a.post('/api/auth/logout', json={}).status_code, 200)
        self.assertEqual(self.a.get('/api/auth/me').status_code, 401)
        login = self.a.post('/api/auth/login', json={'phone': '13800000001', 'password': ' x '}).json()
        self.a.headers['Authorization'] = 'Bearer ' + login['token']
        self.assertNotEqual(token, self.a.headers['Authorization'])
        with patch('src.auth.time.time', return_value=login['expires_at']):
            self.assertEqual(self.a.get('/api/courses').status_code, 401)
        with closing(sqlite3.connect(self.store.db_path)) as connection:
            rows = connection.execute('SELECT token_hash FROM account_sessions').fetchall()
        self.assertTrue(all(login['token'] != row[0] for row in rows))

    def test_every_business_route_denies_anonymous(self):
        for method, route in [('GET', '/api/courses'), ('POST', '/api/courses'),
                              ('GET', '/api/auth/me'), ('POST', '/api/auth/logout'),
                              ('GET', '/api/courses/default/materials'), ('GET', '/api/courses/default/history'),
                              ('GET', '/api/courses/default/analytics'), ('GET', '/api/courses/default/history/export.csv'),
                              ('POST', '/api/courses/default/learning-report'), ('POST', '/api/presentation-preview'),
                              ('POST', '/api/presentation-questions'), ('POST', '/api/question-optimize'), ('POST', '/api/answer-evaluate')]:
            with self.subTest(route=route):
                response = self.anonymous.request(method, route, json={})
                self.assertEqual(response.status_code, 401)
        self.assertEqual(self.anonymous.get('/api/health').status_code, 200)

    def test_cross_account_course_material_history_exports_and_teaching(self):
        a = self.register_and_login(self.a)
        self.register_and_login(self.b, '13800000002')
        course = self.a.post('/api/courses', json={'name': '账户A课程'}).json()
        course_id = course['id']
        self.assertEqual(self.b.get('/api/courses').json(), [])
        self.assertEqual([item['id'] for item in self.a.get('/api/courses').json()], [course_id])
        base = f'/api/courses/{course_id}'
        for method, path in [('GET', base), ('PATCH', base), ('DELETE', base), ('GET', base + '/materials'),
                             ('DELETE', base + '/materials/file'), ('POST', base + '/materials/build'),
                             ('GET', base + '/materials/build-status'), ('GET', base + '/history'),
                             ('GET', base + '/history/event'), ('DELETE', base + '/history/event'),
                             ('DELETE', base + '/history'), ('GET', base + '/history/export.csv'),
                             ('GET', base + '/analytics'), ('POST', base + '/learning-report'),
                             ('POST', base + '/learning-report/export/md')]:
            with self.subTest(path=path):
                self.assertEqual(self.b.request(method, path, json={}).status_code, 404)
        for route in ('/api/question-optimize', '/api/answer-evaluate'):
            with patch('src.web_api._get_course_runtime') as runtime:
                response = self.b.post(route, json={'course_id': course_id, 'question': '问题', 'student_answer': '答案'})
                self.assertEqual(response.status_code, 404)
                runtime.assert_not_called()
        for route in ('/api/presentation-preview', '/api/presentation-questions', base + '/materials'):
            with patch('src.web_api._parse_uploaded_material') as parser:
                response = self.b.post(route, data={'course_id': course_id}, files={'file' if route.endswith('/materials') else 'files': ('x.txt', b'private')})
                self.assertEqual(response.status_code, 404)
                parser.assert_not_called()
        self.assertIsNotNone(self.store.get(course_id))
        self.assertEqual(self.a.get(base).status_code, 200)

    def test_explicit_legacy_claim_preserves_data_and_is_atomic(self):
        a = self.register_and_login(self.a)
        b = self.register_and_login(self.b, '13800000002')
        old = self.store.get('default')
        event = self.history.add(course_id='default', task_type='answer_evaluate', input_data={}, output_data={'score': 72, 'level': '简单', 'course_basis': []})
        accounts = AccountStore(self.store.db_path)
        self.assertEqual(self.a.get('/api/courses/default').status_code, 404)
        with self.assertRaises(ValueError):
            accounts.assign_legacy(a['account_id'], ['default', 'missing'])
        self.assertFalse(accounts.owns(a['account_id'], 'default'))
        accounts.assign_legacy(a['account_id'], ['default'])
        accounts.assign_legacy(a['account_id'], ['default'])
        with self.assertRaises(ValueError):
            accounts.assign_legacy(b['account_id'], ['default'])
        self.assertEqual(self.a.get('/api/courses/default').status_code, 200)
        self.assertEqual(self.b.get('/api/courses/default').status_code, 404)
        self.assertEqual(self.store.get('default'), old)
        self.assertEqual(self.history.get('default', event.id).score, 72)

    def test_migrations_repeat_and_keep_legacy_rows(self):
        event = self.history.add(course_id='default', task_type='answer_evaluate', input_data={}, output_data={'score': 72, 'course_basis': []})
        for _ in range(3):
            migrate_accounts(self.store.db_path)
        with closing(sqlite3.connect(self.store.db_path)) as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM schema_migrations').fetchone()[0], 4)
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM course_ownership').fetchone()[0], 0)
        self.assertEqual(self.history.get('default', event.id).score, 72)
        self.assertEqual(self.store.get('default').id, 'default')

    def test_pre_auth_database_keeps_course_name_and_history(self):
        legacy = Path(self.tmp.name) / 'legacy.db'
        with closing(sqlite3.connect(self.store.db_path)) as source, closing(sqlite3.connect(legacy)) as target:
            for name in ('courses', 'initialization_flags', 'teaching_events'):
                sql = source.execute('SELECT sql FROM sqlite_master WHERE name = ?', (name,)).fetchone()[0]
                target.execute(sql)
            target.execute("INSERT INTO courses VALUES ('default', '旧课程自定义名称', '', '', '', '2020-01-01', 'ready')")
            target.execute("INSERT INTO initialization_flags VALUES ('default_course')")
            target.execute("INSERT INTO teaching_events VALUES ('old', 'default', '2020-01-01', 'answer_evaluate', NULL, '{}', '{}', 72, '简单', '[]', NULL)")
            target.commit()
        legacy_store = CourseStore(legacy)
        account = AccountStore(legacy).register('新教师', '13800000005', 'a', 'a')
        self.assertEqual(legacy_store.get('default').name, '旧课程自定义名称')
        self.assertEqual(legacy_store.list(account['account_id']), [])
        self.assertEqual(TeachingHistoryStore(legacy).get('default', 'old').score, 72)

    def test_migration_rollback_on_schema_conflict(self):
        path = Path(self.tmp.name) / 'conflict.db'
        with closing(sqlite3.connect(path)) as connection:
            connection.execute('CREATE TABLE accounts (legacy TEXT)')
            connection.execute("INSERT INTO accounts VALUES ('preserved')")
            connection.commit()
        with self.assertRaises(sqlite3.OperationalError):
            migrate_accounts(path)
        with closing(sqlite3.connect(path)) as connection:
            self.assertEqual(connection.execute('SELECT * FROM accounts').fetchall(), [('preserved',)])
            self.assertIsNone(connection.execute("SELECT 1 FROM sqlite_master WHERE name = 'schema_migrations'").fetchone())

    def test_cors_supports_bearer_for_browser_and_desktop(self):
        for origin in ('http://localhost:5173', 'tauri://localhost', 'http://tauri.localhost', 'https://tauri.localhost'):
            response = self.anonymous.options('/api/auth/login', headers={
                'Origin': origin, 'Access-Control-Request-Method': 'POST',
                'Access-Control-Request-Headers': 'Authorization, Content-Type'})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers['access-control-allow-origin'], origin)
        rejected = self.anonymous.options('/api/courses', headers={'Origin': 'https://untrusted.example', 'Access-Control-Request-Method': 'GET'})
        self.assertEqual(rejected.status_code, 400)


if __name__ == '__main__':
    unittest.main()
