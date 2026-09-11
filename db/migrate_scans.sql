-- Run this ONLY on the existing production database
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
