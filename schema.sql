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
    user_id INT NOT NULL,
    speech_rate FLOAT NOT NULL,
    voice_type VARCHAR(50) NOT NULL,
    haptic_vibration BOOLEAN NOT NULL DEFAULT TRUE,
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