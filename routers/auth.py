from fastapi import APIRouter, HTTPException, status
from schemas import UserSignup, UserLogin, UpdateUsernameRequest, ChangePasswordRequest
from security import hash_password, verify_password
from database import get_db_connection

# Create the router instance
router = APIRouter()

@router.post("/signup", status_code=status.HTTP_201_CREATED)
def signup(user: UserSignup):
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
    
    # Fetch user by username
    cursor.execute("SELECT * FROM users WHERE username = %s", (user.username,))
    db_user = cursor.fetchone()
    
    cursor.close()
    connection.close()
    
    # Verify user exists and password is correct
    if not db_user or not verify_password(user.password, db_user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Invalid username or password"
        )
        
    return {
        "success": True, 
        "message": "Login successful",
        "user_id": db_user["user_id"],
        "username": db_user["username"],
        "email": db_user["email"]
    }

@router.put("/update-username")
async def update_username(request: UpdateUsernameRequest):
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
async def change_password(request: ChangePasswordRequest):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        # Fetch user with current password hash
        cursor.execute(
            "SELECT user_id, password_hash FROM users WHERE user_id = %s",
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
        conn.commit()
        return {"success": True, "message": "Password changed successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    finally:
        cursor.close()
        conn.close()
