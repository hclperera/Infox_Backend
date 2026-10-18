"""Single-use email codes. Secrets and email delivery stay on the server."""
import hashlib
import hmac
import json
import logging
import os
import secrets
import uuid
from datetime import timedelta
from urllib.request import Request, urlopen

from fastapi import HTTPException

from database import get_db_connection
from security import hash_password
from services import sessions

CODE_LIFETIME = timedelta(minutes=10)
RESEND_DELAY = timedelta(seconds=60)
SEND_WINDOW = timedelta(hours=1)
MAX_SENDS = 5
MAX_GUESSES = 5
REQUEST_MESSAGE = 'If this email is registered and eligible, a reset code will arrive shortly. Check your inbox and spam folder.'
INVALID_CODE = 'The code is invalid or expired. Request a new code if needed.'
logger = logging.getLogger(__name__)


def configuration():
    key = os.getenv('RESEND_API_KEY', '').strip()
    sender = os.getenv('RESEND_FROM_EMAIL', '').strip()
    secret = os.getenv('PASSWORD_RESET_SECRET', '')
    if not key or not sender or len(secret.encode('utf-8')) < 32:
        raise HTTPException(503, 'Password recovery is temporarily unavailable. Please try again later.')
    return key, sender, secret


def digest(user_id, nonce, code, secret):
    return hmac.new(secret.encode('utf-8'), f'{user_id}:{nonce}:{code}'.encode('utf-8'), hashlib.sha256).hexdigest()


def send_code(email, code, nonce, key, sender):
    payload = {
        'from': sender,
        'to': [email],
        'subject': 'Your InfoX password reset code',
        'text': (f'Your InfoX password reset code is: {code}\n\n'
                 'Enter it in the InfoX app with your new password. '
                 'It expires in 10 minutes and can be used once. '
                 'Only the most recently requested code works.\n\n'
                 'If you did not request this, you can ignore this email. '
                 'Do not share this code with anyone.'),
    }
    request = Request('https://api.resend.com/emails', data=json.dumps(payload).encode('utf-8'),
                      headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json',
                               'User-Agent': 'InfoX/1.0', 'Idempotency-Key': f'password-reset/{nonce}'},
                      method='POST')
    with urlopen(request, timeout=10) as response:
        if response.status not in (200, 201, 202):
            raise RuntimeError('Email provider rejected delivery')


def lookup_user(cursor, email):
    # Do not choose arbitrarily if a legacy database contains duplicate emails.
    cursor.execute('SELECT user_id, email FROM users WHERE LOWER(email) = %s ORDER BY user_id LIMIT 2 FOR UPDATE',
                   (email.strip().lower(),))
    user = cursor.fetchone()
    duplicate = cursor.fetchone()
    return user if user and not duplicate else None


def issue_reset(email):
    """Background work: identical public response regardless of account/delivery."""
    conn = cursor = None
    try:
        key, sender, secret = configuration()
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        user = lookup_user(cursor, email)
        if not user:
            return
        cursor.execute('SELECT * FROM password_reset_state WHERE user_id = %s', (user['user_id'],))
        state = cursor.fetchone()
        now = sessions.utcnow()
        in_window = state and now < state['window_started_at'] + SEND_WINDOW
        if state and (now < state['sent_at'] + RESEND_DELAY or (in_window and state['send_count'] >= MAX_SENDS)):
            return
        code = f'{secrets.randbelow(100000000):08d}'
        nonce = uuid.uuid4().hex
        hashed = digest(user['user_id'], nonce, code, secret)
        window_start = state['window_started_at'] if in_window else now
        count = state['send_count'] + 1 if in_window else 1
        values = (hashed, nonce, now + CODE_LIFETIME, now, window_start, count, user['user_id'])
        if state:
            cursor.execute('UPDATE password_reset_state SET code_hash = %s, nonce = %s, expires_at = %s, '
                           'sent_at = %s, window_started_at = %s, send_count = %s, failed_attempts = 0 WHERE user_id = %s', values)
        else:
            cursor.execute('INSERT INTO password_reset_state '
                           '(code_hash, nonce, expires_at, sent_at, window_started_at, send_count, user_id) '
                           'VALUES (%s, %s, %s, %s, %s, %s, %s)', values)
        # Commit before sending; never retain a database lock during network IO.
        conn.commit()
        send_code(user['email'], code, nonce, key, sender)
    except Exception:
        if conn:
            conn.rollback()
        # Never log codes, email addresses, API keys, or provider response bodies.
        logger.error('Password recovery processing or email delivery failed; check database and Resend configuration.')
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def reset_password(email, code, password):
    _, _, secret = configuration()
    if not password or '\x00' in password or len(password.encode('utf-8')) > 72:
        raise HTTPException(400, 'Enter a password of 1 to 72 UTF-8 bytes without null characters.')
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        user = lookup_user(cursor, email)
        if not user:
            raise HTTPException(400, INVALID_CODE)
        cursor.execute('SELECT * FROM password_reset_state WHERE user_id = %s', (user['user_id'],))
        state = cursor.fetchone()
        if (not state or not state['code_hash'] or not state['expires_at']
                or state['expires_at'] <= sessions.utcnow() or state['failed_attempts'] >= MAX_GUESSES):
            raise HTTPException(400, INVALID_CODE)
        if not hmac.compare_digest(state['code_hash'], digest(user['user_id'], state['nonce'], code, secret)):
            cursor.execute('UPDATE password_reset_state SET failed_attempts = failed_attempts + 1 WHERE user_id = %s',
                           (user['user_id'],))
            conn.commit()
            raise HTTPException(400, INVALID_CODE)
        cursor.execute('UPDATE users SET password_hash = %s WHERE user_id = %s',
                       (hash_password(password), user['user_id']))
        cursor.execute('DELETE FROM user_sessions WHERE user_id = %s', (user['user_id'],))
        cursor.execute('DELETE FROM login_security WHERE user_id = %s', (user['user_id'],))
        invalidate_code(cursor, user['user_id'])
        conn.commit()
        return {'success': True, 'message': 'Password reset successfully. Please log in with your new password.'}
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


def invalidate_code(cursor, user_id):
    # Keep sending quotas even after a reset or authenticated password change.
    cursor.execute('UPDATE password_reset_state SET code_hash = NULL, nonce = NULL, expires_at = NULL '
                   'WHERE user_id = %s', (user_id,))
