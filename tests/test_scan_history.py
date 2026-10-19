"""History contract tests using a temporary SQL database, never production."""
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from routers import history
from services.sessions import require_user


class Connection:
    def __init__(self, path):
        self.raw = sqlite3.connect(path)
        self.raw.row_factory = sqlite3.Row
    def cursor(self, dictionary=False):
        return self
    def execute(self, sql, params):
        self.result = self.raw.execute(sql.replace('%s', '?'), params)
    def fetchall(self):
        return [dict(row) for row in self.result.fetchall()]
    def close(self):
        self.raw.close()


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / 'history.db'
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('CREATE TABLE scans (scan_id INTEGER, user_id INTEGER, status TEXT, translated_text TEXT, created_at TEXT)')
            db.executemany('INSERT INTO scans VALUES (?, ?, ?, ?, ?)', [
                (1, 1, 'done', 'one', '2026-10-19'),
                (2, 2, 'done', 'private', '2026-10-19'),
                (3, 1, 'error', None, '2026-10-19'),
                (4, 1, 'pending', None, '2026-10-19'),
                (5, 1, 'done', 'five', '2026-10-19')])
            db.commit()
        app = FastAPI()
        app.include_router(history.router)
        self.app = app
        self.client = TestClient(app)
        self.mock_db = patch.object(history, 'get_db_connection', lambda: Connection(self.path))
        self.mock_db.start()
    def tearDown(self):
        self.mock_db.stop()
        self.client.close()
        self.folder.cleanup()
    def login(self):
        self.app.dependency_overrides[require_user] = lambda: {'user_id': 1}
    def test_requires_authentication(self):
        self.assertEqual(self.client.get('/scans').status_code, 401)
    def test_only_owner_rows_with_stable_pagination(self):
        self.login()
        first = self.client.get('/scans?limit=2&user_id=2').json()
        self.assertEqual([x['scan_id'] for x in first['scans']], [5, 4])
        self.assertEqual(first['next_before'], 4)
        second = self.client.get('/scans?limit=2&before=4').json()
        self.assertEqual([x['scan_id'] for x in second['scans']], [3, 1])
        self.assertIsNone(second['next_before'])
        self.assertEqual(second['scans'][1]['translated_text'], 'one')
    def test_empty_history_and_validation(self):
        self.login()
        self.assertEqual(self.client.get('/scans?before=1').json(), {'scans': [], 'next_before': None})
        for query in ('limit=0', 'limit=101', 'before=-1'):
            self.assertEqual(self.client.get('/scans?' + query).status_code, 422)


if __name__ == '__main__':
    unittest.main()
