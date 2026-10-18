-- Apply before deploying server-enforced login lockout. Timestamps are UTC.
CREATE TABLE IF NOT EXISTS login_security (
    user_id INT PRIMARY KEY,
    failed_attempts INT NOT NULL DEFAULT 0,
    locked_until DATETIME(6) NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);
