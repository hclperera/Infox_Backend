-- Apply after the sessions and login-lockout migrations. All times are UTC.
CREATE TABLE IF NOT EXISTS password_reset_state (
    user_id INT PRIMARY KEY,
    code_hash CHAR(64) NULL,
    nonce CHAR(32) NULL,
    expires_at DATETIME(6) NULL,
    failed_attempts INT NOT NULL DEFAULT 0,
    sent_at DATETIME(6) NOT NULL,
    window_started_at DATETIME(6) NOT NULL,
    send_count INT NOT NULL DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);
