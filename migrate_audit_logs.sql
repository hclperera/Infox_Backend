CREATE TABLE IF NOT EXISTS audit_logs (
    log_id         INT PRIMARY KEY AUTO_INCREMENT,
    action_type    VARCHAR(50)  NOT NULL,
    target_user_id INT          NOT NULL,
    target_username VARCHAR(100) NOT NULL,
    timestamp      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
);

DROP TRIGGER IF EXISTS prevent_audit_log_update;
DROP TRIGGER IF EXISTS prevent_audit_log_delete;

CREATE TRIGGER prevent_audit_log_update
BEFORE UPDATE ON audit_logs
FOR EACH ROW BEGIN
    SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'Audit logs are immutable and cannot be modified.';
END;

CREATE TRIGGER prevent_audit_log_delete
BEFORE DELETE ON audit_logs
FOR EACH ROW BEGIN
    SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'Audit logs are immutable and cannot be deleted.';
END;
