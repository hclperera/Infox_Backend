"""Opaque mobile sessions. Only SHA-256 digests of random tokens are persisted."""
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from database import get_db_connection

ACCESS_LIFETIME = timedelta(minutes=30)
REFRESH_LIFETIME = timedelta(days=30)
bearer = HTTPBearer(auto_error=False)


def utcnow():
    # MySQL DATETIME stores no timezone; use UTC consistently for all comparisons.
    return datetime.now(timezone.utc).replace(tzinfo=None)


def token_hash(token):
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def unauthorized():
    return HTTPException(401, 'Session expired. Please log in again.',
                         headers={'WWW-Authenticate': 'Bearer'})


def public_user(user):
    return {key: user[key] for key in ('user_id', 'username', 'email')}


def _response(user, access, refresh, access_expiry, refresh_expiry):
    return dict(success=True, token_type='Bearer', access_token=access,
                refresh_token=refresh, access_expires_at=access_expiry.isoformat() + 'Z',
                refresh_expires_at=refresh_expiry.isoformat() + 'Z', **public_user(user))


def create_session(cursor, user):
    """Caller owns the transaction and must lock the user row before issuance."""
    now = utcnow()
    access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    access_expiry, refresh_expiry = now + ACCESS_LIFETIME, now + REFRESH_LIFETIME
    cursor.execute(
        'INSERT INTO user_sessions (session_id, user_id, access_token_hash, '
        'refresh_token_hash, access_expires_at, refresh_expires_at, created_at) '
        'VALUES (%s, %s, %s, %s, %s, %s, %s)',
        (uuid.uuid4().hex, user['user_id'], token_hash(access), token_hash(refresh),
         access_expiry, refresh_expiry, now))
    return _response(user, access, refresh, access_expiry, refresh_expiry)


def refresh_session(token):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            'SELECT s.session_id, s.refresh_expires_at, u.user_id, u.username, u.email '
            'FROM user_sessions s JOIN users u ON u.user_id = s.user_id '
            'WHERE s.refresh_token_hash = %s FOR UPDATE', (token_hash(token),))
        row = cursor.fetchone()
        if not row or row['refresh_expires_at'] <= utcnow():
            raise unauthorized()
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        access_expiry = min(utcnow() + ACCESS_LIFETIME, row['refresh_expires_at'])
        cursor.execute(
            'UPDATE user_sessions SET access_token_hash = %s, refresh_token_hash = %s, '
            'access_expires_at = %s WHERE session_id = %s',
            (token_hash(access), token_hash(refresh), access_expiry, row['session_id']))
        conn.commit()
        return _response(row, access, refresh, access_expiry, row['refresh_expires_at'])
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


def logout_session(token):
    # Refresh credential allows logout even when the access token has expired.
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('DELETE FROM user_sessions WHERE refresh_token_hash = %s', (token_hash(token),))
        conn.commit()
    finally:
        cursor.close()
        conn.close()


def require_user(credentials: HTTPAuthorizationCredentials = Depends(bearer)):
    if credentials is None or credentials.scheme.lower() != 'bearer':
        raise unauthorized()
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        now = utcnow()
        cursor.execute(
            'SELECT u.user_id, u.username, u.email, s.session_id '
            'FROM user_sessions s JOIN users u ON u.user_id = s.user_id '
            'WHERE s.access_token_hash = %s AND s.access_expires_at > %s '
            'AND s.refresh_expires_at > %s', (token_hash(credentials.credentials), now, now))
        user = cursor.fetchone()
        if user is None:
            raise unauthorized()
        return user
    finally:
        cursor.close()
        conn.close()


def require_owner(user, requested_user_id):
    if user['user_id'] != requested_user_id:
        raise HTTPException(403, 'You cannot access another user\'s data.')
