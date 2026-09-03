-- Create Users Table (if it doesn't already exist)
CREATE TABLE IF NOT EXISTS users (
    user_id INT PRIMARY KEY AUTO_INCREMENT,
    email VARCHAR(255) NOT NULL,
    username VARCHAR(100) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Create Settings Table
CREATE TABLE IF NOT EXISTS settings (
    settings_id INT PRIMARY KEY AUTO_INCREMENT,
    user_id INT NOT NULL UNIQUE,
    speech_rate FLOAT NOT NULL,
    voice_type VARCHAR(50) NOT NULL,
    haptic_vibration BOOLEAN NOT NULL DEFAULT TRUE,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- ============================================================
-- FR 35: Audit Logs
-- Tracks all admin actions (VIEW_USER, DELETE_USER).
-- No admin_id column — single hardcoded admin account.
-- No before/after states — logs only who was acted upon.
-- ============================================================
CREATE TABLE IF NOT EXISTS audit_logs (
    log_id        INT PRIMARY KEY AUTO_INCREMENT,
    action_type   VARCHAR(50)  NOT NULL,           -- 'VIEW_USER' | 'DELETE_USER'
    target_user_id INT         NOT NULL,            -- ID of the user acted upon
    target_username VARCHAR(100) NOT NULL,          -- Username snapshot at time of action
    timestamp     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Immutability: block any UPDATE on audit_logs
DELIMITER //
CREATE TRIGGER prevent_audit_log_update
BEFORE UPDATE ON audit_logs
FOR EACH ROW BEGIN
    SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'Audit logs are immutable and cannot be modified.';
END //

-- Immutability: block any DELETE on audit_logs
CREATE TRIGGER prevent_audit_log_delete
BEFORE DELETE ON audit_logs
FOR EACH ROW BEGIN
    SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'Audit logs are immutable and cannot be deleted.';
END //
DELIMITER ;

-- ============================================================
-- Scans Table
-- One row per uploaded braille image.
-- image_path  → permanent file path on the server
-- status      → 'pending' | 'done' | 'failed'
-- ============================================================
CREATE TABLE IF NOT EXISTS scans (
    scan_id          INT PRIMARY KEY AUTO_INCREMENT,
    user_id          INT NOT NULL,
    image_path       VARCHAR(500) NOT NULL,
    translated_text  TEXT,
    status           VARCHAR(20) NOT NULL DEFAULT 'pending',
    error_message    VARCHAR(500),
    created_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);