from fastapi import APIRouter, HTTPException, status
from schemas import UserSettings
from database import get_db_connection

router = APIRouter()

@router.get("/{user_id}")
def get_settings(user_id: int):
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    
    try:
        cursor.execute("SELECT * FROM settings WHERE user_id = %s", (user_id,))
        settings = cursor.fetchone()
        
        if not settings:
            # Return default settings if none exist yet
            return {
                "user_id": user_id,
                "speech_rate": 0.5,
                "voice_type": "Female",
                "haptic_vibration": True
            }
            
        return settings
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
        
    finally:
        cursor.close()
        connection.close()


@router.put("/")
def update_settings(settings: UserSettings):
    connection = get_db_connection()
    cursor = connection.cursor()
    
    try:
        # Check if settings already exist for this user
        cursor.execute("SELECT settings_id FROM settings WHERE user_id = %s", (settings.user_id,))
        existing = cursor.fetchone()
        
        if existing:
            # Update
            cursor.execute(
                """
                UPDATE settings 
                SET speech_rate = %s, voice_type = %s, haptic_vibration = %s 
                WHERE user_id = %s
                """,
                (settings.speech_rate, settings.voice_type, settings.haptic_vibration, settings.user_id)
            )
        else:
            # Insert
            cursor.execute(
                """
                INSERT INTO settings (user_id, speech_rate, voice_type, haptic_vibration) 
                VALUES (%s, %s, %s, %s)
                """,
                (settings.user_id, settings.speech_rate, settings.voice_type, settings.haptic_vibration)
            )
            
        connection.commit()
        return {"success": True, "message": "Settings saved successfully"}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
        
    finally:
        cursor.close()
        connection.close()
