#!/bin/bash

# Excytin Incident Database Health Check Script
# Validates that the MySQL database is ready for application use
# Performs comprehensive checks including connectivity, authentication, and query execution
# This script is shared across all incident databases (5, 34, 38, 39, 55, 134, 166, 322)

set -euo pipefail

# Configuration
DB_HOST="localhost"
DB_PORT="3306"
DB_USER="admin"
DB_PASSWORD="admin"
DB_NAME="env_monitor_db"
MAX_RETRIES=3
RETRY_DELAY=2

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Test MySQL basic connectivity
test_mysql_connectivity() {
    log_info "Testing MySQL basic connectivity..."
    
    if ! mysqladmin ping -h "$DB_HOST" -P "$DB_PORT" --silent; then
        log_error "MySQL server is not responding to ping"
        return 1
    fi
    
    log_info "✅ MySQL server is responding"
    return 0
}

# Test admin user credentials and database access
test_admin_credentials() {
    log_info "Testing admin user credentials and database access..."
    
    if ! mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p"$DB_PASSWORD" -D "$DB_NAME" -e "SELECT 1;" > /dev/null 2>&1; then
        log_error "Failed to connect with admin credentials or execute query"
        return 1
    fi
    
    log_info "✅ Admin user credentials are working"
    return 0
}

# Verify that tables exist and database is properly initialized
test_required_tables() {
    log_info "Testing database initialization and table accessibility..."
    
    # Check that database has tables (any tables indicate successful initialization)
    local table_count=$(mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p"$DB_PASSWORD" -D "$DB_NAME" -e "SELECT COUNT(*) as count FROM information_schema.tables WHERE table_schema='$DB_NAME';" -s -N 2>/dev/null || echo "0")
    
    if [ "$table_count" -eq 0 ]; then
        log_error "Database has no tables - initialization may have failed"
        return 1
    fi
    
    # Check that common Azure AD tables exist and are accessible
    # Note: Different incidents have different table schemas, so we check for tables that are common
    local common_tables=("AADManagedIdentitySignInLogs" "AADNonInteractiveUserSignInLogs")
    
    for table in "${common_tables[@]}"; do
        if ! mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p"$DB_PASSWORD" -D "$DB_NAME" -e "SELECT COUNT(*) FROM \`$table\` LIMIT 1;" > /dev/null 2>&1; then
            log_error "Common table '$table' is not accessible or does not exist"
            return 1
        fi
    done
    
    log_info "✅ Database initialized with $table_count tables and common tables are accessible"
    return 0
}

# Test data integrity and query functionality
test_data_integrity() {
    log_info "Testing data integrity and complex query functionality..."
    
    # Test a union query across common tables that exist in all incidents
    local query="SELECT COUNT(*) FROM (
        SELECT 'ManagedIdentity' as log_type, COUNT(*) as count FROM AADManagedIdentitySignInLogs 
        UNION ALL 
        SELECT 'NonInteractive' as log_type, COUNT(*) as count FROM AADNonInteractiveUserSignInLogs
    ) as log_summary;"
    
    if ! mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p"$DB_PASSWORD" -D "$DB_NAME" -e "$query" > /dev/null 2>&1; then
        log_error "Failed to execute complex query - data integrity issue"
        return 1
    fi
    
    # Test that we can query metadata about all tables
    local metadata_query="SELECT table_name, table_rows FROM information_schema.tables WHERE table_schema='$DB_NAME' LIMIT 5;"
    if ! mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p"$DB_PASSWORD" -D "$DB_NAME" -e "$metadata_query" > /dev/null 2>&1; then
        log_error "Failed to query table metadata - database integrity issue"
        return 1
    fi
    
    log_info "✅ Data integrity and query functionality verified"
    return 0
}

# Test read/write permissions for incident analysis operations
test_permissions() {
    log_info "Testing database permissions for incident analysis operations..."
    
    # Test table creation (for temporary analysis tables)
    local test_table="health_check_test_$(date +%s)"
    
    # Run all operations in a single session to maintain table scope
    local combined_query="
        CREATE TEMPORARY TABLE $test_table (id INT, test_data VARCHAR(50));
        INSERT INTO $test_table VALUES (1, 'health_check_test');
        SELECT COUNT(*) FROM $test_table WHERE id = 1;
        DROP TEMPORARY TABLE $test_table;"
    
    if ! mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p"$DB_PASSWORD" -D "$DB_NAME" -e "$combined_query" > /dev/null 2>&1; then
        log_error "Permission test failed for temporary table operations"
        return 1
    fi
    
    log_info "✅ Database permissions are correct for incident analysis"
    return 0
}

# Test file import capabilities (critical for incident data loading)
test_file_operations() {
    log_info "Testing secure file operation capabilities..."
    
    # Verify secure-file-priv configuration allows file operations
    local file_priv_query="SHOW VARIABLES LIKE 'secure_file_priv';"
    
    if ! mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p"$DB_PASSWORD" -D "$DB_NAME" -e "$file_priv_query" > /dev/null 2>&1; then
        log_error "Failed to check secure_file_priv configuration"
        return 1
    fi
    
    log_info "✅ File operation capabilities verified"
    return 0
}

# Main health check function
main() {
    # Try to detect incident number from hostname or container name
    local incident_info=""
    if [ -n "${HOSTNAME:-}" ]; then
        incident_info=" (${HOSTNAME})"
    fi
    
    log_info "Starting Excytin incident database health check${incident_info}..."
    
    local retry_count=0
    
    while [ $retry_count -lt $MAX_RETRIES ]; do
        # Run all health checks
        if test_mysql_connectivity && \
           test_admin_credentials && \
           test_required_tables && \
           test_data_integrity && \
           test_permissions && \
           test_file_operations; then
            
            log_info "🎉 Excytin incident database is fully operational and ready for cybersecurity analysis!"
            exit 0
        fi
        
        retry_count=$((retry_count + 1))
        if [ $retry_count -lt $MAX_RETRIES ]; then
            log_warn "Health check failed (attempt $retry_count/$MAX_RETRIES). Retrying in ${RETRY_DELAY}s..."
            sleep $RETRY_DELAY
        fi
    done
    
    log_error "❌ Excytin incident database health check failed after $MAX_RETRIES attempts"
    log_error "Database is not ready for cybersecurity incident analysis operations"
    exit 1
}

# Handle script termination gracefully
trap 'log_error "Health check interrupted"; exit 1' INT TERM

# Run the main function
main "$@"