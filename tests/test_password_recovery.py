import json
import os
import sqlite3
from contextlib import closing
from datetime import timedelta
from unittest.mock import patch, MagicMock

from tests.test_auth_sessions import ApiTestCase
from services import password_recovery as recovery
from security import verify_password


class RecoveryTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        env = patch.dict(os.environ, {'RESEND_API_KEY': 'test-key', 'RESEND_FROM_EMAIL': 'InfoX <reset@example.com>',
                                     'PASSWORD_RESET_SECRET': 'test-secret-' * 4})
        env.start()
        self.addCleanup(env.stop)
        sender = patch.object(recovery, 'send_code')
        self.sender = sender.start()
        self.addCleanup(sender.stop)

    def request(self, email='reader@example.com'):
        return self.client.post('/auth/password-reset/request', json={'email': email})

    def confirm(self, code=None, email='reader@example.com', password=' new password '):
        if code is None:
            code = self.sender.call_args.args[1]
        return self.client.post('/auth/password-reset/confirm', json={
            'email': email, 'code': code, 'new_password': password})

    def test_generic_request_hash_only_and_success_revokes_unlocks(self):
        first, second = self.login(), self.login()
        for _ in range(5):
            self.client.post('/login', json={'username': 'reader', 'password': 'wrong'})
        response = self.request(' READER@example.com ')
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json(), self.request('missing@example.com').json())
        self.assertEqual(self.sender.call_count, 1)
        code = self.sender.call_args.args[1]
        self.assertEqual(len(code), 8)
        self.assertNotIn(code, response.text)
        with closing(sqlite3.connect(self.path)) as conn:
            row = conn.execute('SELECT code_hash, nonce FROM password_reset_state').fetchone()
        self.assertNotEqual(row[0], code)
        self.assertEqual(row[0], recovery.digest(1, row[1], code, os.environ['PASSWORD_RESET_SECRET']))
        self.assertEqual(self.confirm().status_code, 200)
        self.assertEqual(self.confirm().status_code, 400)
        for session in (first, second):
            self.assertEqual(self.client.get('/auth/me', headers=self.headers(session)).status_code, 401)
            self.assertEqual(self.client.post('/auth/refresh', json={'refresh_token': session['refresh_token']}).status_code, 401)
        self.assertEqual(self.client.post('/login', json={'username': 'reader', 'password': ' original password '}).status_code, 401)
        self.assertEqual(self.client.post('/login', json={'username': 'reader', 'password': ' new password '}).status_code, 200)

    def test_wrong_codes_exhaust_budget_and_expiry_is_enforced(self):
        self.request()
        code = self.sender.call_args.args[1]
        wrong = '11111111' if code != '11111111' else '22222222'
        for _ in range(5):
            self.assertEqual(self.confirm(wrong).status_code, 400)
        self.assertEqual(self.confirm(code).status_code, 400)
        self.now += timedelta(seconds=60)
        self.request()
        self.now += timedelta(minutes=10)
        self.assertEqual(self.confirm().status_code, 400)

    def test_resend_replaces_code_and_enforces_cooldown_and_hourly_quota(self):
        self.request()
        old = self.sender.call_args.args[1]
        self.request()
        self.assertEqual(self.sender.call_count, 1)
        self.now += timedelta(seconds=60)
        self.request()
        self.assertEqual(self.sender.call_count, 2)
        self.assertEqual(self.confirm(old).status_code, 400)
        for _ in range(4):
            self.now += timedelta(seconds=60)
            self.request()
        self.assertEqual(self.sender.call_count, 5)
        self.now += timedelta(hours=1)
        self.request()
        self.assertEqual(self.sender.call_count, 6)

    def test_code_cannot_reset_other_account_and_change_password_invalidates_it(self):
        session = self.login()
        self.request()
        self.assertEqual(self.confirm(email='other@example.com').status_code, 400)
        response = self.client.put('/change-password', headers=self.headers(session), json={
            'user_id': 1, 'current_password': ' original password ', 'new_password': 'changed normally'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.confirm().status_code, 400)

    def test_validation_missing_configuration_and_no_password_truncation(self):
        self.assertEqual(self.request('bad').status_code, 400)
        with patch.dict(os.environ, {'PASSWORD_RESET_SECRET': ''}):
            for email in ('reader@example.com', 'missing@example.com'):
                self.assertEqual(self.request(email).status_code, 503)
        self.sender.assert_not_called()
        self.request()
        self.assertEqual(self.confirm(password='a' * 73).status_code, 422)
        self.assertEqual(self.confirm(password='ආ' * 25).status_code, 400)
        self.assertEqual(self.confirm(password='a\x00b').status_code, 400)
        self.assertEqual(self.confirm('123').status_code, 422)
        self.assertEqual(self.confirm().status_code, 200)

    def test_delivery_failure_does_not_expose_account_or_provider_details(self):
        self.sender.side_effect = RuntimeError('sensitive provider details')
        with self.assertLogs(recovery.logger, level='ERROR') as logs:
            known = self.request()
        self.assertNotIn('sensitive', str(logs.output))
        self.assertEqual(known.json(), self.request('missing@example.com').json())
        self.request()
        self.assertEqual(self.sender.call_count, 1)

    def test_duplicate_email_is_not_arbitrarily_reset(self):
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute("UPDATE users SET email='reader@example.com' WHERE user_id=2")
            conn.commit()
        self.assertEqual(self.request().status_code, 202)
        self.sender.assert_not_called()
        self.assertEqual(self.confirm('12345678').status_code, 400)

    def test_failed_transaction_preserves_password_sessions_and_code(self):
        session = self.login()
        self.request()
        with patch.object(recovery, 'invalidate_code', side_effect=RuntimeError('simulated SQL error')):
            with self.assertRaises(RuntimeError):
                self.confirm()
        self.assertEqual(self.client.get('/auth/me', headers=self.headers(session)).status_code, 200)
        with closing(sqlite3.connect(self.path)) as conn:
            password = conn.execute('SELECT password_hash FROM users WHERE user_id=1').fetchone()[0]
        self.assertTrue(verify_password(' original password ', password))
        self.assertEqual(self.confirm().status_code, 200)

    def test_resend_http_contract_without_sending_real_email(self):
        # Call the original implementation, bypassing the delivery mock.
        response = MagicMock()
        response.__enter__.return_value.status = 200
        with patch.object(recovery, 'urlopen', return_value=response) as send:
            REAL_SEND_CODE('reader@example.com', '01234567', 'nonce', 'test-key', 'InfoX <reset@example.com>')
        request = send.call_args.args[0]
        self.assertEqual(request.full_url, 'https://api.resend.com/emails')
        self.assertEqual(request.get_header('Authorization'), 'Bearer test-key')
        self.assertEqual(send.call_args.kwargs['timeout'], 10)
        payload = json.loads(request.data)
        self.assertEqual(payload['to'], ['reader@example.com'])
        self.assertIn('01234567', payload['text'])


REAL_SEND_CODE = recovery.send_code
