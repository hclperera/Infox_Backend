from fastapi import APIRouter, HTTPException, status, Depends, Response, BackgroundTasks
from schemas import PasswordResetRequest, PasswordResetConfirm
from services import password_recovery
from services.registration_validation import is_valid_registration_email
from schemas import UserSignup, UserLogin, UpdateUsernameRequest, ChangePasswordRequest, RefreshSessionRequest
from security import hash_password, verify_password
from database import get_db_connection
from services.registration_validation import registration_error
from services.sessions import create_session, refresh_session, logout_session, require_user, require_owner, public_user

def prevent_auth_caching(response: Response):
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Pragma'] = 'no-cache'


router = APIRouter(dependencies=[Depends(prevent_auth_caching)])


@router.post('/auth/password-reset/request', status_code=202)
def request_password_reset(request: PasswordResetRequest, background: BackgroundTasks):
    if not is_valid_registration_email(request.email.strip()):
        raise HTTPException(400, 'Please enter a valid email address.')
    password_recovery.configuration()
    background.add_task(password_recovery.issue_reset, request.email)
    return {'success': True, 'message': password_recovery.REQUEST_MESSAGE, 'resend_after_seconds': 60}


@router.post('/auth/password-reset/confirm')
def confirm_password_reset(request: PasswordResetConfirm):
    return password_recovery.reset_password(request.email, request.code, request.new_password)

@router.post("/signup", status_code=status.HTTP_201_CREATED)
def signup(user: UserSignup):
    error = registration_error(user.username, user.email, user.password)
    if error:
        raise HTTPException(status_code=400, detail=error)
    user.username = user.username.strip()
    user.email = user.email.strip()
    connection = get_db_connection()
    cursor = connection.cursor()
    
    # Check if user exists
    cursor.execute(
        "SELECT user_id FROM users WHERE username = %s OR email = %s", 
        (user.username, user.email)
    )
    
    if cursor.fetchone():
        cursor.close()
        connection.close()
        raise HTTPException(status_code=400, detail="Username or Email is already registered")
    
    # Hash password and insert
    hashed_pwd = hash_password(user.password)
    
    try:
        cursor.execute(
            "INSERT INTO users (username, email, password_hash) VALUES (%s, %s, %s)",
            (user.username, user.email, hashed_pwd)
        )
        connection.commit()
        return {"success": True, "message": "User registered successfully"}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    
    finally:
        cursor.close()
        connection.close()


@router.post("/login")
def login(user: UserLogin):
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    
    try:
        cursor.execute("SELECT * FROM users WHERE username = %s FOR UPDATE", (user.username.strip(),))
        db_user = cursor.fetchone()
        if not db_user or not verify_password(user.password, db_user['password_hash']):
            raise HTTPException(401, 'Invalid username or password')
        result = create_session(cursor, db_user)
        connection.commit()
        return result
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()


@router.post('/auth/refresh')
def refresh(request: RefreshSessionRequest):
    return refresh_session(request.refresh_token)


@router.post('/auth/logout')
def logout(request: RefreshSessionRequest):
    logout_session(request.refresh_token)
    return {'success': True}


@router.get('/auth/me')
def me(user=Depends(require_user)):
    return public_user(user)

@router.put("/update-username")
async def update_username(request: UpdateUsernameRequest, authenticated_user=Depends(require_user)):
    require_owner(authenticated_user, request.user_id)
    request.new_username = request.new_username.strip()
    if not request.new_username:
        raise HTTPException(400, 'Please enter your username.')
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        # Check if user exists
        cursor.execute(
            "SELECT user_id FROM users WHERE user_id = %s",
            (request.user_id,)
        )
        user = cursor.fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        # Check if new username is already taken by someone else
        cursor.execute(
            "SELECT user_id FROM users WHERE username = %s AND user_id != %s",
            (request.new_username, request.user_id)
        )
        existing = cursor.fetchone()
        if existing:
            raise HTTPException(status_code=400, detail="Username already taken")
        # Update username
        cursor.execute(
            "UPDATE users SET username = %s WHERE user_id = %s",
            (request.new_username, request.user_id)
        )
        conn.commit()
        return {"success": True, "message": "Username updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    finally:
        cursor.close()
        conn.close()

@router.put("/change-password")
async def change_password(request: ChangePasswordRequest, authenticated_user=Depends(require_user)):
    require_owner(authenticated_user, request.user_id)
    if not request.new_password:
        raise HTTPException(400, 'Please enter your new password.')
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        # Fetch user with current password hash
        cursor.execute(
            "SELECT user_id, password_hash FROM users WHERE user_id = %s FOR UPDATE",
            (request.user_id,)
        )
        user = cursor.fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        # Verify current password against stored hash
        if not verify_password(request.current_password, user["password_hash"]):
            raise HTTPException(status_code=400, detail="Current password is incorrect")
        # Hash new password and update
        new_hash = hash_password(request.new_password)
        cursor.execute(
            "UPDATE users SET password_hash = %s WHERE user_id = %s",
            (new_hash, request.user_id)
        )
        cursor.execute('DELETE FROM user_sessions WHERE user_id = %s', (request.user_id,))
        password_recovery.invalidate_code(cursor, request.user_id)
        conn.commit()
        return {"success": True, "message": "Password changed successfully"}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    finally:
        cursor.close()
        conn.close()
