-- Apply before deploying the session-enabled backend. All timestamps are UTC.
CREATE TABLE IF NOT EXISTS user_sessions (
    session_id CHAR(32) PRIMARY KEY,
    user_id INT NOT NULL,
    access_token_hash CHAR(64) NOT NULL UNIQUE,
    refresh_token_hash CHAR(64) NOT NULL UNIQUE,
    access_expires_at DATETIME(6) NOT NULL,
    refresh_expires_at DATETIME(6) NOT NULL,
    created_at DATETIME(6) NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);
