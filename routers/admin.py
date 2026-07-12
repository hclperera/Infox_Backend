from fastapi import APIRouter, HTTPException, Depends, Header, status
from database import get_db_connection
from pydantic import BaseModel
import jwt
import os
from datetime import datetime, timedelta

router = APIRouter()

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
SECRET_KEY = os.getenv("ADMIN_SECRET_KEY", "infox-admin-secret")


class AdminLogin(BaseModel):
    username: str
    password: str


def verify_admin_token(authorization: str = Header(...)):
    """Dependency to verify admin JWT token."""
    try:
        token = authorization.replace("Bearer ", "")
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        if payload.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Not an admin")
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


@router.post("/login")
def admin_login(creds: AdminLogin):
    if creds.username != ADMIN_USERNAME or creds.password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid admin credentials")

    token = jwt.encode(
        {"sub": "admin", "role": "admin", "exp": datetime.utcnow() + timedelta(hours=24)},
        SECRET_KEY,
        algorithm="HS256",
    )
    return {"success": True, "token": token}


@router.get("/stats")
def get_stats(admin=Depends(verify_admin_token)):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT COUNT(*) as total FROM users")
        total = cursor.fetchone()["total"]

        cursor.execute(
            "SELECT COUNT(*) as count FROM users WHERE DATE(created_at) = CURDATE()"
        )
        today = cursor.fetchone()["count"]

        cursor.execute(
            "SELECT COUNT(*) as count FROM users WHERE created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)"
        )
        week = cursor.fetchone()["count"]

        cursor.execute(
            "SELECT COUNT(*) as count FROM users WHERE created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)"
        )
        month = cursor.fetchone()["count"]

        return {
            "total_users": total,
            "new_users_today": today,
            "new_users_this_week": week,
            "new_users_this_month": month,
        }
    finally:
        cursor.close()
        conn.close()


@router.get("/users")
def get_users(
    page: int = 1,
    per_page: int = 20,
    search: str = "",
    admin=Depends(verify_admin_token),
):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        offset = (page - 1) * per_page

        if search:
            search_param = f"%{search}%"
            cursor.execute(
                "SELECT COUNT(*) as total FROM users WHERE username LIKE %s OR email LIKE %s",
                (search_param, search_param),
            )
            total = cursor.fetchone()["total"]
            cursor.execute(
                "SELECT user_id, username, email, created_at FROM users "
                "WHERE username LIKE %s OR email LIKE %s "
                "ORDER BY created_at DESC LIMIT %s OFFSET %s",
                (search_param, search_param, per_page, offset),
            )
        else:
            cursor.execute("SELECT COUNT(*) as total FROM users")
            total = cursor.fetchone()["total"]
            cursor.execute(
                "SELECT user_id, username, email, created_at FROM users "
                "ORDER BY created_at DESC LIMIT %s OFFSET %s",
                (per_page, offset),
            )

        users = cursor.fetchall()
        # Convert datetime to string for JSON serialization
        for user in users:
            if isinstance(user.get("created_at"), datetime):
                user["created_at"] = user["created_at"].isoformat()

        return {"users": users, "total": total, "page": page, "per_page": per_page}
    finally:
        cursor.close()
        conn.close()


@router.get("/users/{user_id}")
def get_user_detail(user_id: int, admin=Depends(verify_admin_token)):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT user_id, username, email, created_at FROM users WHERE user_id = %s",
            (user_id,),
        )
        user = cursor.fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        if isinstance(user.get("created_at"), datetime):
            user["created_at"] = user["created_at"].isoformat()

        cursor.execute("SELECT * FROM settings WHERE user_id = %s", (user_id,))
        settings = cursor.fetchone()

        return {"user": user, "settings": settings}
    finally:
        cursor.close()
        conn.close()


@router.delete("/users/{user_id}")
def delete_user(user_id: int, admin=Depends(verify_admin_token)):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT user_id FROM users WHERE user_id = %s", (user_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="User not found")

        cursor.execute("DELETE FROM users WHERE user_id = %s", (user_id,))
        conn.commit()
        return {"success": True, "message": "User deleted successfully"}
    finally:
        cursor.close()
        conn.close()


@router.get("/users/{user_id}/settings")
def get_user_settings(user_id: int, admin=Depends(verify_admin_token)):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM settings WHERE user_id = %s", (user_id,))
        settings = cursor.fetchone()
        if not settings:
            return {"message": "No settings configured", "settings": None}
        return {"settings": settings}
    finally:
        cursor.close()
        conn.close()


@router.get("/signup-trend")
def get_signup_trend(admin=Depends(verify_admin_token)):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT DATE(created_at) as date, COUNT(*) as count
            FROM users
            WHERE created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)
            GROUP BY DATE(created_at)
            ORDER BY date ASC
            """
        )
        data = cursor.fetchall()
        for row in data:
            if isinstance(row.get("date"), datetime):
                row["date"] = row["date"].strftime("%Y-%m-%d")
            elif hasattr(row.get("date"), "isoformat"):
                row["date"] = row["date"].isoformat()
        return {"data": data}
    finally:
        cursor.close()
        conn.close()
