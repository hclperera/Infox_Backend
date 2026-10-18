"""Real HTTP/router tests against a temporary SQL store, never production.

SQLite adapts MySQL placeholders and omits FOR UPDATE. These tests exercise SQL,
authentication and HTTP contracts, but do not prove MySQL locking/migration behavior.
"""
import sqlite3
from contextlib import closing
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import auth, braille, settings
from security import hash_password, verify_password
from services import sessions


class Cursor:
    def __init__(self, connection, dictionary=False):
        self.raw = connection.cursor()
        self.dictionary = dictionary

    def execute(self, sql, params=()):
        params = tuple(p.isoformat(' ') if isinstance(p, datetime) else p for p in params)
        self.raw.execute(sql.replace('%s', '?').replace(' FOR UPDATE', ''), params)

    def fetchone(self):
        row = self.raw.fetchone()
        if row is None or not self.dictionary:
            return row
        result = dict(zip((d[0] for d in self.raw.description), row))
        for key in ('access_expires_at', 'refresh_expires_at', 'locked_until'):
            if key in result and result[key] is not None:
                result[key] = datetime.fromisoformat(result[key])
        return result

    @property
    def lastrowid(self):
        return self.raw.lastrowid

    def close(self):
        self.raw.close()


class Connection:
    def __init__(self, path):
        self.raw = sqlite3.connect(path)
        self.raw.execute('PRAGMA foreign_keys = ON')

    def cursor(self, dictionary=False):
        return Cursor(self.raw, dictionary)

    def commit(self):
        self.raw.commit()

    def rollback(self):
        self.raw.rollback()

    def close(self):
        self.raw.close()


class SessionApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.password_hash = hash_password(' original password ')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / 'test.sqlite')
        with closing(sqlite3.connect(self.path)) as conn:
            conn.executescript('''
                CREATE TABLE users (user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT, email TEXT, password_hash TEXT);
                CREATE TABLE user_sessions (session_id TEXT PRIMARY KEY,
                    user_id INTEGER REFERENCES users(user_id) ON DELETE CASCADE,
                    access_token_hash TEXT UNIQUE, refresh_token_hash TEXT UNIQUE,
                    access_expires_at TEXT, refresh_expires_at TEXT, created_at TEXT);
                CREATE TABLE settings (settings_id INTEGER PRIMARY KEY, user_id INTEGER UNIQUE, speech_rate REAL,
                    voice_type TEXT, haptic_vibration INTEGER);
                CREATE TABLE login_security (user_id INTEGER PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
                    failed_attempts INTEGER NOT NULL DEFAULT 0, locked_until TEXT);
                CREATE TABLE scans (scan_id INTEGER PRIMARY KEY, user_id INTEGER,
                    status TEXT, translated_text TEXT, error_message TEXT);
                INSERT INTO scans VALUES (10, 1, 'done', 'first document', NULL);
                INSERT INTO scans VALUES (20, 2, 'done', 'private document', NULL);
            ''')
            conn.executemany('INSERT INTO users VALUES (?, ?, ?, ?)', [
                (1, 'reader', 'reader@example.com', self.password_hash),
                (2, 'other', 'other@example.com', self.password_hash),
            ])
            conn.commit()
        for module in (sessions, auth, settings, braille):
            patcher = patch.object(module, 'get_db_connection', lambda: Connection(self.path))
            patcher.start()
            self.addCleanup(patcher.stop)
        self.now = datetime(2026, 10, 18, 12)
        patcher = patch.object(sessions, 'utcnow', lambda: self.now)
        patcher.start()
        self.addCleanup(patcher.stop)
        app = FastAPI()
        app.include_router(auth.router)
        app.include_router(settings.router, prefix='/settings')
        app.include_router(braille.router)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def login(self, username='reader'):
        response = self.client.post('/login', json={
            'username': username, 'password': ' original password ',
        })
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    @staticmethod
    def headers(session):
        return {'Authorization': 'Bearer ' + session['access_token']}

    def test_fifth_failure_locks_and_correct_password_cannot_bypass(self):
        for attempt in range(5):
            response = self.client.post('/login', json={'username': ' reader ', 'password': 'wrong'})
            self.assertEqual(response.status_code, 401 if attempt < 4 else 429)
        self.assertEqual(response.headers['retry-after'], '900')
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.now += timedelta(seconds=60)
        # A separate HTTP client represents another device/process.
        with TestClient(self.client.app) as other:
            response = other.post('/login', json={'username': 'reader', 'password': ' original password '})
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers['retry-after'], '840')
        with closing(sqlite3.connect(self.path)) as conn:
            self.assertEqual(conn.execute('SELECT failed_attempts FROM login_security').fetchone()[0], 5)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM user_sessions').fetchone()[0], 0)
        self.login('other')
        self.now += timedelta(seconds=840)
        self.login()
        with closing(sqlite3.connect(self.path)) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM login_security').fetchone()[0], 0)

    def test_expired_lock_restarts_count_and_success_resets_failures(self):
        for _ in range(5):
            self.client.post('/login', json={'username': 'reader', 'password': 'wrong'})
        self.now += timedelta(minutes=15)
        self.assertEqual(self.client.post('/login', json={'username': 'reader', 'password': 'wrong'}).status_code, 401)
        with closing(sqlite3.connect(self.path)) as conn:
            self.assertEqual(conn.execute('SELECT failed_attempts, locked_until FROM login_security').fetchone(), (1, None))
        self.login()
        for _ in range(4):
            self.assertEqual(self.client.post('/login', json={'username': 'reader', 'password': 'wrong'}).status_code, 401)
        self.login()

    def test_unknown_users_and_database_failures_do_not_create_locks(self):
        for _ in range(6):
            self.assertEqual(self.client.post('/login', json={'username': 'missing', 'password': 'wrong'}).status_code, 401)
        with patch.object(auth, 'verify_password', side_effect=RuntimeError('simulated failure')):
            with self.assertRaises(RuntimeError):
                self.client.post('/login', json={'username': 'reader', 'password': 'wrong'})
        with closing(sqlite3.connect(self.path)) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM login_security').fetchone()[0], 0)

    def test_signup_validation_runs_before_database_and_hashes_password(self):
        with patch.object(auth, 'get_db_connection', side_effect=AssertionError('Must not query DB')):
            for body in ({'username': ' ', 'email': 'a@example.com', 'password': 'x'},
                         {'username': 'new', 'email': 'bad', 'password': 'x'}):
                self.assertEqual(self.client.post('/signup', json=body).status_code, 400)
        response = self.client.post('/signup', json={
            'username': ' new ', 'email': ' new+notes@example.technology ', 'password': ' pass ',
        })
        self.assertEqual(response.status_code, 201)
        with closing(sqlite3.connect(self.path)) as conn:
            row = conn.execute("SELECT email, password_hash FROM users WHERE username='new'").fetchone()
        self.assertEqual(row[0], 'new+notes@example.technology')
        self.assertTrue(verify_password(' pass ', row[1]))

    def test_login_uses_exact_password_and_stores_only_token_hashes(self):
        response = self.client.post('/login', json={'username': 'reader', 'password': 'original password'})
        self.assertEqual(response.status_code, 401)
        session = self.login()
        self.assertNotIn('password_hash', session)
        self.assertEqual(self.client.get('/auth/me', headers=self.headers(session)).json()['user_id'], 1)
        with closing(sqlite3.connect(self.path)) as conn:
            hashes = conn.execute('SELECT access_token_hash, refresh_token_hash FROM user_sessions').fetchone()
        self.assertEqual(hashes, (sessions.token_hash(session['access_token']), sessions.token_hash(session['refresh_token'])))
        self.assertEqual(session['access_expires_at'], '2026-10-18T12:30:00Z')
        self.assertEqual(session['refresh_expires_at'], '2026-11-17T12:00:00Z')

    def test_expiry_rotation_and_fixed_refresh_deadline(self):
        old = self.login()
        self.now += timedelta(minutes=31)
        self.assertEqual(self.client.get('/auth/me', headers=self.headers(old)).status_code, 401)
        response = self.client.post('/auth/refresh', json={'refresh_token': old['refresh_token']})
        self.assertEqual(response.status_code, 200)
        new = response.json()
        self.assertEqual(new['refresh_expires_at'], old['refresh_expires_at'])
        self.assertNotEqual(new['refresh_token'], old['refresh_token'])
        self.assertEqual(self.client.post('/auth/refresh', json={'refresh_token': old['refresh_token']}).status_code, 401)
        self.assertEqual(self.client.get('/auth/me', headers=self.headers(new)).status_code, 200)
        self.now += timedelta(days=30)
        self.assertEqual(self.client.post('/auth/refresh', json={'refresh_token': new['refresh_token']}).status_code, 401)

    def test_logout_revokes_access_and_refresh_but_not_other_device(self):
        first, second = self.login(), self.login()
        self.assertEqual(self.client.post('/auth/logout', json={'refresh_token': first['refresh_token']}).status_code, 200)
        self.assertEqual(self.client.get('/auth/me', headers=self.headers(first)).status_code, 401)
        self.assertEqual(self.client.post('/auth/refresh', json={'refresh_token': first['refresh_token']}).status_code, 401)
        self.assertEqual(self.client.get('/auth/me', headers=self.headers(second)).status_code, 200)

    def test_password_change_revokes_every_session(self):
        first, second = self.login(), self.login()
        payload = {'user_id': 1, 'current_password': 'wrong', 'new_password': ' new password '}
        self.assertEqual(self.client.put('/change-password', headers=self.headers(first), json=payload).status_code, 400)
        payload['current_password'] = ' original password '
        self.assertEqual(self.client.put('/change-password', headers=self.headers(first), json=payload).status_code, 200)
        for token in (first, second):
            self.assertEqual(self.client.get('/auth/me', headers=self.headers(token)).status_code, 401)
            self.assertEqual(self.client.post('/auth/refresh', json={'refresh_token': token['refresh_token']}).status_code, 401)
        self.assertEqual(self.client.post('/login', json={'username': 'reader', 'password': ' new password '}).status_code, 200)

    def test_protected_routes_and_cross_account_access(self):
        for path in ('/auth/me', '/settings/1', '/scan/10'):
            self.assertEqual(self.client.get(path).status_code, 401)
        headers = self.headers(self.login())
        self.assertEqual(self.client.get('/settings/2', headers=headers).status_code, 403)
        self.assertEqual(self.client.get('/scan/20', headers=headers).status_code, 404)
        self.assertEqual(self.client.get('/scan/10', headers=headers).status_code, 200)
        self.assertEqual(self.client.put('/settings/', headers=headers, json={
            'user_id': 2, 'speech_rate': .5, 'voice_type': 'Female', 'haptic_vibration': True,
        }).status_code, 403)
        self.assertEqual(self.client.put('/update-username', headers=headers, json={
            'user_id': 2, 'new_username': 'hijacked',
        }).status_code, 403)
        self.assertEqual(self.client.put('/change-password', headers=headers, json={
            'user_id': 2, 'current_password': ' original password ', 'new_password': 'hijacked',
        }).status_code, 403)
        with patch.object(braille, '_save_uploaded_image') as save:
            response = self.client.post('/scan', headers=headers, data={'user_id': '2'},
                                        files={'file': ('test.jpg', b'image', 'image/jpeg')})
            self.assertEqual(response.status_code, 403)
            save.assert_not_called()

    def test_deleted_user_cannot_access_or_refresh(self):
        token = self.login()
        conn = Connection(self.path)
        conn.raw.execute('DELETE FROM users WHERE user_id=1')
        conn.commit()
        conn.close()
        self.assertEqual(self.client.get('/auth/me', headers=self.headers(token)).status_code, 401)
        self.assertEqual(self.client.post('/auth/refresh', json={'refresh_token': token['refresh_token']}).status_code, 401)

    def test_own_profile_settings_and_scan_upload_still_work(self):
        headers = self.headers(self.login())
        settings_body = {'user_id': 1, 'speech_rate': .7, 'voice_type': 'Female', 'haptic_vibration': True}
        self.assertEqual(self.client.put('/settings/', headers=headers, json=settings_body).status_code, 200)
        self.assertEqual(self.client.get('/settings/1', headers=headers).json()['speech_rate'], .7)
        settings_body['speech_rate'] = .9
        self.assertEqual(self.client.put('/settings/', headers=headers, json=settings_body).status_code, 200)
        self.assertEqual(self.client.put('/update-username', headers=headers, json={
            'user_id': 1, 'new_username': 'renamed',
        }).status_code, 200)
        self.assertEqual(self.client.get('/auth/me', headers=headers).json()['username'], 'renamed')
        with patch.object(braille, '_save_uploaded_image', return_value='test.jpg'), \
                patch.object(braille, '_insert_scan_record', return_value=30), \
                patch.object(braille, 'process_scan_task') as process:
            response = self.client.post('/scan', headers=headers, data={'user_id': '1'},
                                        files={'file': ('test.jpg', b'image', 'image/jpeg')})
            self.assertEqual(response.status_code, 201)
            self.assertEqual(response.json()['scan_id'], 30)
            process.assert_called_once_with(30, 'test.jpg')


if __name__ == '__main__':
    unittest.main()
