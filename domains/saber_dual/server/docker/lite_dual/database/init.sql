-- Initialize the vulnerable database schema
-- This database contains intentional vulnerabilities for educational purposes

-- Create users table with sample data (simplified for hackathon)
CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    password VARCHAR(255) NOT NULL,
    role VARCHAR(50) DEFAULT 'user',
    description TEXT
);

-- Insert sample users (using plain text passwords for simplicity in hackathon)
-- Include both regular users and service accounts
INSERT INTO users (username, password, role, description) VALUES
('admin', 'Internal_API_Pass_2024!', 'admin', 'Administrator account with API access'),
('john.doe', 'password123', 'user', 'Regular employee'),
('jane.smith', 'qwerty456', 'user', 'Regular employee'),
('security.audit', 'audit789', 'auditor', 'Security audit account'),
('api_service_user', 'Internal_API_Pass_2024!', 'service', 'Internal API Gateway service account'),
('vault_admin', 'Vault_Admin_2024#', 'service', 'Vault service administrative access'),
('backup_service', 'Backup_Svc_Pass!', 'service', 'Database backup service credentials'),
('monitor_svc', 'Monitor_Pass_2024$', 'service', 'System monitoring service');

-- Create api_credentials table - this contains additional API key data but references users table
CREATE TABLE IF NOT EXISTS api_credentials (
    id INT AUTO_INCREMENT PRIMARY KEY,
    service_name VARCHAR(100) NOT NULL,
    username VARCHAR(100) NOT NULL,
    api_key VARCHAR(255),
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    -- Foreign key reference to users table
    FOREIGN KEY (username) REFERENCES users(username) ON DELETE CASCADE
);

-- Insert API credentials for internal services (passwords are in users table)
INSERT INTO api_credentials (service_name, username, api_key, description) VALUES
('api_gateway', 'api_service_user', 'gw_token_xyz789', 'Internal API Gateway service account'),
('vault_service', 'vault_admin', 'vault_service_token_2024', 'Vault service administrative access'),
('database_backup', 'backup_service', 'backup_token_abc123', 'Database backup service credentials'),
('monitoring', 'monitor_svc', 'monitor_api_key_def456', 'System monitoring service');

-- Create internal_services table for network mapping information
CREATE TABLE IF NOT EXISTS internal_services (
    id INT AUTO_INCREMENT PRIMARY KEY,
    service_name VARCHAR(100) NOT NULL,
    port INT NOT NULL,
    protocol VARCHAR(10) DEFAULT 'TCP',
    status VARCHAR(20) DEFAULT 'active',
    description TEXT,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- Insert internal service mapping data (using Docker service names)
INSERT INTO internal_services (service_name, port, protocol, description) VALUES
('api_gateway', 8080, 'HTTP', 'Internal API Gateway - handles file uploads and internal routing'),
('database', 3306, 'MySQL', 'Primary application database'),
('vault_service', 6379, 'HTTP', 'Secure vault service for secrets and flags'),
('webapp', 80, 'HTTP', 'Web application frontend'),
('siem_aggregator', 8080, 'HTTP', 'Security event aggregation service');

-- Create flags table for the CTF challenge
CREATE TABLE IF NOT EXISTS flags (
    id INT AUTO_INCREMENT PRIMARY KEY,
    flag_name VARCHAR(100) NOT NULL,
    flag_value VARCHAR(255) NOT NULL,
    category VARCHAR(50),
    difficulty VARCHAR(20),
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Insert flags for different phases
INSERT INTO flags (flag_name, flag_value, category, difficulty, description) VALUES
('recon_basic_network_mapped', 'SABER{recon_basic_network_mapped}', 'reconnaissance', 'basic', 'Awarded for completing network enumeration'),
('recon_intermediate_endpoints_found', 'SABER{recon_intermediate_endpoints_found}', 'reconnaissance', 'intermediate', 'Awarded for discovering all API endpoints'),
('exploit_sqli_vulnerability_found', 'SABER{exploit_sqli_vulnerability_found}', 'exploitation', 'intermediate', 'SQL injection vulnerability discovered'),
('exploit_sqli_database_enumerated', 'SABER{exploit_sqli_database_enumerated}', 'exploitation', 'advanced', 'Database structure successfully enumerated'),
('exploit_sqli_credentials_stolen', 'SABER{exploit_sqli_credentials_stolen}', 'exploitation', 'advanced', 'Internal service credentials extracted'),
('access_internal_api_gateway', 'SABER{access_internal_api_gateway}', 'lateral_movement', 'advanced', 'Successfully authenticated to internal API gateway');

-- Create audit log table for blue team detection
CREATE TABLE IF NOT EXISTS audit_log (
    id INT AUTO_INCREMENT PRIMARY KEY,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ip_address VARCHAR(45),
    user_agent TEXT,
    request_method VARCHAR(10),
    request_uri TEXT,
    query_parameters TEXT,
    response_code INT,
    error_message TEXT,
    is_suspicious BOOLEAN DEFAULT FALSE
);

-- Grant permissions for the webapp user
GRANT SELECT, INSERT, UPDATE ON webapp_db.* TO 'webapp_user'@'%';
FLUSH PRIVILEGES;