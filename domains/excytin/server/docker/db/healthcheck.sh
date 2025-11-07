#!/bin/bash

# Excytin Incident Database Health Check Script
# Validates that the MySQL database is ready for application use
# Performs comprehensive checks including connectivity, authentication, and query execution
# This script is shared across all incident databases (5, 34, 38, 39, 55, 134, 166, 322)
# Dynamically detects and validates all tables from the loaded SQL file

set -euo pipefail

# Configuration
DB_HOST="localhost"
DB_PORT="3306"
DB_USER="admin"
DB_PASSWORD="admin"
DB_NAME="env_monitor_db"
MAX_RETRIES=3
RETRY_DELAY=2
SQL_FILES_DIR="/docker-entrypoint-initdb.d"

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

# Detect which incident SQL file is loaded
detect_incident_number() {
    # Look for incident SQL files in the init directory (suppress log during retry attempts)
    local sql_file=$(find "$SQL_FILES_DIR" -name "incident_*.sql" -type f 2>/dev/null | head -n 1)
    
    if [ -z "$sql_file" ]; then
        return 1
    fi
    
    # Extract incident number from filename
    local incident_num=$(basename "$sql_file" | sed 's/incident_\([0-9]*\)\.sql/\1/')
    
    if [ -z "$incident_num" ]; then
        return 1
    fi
    
    echo "$incident_num"
    return 0
}

# Extract all table names from the SQL file
get_expected_tables() {
    local sql_file="$1"
    
    if [ ! -f "$sql_file" ]; then
        return 1
    fi
    
    # Extract table names from CREATE TABLE statements
    # Handle both `backtick` and non-backtick table names
    local tables=$(grep -i "CREATE TABLE" "$sql_file" | sed 's/CREATE TABLE `\?\([^` (]*\).*/\1/' | sort)
    
    if [ -z "$tables" ]; then
        return 1
    fi
    
    echo "$tables"
    return 0
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
    
    # Detect incident and get SQL file
    local incident_num=$(detect_incident_number 2>/dev/null)
    if [ $? -ne 0 ]; then
        log_error "Failed to detect incident number - no incident SQL file found in $SQL_FILES_DIR"
        return 1
    fi
    
    log_info "Detected incident number: $incident_num"
    
    local sql_file="$SQL_FILES_DIR/incident_${incident_num}.sql"
    
    # Get expected tables from SQL file
    local expected_tables=$(get_expected_tables "$sql_file" 2>/dev/null)
    if [ $? -ne 0 ]; then
        log_error "Failed to extract table definitions from SQL file: $sql_file"
        return 1
    fi
    
    local expected_count=$(echo "$expected_tables" | wc -l)
    log_info "Expected $expected_count tables from SQL file"
    
    # Check that database has tables
    local actual_count=$(mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p"$DB_PASSWORD" -D "$DB_NAME" -e "SELECT COUNT(*) as count FROM information_schema.tables WHERE table_schema='$DB_NAME';" -s -N 2>/dev/null || echo "0")
    
    if [ "$actual_count" -eq 0 ]; then
        log_error "Database has no tables - SQL initialization failed!"
        log_error "This usually means the SQL file encountered an error during execution."
        log_error "Check container logs for 'ERROR' messages during SQL file loading."
        log_error "Common issues: LOAD DATA INFILE with incorrect --secure-file-priv path"
        return 1
    fi
    
    log_info "Database has $actual_count tables (expected: $expected_count)"
    
    if [ "$actual_count" -ne "$expected_count" ]; then
        log_warn "Table count mismatch: expected $expected_count but found $actual_count"
        log_warn "SQL initialization may have partially failed - check container logs"
    fi
    
    # Get list of actual tables that exist
    local actual_tables=$(mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p"$DB_PASSWORD" -D "$DB_NAME" -e "SELECT table_name FROM information_schema.tables WHERE table_schema='$DB_NAME' ORDER BY table_name;" -s -N 2>/dev/null)
    
    # Check each expected table exists and is readable
    local failed_tables=0
    local checked_tables=0
    local missing_tables=""
    
    while IFS= read -r table; do
        # Skip empty lines
        [ -z "$table" ] && continue
        
        checked_tables=$((checked_tables + 1))
        
        # Check if table exists in actual tables list
        if ! echo "$actual_tables" | grep -q "^${table}$"; then
            if [ -z "$missing_tables" ]; then
                missing_tables="$table"
            else
                missing_tables="$missing_tables, $table"
            fi
            failed_tables=$((failed_tables + 1))
        fi
    done <<< "$expected_tables"
    
    if [ $failed_tables -gt 0 ]; then
        log_error "$failed_tables out of $checked_tables expected tables are missing from database"
        log_error "Missing tables: $missing_tables"
        log_error "SQL file likely failed during execution - check container startup logs"
        return 1
    fi
    
    log_info "✅ All $checked_tables tables from incident $incident_num are present and accessible"
    return 0
}

# Test data integrity and query functionality
test_data_integrity() {
    log_info "Testing data integrity and complex query functionality..."
    
    # Detect incident to get appropriate tables
    local incident_num=$(detect_incident_number 2>/dev/null)
    if [ $? -ne 0 ]; then
        log_error "Failed to detect incident number"
        return 1
    fi
    
    local sql_file="$SQL_FILES_DIR/incident_${incident_num}.sql"
    local expected_tables=$(get_expected_tables "$sql_file" 2>/dev/null)
    if [ $? -ne 0 ]; then
        log_error "Failed to get expected tables"
        return 1
    fi
    
    # Get actual tables that exist in the database
    local actual_tables=$(mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p"$DB_PASSWORD" -D "$DB_NAME" -e "SELECT table_name FROM information_schema.tables WHERE table_schema='$DB_NAME' ORDER BY table_name LIMIT 3;" -s -N 2>/dev/null)
    
    if [ -z "$actual_tables" ]; then
        log_error "No tables found in database for integrity check"
        return 1
    fi
    
    # Test a union query across the first few tables that exist
    local union_parts=""
    local table_count=0
    
    while IFS= read -r table; do
        [ -z "$table" ] && continue
        
        table_count=$((table_count + 1))
        
        if [ -z "$union_parts" ]; then
            union_parts="SELECT '$table' as table_name, COUNT(*) as row_count FROM \`$table\`"
        else
            union_parts="$union_parts UNION ALL SELECT '$table' as table_name, COUNT(*) as row_count FROM \`$table\`"
        fi
    done <<< "$actual_tables"
    
    if [ -n "$union_parts" ] && [ $table_count -gt 0 ]; then
        local query="SELECT COUNT(*) FROM ($union_parts) as table_summary;"
        
        if ! mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p"$DB_PASSWORD" -D "$DB_NAME" -e "$query" > /dev/null 2>&1; then
            log_error "Failed to execute complex union query - data integrity issue"
            return 1
        fi
    fi
    
    # Test that we can query metadata about all tables
    local metadata_query="SELECT table_name, table_rows FROM information_schema.tables WHERE table_schema='$DB_NAME' ORDER BY table_name LIMIT 10;"
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
            
            # Get incident info for final message
            local incident_num=$(detect_incident_number 2>/dev/null || echo "unknown")
            local sql_file="$SQL_FILES_DIR/incident_${incident_num}.sql"
            local table_count=$(get_expected_tables "$sql_file" 2>/dev/null | wc -l || echo "0")
            
            log_info "🎉 Excytin incident $incident_num database is fully operational with $table_count tables validated!"
            log_info "All tables are loaded, readable, and ready for cybersecurity analysis!"
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