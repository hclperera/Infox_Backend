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

/*
-- Create Document Table
CREATE TABLE IF NOT EXISTS documents (
    doc_id INT PRIMARY KEY AUTO_INCREMENT,
    user_id INT NOT NULL,
    title VARCHAR(255) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- Create Image Table
CREATE TABLE IF NOT EXISTS images (
    image_id INT PRIMARY KEY AUTO_INCREMENT,
    doc_id INT NOT NULL,
    image_path VARCHAR(255) NOT NULL,
    uploaded_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (doc_id) REFERENCES documents(doc_id) ON DELETE CASCADE
);

-- Create Processing_Result Table
CREATE TABLE IF NOT EXISTS processing_results (
    result_id INT PRIMARY KEY AUTO_INCREMENT,
    image_id INT NOT NULL,
    binary_matrix TEXT NOT NULL,
    translated_text TEXT NOT NULL,
    confidence_score DECIMAL(5,2) NOT NULL,
    FOREIGN KEY (image_id) REFERENCES images(image_id) ON DELETE CASCADE
);
*/
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

-- Server-enforced login lockout. Timestamps are UTC.
CREATE TABLE IF NOT EXISTS login_security (
    user_id INT PRIMARY KEY,
    failed_attempts INT NOT NULL DEFAULT 0,
    locked_until DATETIME(6) NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- Single-use password recovery state. All times are UTC.
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
