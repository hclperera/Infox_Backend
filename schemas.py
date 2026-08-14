from pydantic import BaseModel

# Schema for the signup endpoint
class UserSignup(BaseModel):
    username: str
    email: str
    password: str

# Schema for the login endpoint
class UserLogin(BaseModel):
    username: str
    password: str

# Schema for the update username endpoint
class UpdateUsernameRequest(BaseModel):
    user_id: int
    new_username: str

# Schema for the change password endpoint 
class ChangePasswordRequest(BaseModel):
    user_id: int
    current_password: str
    new_password: str

# Schema for user settings
class UserSettings(BaseModel):
    user_id: int
    speech_rate: float
    voice_type: str
    haptic_vibration: bool
