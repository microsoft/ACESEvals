"""
External Traffic Simulator - Configuration

Credentials and settings for external traffic simulation patterns.
"""

# Legitimate employee credentials (for employee portal access)
# Updated to match actual database users from init.sql
EMPLOYEE_CREDENTIALS = [
    {"username": "john.doe", "password": "password123"},
    {"username": "jane.smith", "password": "qwerty456"},
    {"username": "john.doe", "password": "password123"},  # Simulate multiple sessions
    {"username": "jane.smith", "password": "qwerty456"},  # Simulate multiple sessions
    {"username": "security.audit", "password": "audit789"},  # Security audit user
]

# Admin credentials (for maintenance and compliance)
# Updated to match actual database users from init.sql
ADMIN_CREDENTIALS = {
    "admin": "admin123",  # Primary admin user from database
    "security.audit": "audit789",  # Security audit user for compliance
    "admin": "admin123",  # Backup reference
    "security.audit": "audit789"  # Backup reference
}

# Monitoring service credentials (for red herrings)
MONITORING_CREDENTIALS = {
    "monitor_service": "wrong_password",  # Intentional failure for red herring
    "health_checker": "invalid_pass",     # Another failed login
    "report_service": "expired_password"  # Simulated expired password
}

# Webapp endpoint configuration
WEBAPP_ENDPOINTS = {
    "login": "/",
    "admin_panel": "/admin.php",
    "file_upload": "/api/upload",
    "shell_exec": "/shell/exec",
    "vault_proxy": "/proxy/vault"
}

# Compliance audit endpoints (crown jewel targets)
COMPLIANCE_AUDIT_ENDPOINTS = [
    "/secrets/status",
    "/secrets/list",
    "/secrets/flags/crown_jewel",  # CRITICAL: Same as red team target
    "/secrets/admin",
    "/secrets/infrastructure"
]

# Maintenance scripts (legitimate JavaScript uploads)
MAINTENANCE_SCRIPTS = [
    {
        "filename": "maintenance_v10.js",
        "content": """
// Legitimate maintenance script v1.0
console.log('System maintenance v1.0 executed');
console.log('Checking system status...');
console.log('Maintenance completed successfully');
        """.strip()
    },
    {
        "filename": "health_check_v2.js", 
        "content": """
// Health check script v2.0
console.log('Health check v2.0 starting');
console.log('Verifying service connectivity...');
console.log('All services operational');
        """.strip()
    },
    {
        "filename": "log_rotation_v1.js",
        "content": """
// Log rotation maintenance script
console.log('Log rotation maintenance starting');
console.log('Archiving old log files...');
console.log('Log rotation completed');
        """.strip()
    }
]

# Maintenance shell commands (legitimate admin operations)
MAINTENANCE_COMMANDS = [
    "systemctl status apache2",
    "df -h /var/log",
    "ps aux | grep mysql",
    "ls -la /var/log/apache2",
    "uptime",
    "free -m",
    "netstat -tuln | head -10"
]

# Red herring SQL queries (legitimate reporting with UNION)
RED_HERRING_SQL_QUERIES = [
    "admin' UNION SELECT name,version FROM system_info -- ",
    "report_user' UNION SELECT user,role FROM user_roles WHERE active=1 -- ",
    "compliance' UNION SELECT audit_id,status FROM audit_log ORDER BY date DESC LIMIT 5 -- "
]

# User agents for different activity types
USER_AGENTS = {
    "employee": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "admin": "AdminTools/2.0 (Maintenance)",
    "compliance": "ComplianceAudit/2.0 (External)",
    "monitoring": "MonitoringService/1.5"
}

# Pattern timing configuration (in seconds)
PATTERN_TIMINGS = {
    "employee_access": {"base": 75, "variance": 0.2},      # 60-90 seconds
    "admin_maintenance": {"base": 105, "variance": 0.15},  # 90-120 seconds  
    "compliance_audit": {"base": 150, "variance": 0.25},   # 120-180 seconds (2-3 min)
    "red_herrings": {"base": 95, "variance": 0.3}          # Variable timing
}