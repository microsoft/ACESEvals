#!/bin/bash

# Comprehensive Database Health Check Script
# This script validates that the database is not only running but fully ready for application use
# It tests the same functionality that the Python unit tests require

set -euo pipefail

# Configuration
DB_HOST="localhost"
DB_PORT="3306"
DB_USER="webapp_user"
DB_PASSWORD="webapp_pass_2024"
DB_NAME="webapp_db"
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

# Function to test MySQL basic connectivity
test_mysql_connectivity() {
    log_info "Testing MySQL basic connectivity..."
    
    if ! mysqladmin ping -h "$DB_HOST" -P "$DB_PORT" --silent; then
        log_error "MySQL server is not responding to ping"
        return 1
    fi
    
    log_info "✅ MySQL server is responding"
    return 0
}

# Function to test webapp user credentials and database access
test_webapp_credentials() {
    log_info "Testing webapp user credentials and database access..."
    
    # Test connection with webapp_user credentials
    if ! mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p"$DB_PASSWORD" -D "$DB_NAME" -e "SELECT 1;" > /dev/null 2>&1; then
        log_error "Failed to connect with webapp_user credentials or execute query"
        return 1
    fi
    
    log_info "✅ Webapp user credentials are working"
    return 0
}

# Function to verify required tables exist and are accessible
test_required_tables() {
    log_info "Testing required table accessibility..."
    
    local tables=("users" "api_credentials" "internal_services" "flags" "audit_log")
    
    for table in "${tables[@]}"; do
        if ! mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p"$DB_PASSWORD" -D "$DB_NAME" -e "SELECT COUNT(*) FROM $table;" > /dev/null 2>&1; then
            log_error "Table '$table' is not accessible or does not exist"
            return 1
        fi
    done
    
    log_info "✅ All required tables are accessible"
    return 0
}

# Function to test data integrity with a comprehensive query
test_data_integrity() {
    log_info "Testing data integrity and query functionality..."
    
    # Test a more complex query that mirrors what the application would do
    # Use proper table aliases to avoid reserved keyword issues
    local query="SELECT u.username, ac.service_name, sv.service_name FROM users u, api_credentials ac, internal_services sv LIMIT 1;"
    
    if ! mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p"$DB_PASSWORD" -D "$DB_NAME" -e "$query" > /dev/null 2>&1; then
        log_error "Failed to execute complex query - data integrity issue"
        return 1
    fi
    
    log_info "✅ Data integrity check passed"
    return 0
}

# Function to test permissions are correctly set
test_permissions() {
    log_info "Testing user permissions..."
    
    # Test that webapp_user can perform expected operations
    local test_queries=(
        "SELECT * FROM users LIMIT 1;"
        "SELECT * FROM api_credentials LIMIT 1;"
        "INSERT INTO audit_log (ip_address, user_agent, request_method, request_uri) VALUES ('127.0.0.1', 'healthcheck', 'GET', '/health');"
        "DELETE FROM audit_log WHERE user_agent = 'healthcheck';"
    )
    
    for query in "${test_queries[@]}"; do
        if ! mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p"$DB_PASSWORD" -D "$DB_NAME" -e "$query" > /dev/null 2>&1; then
            log_error "Permission test failed for query: $query"
            return 1
        fi
    done
    
    log_info "✅ User permissions are correct"
    return 0
}

# Main health check function
main() {
    log_info "Starting comprehensive database health check..."
    
    local retry_count=0
    
    while [ $retry_count -lt $MAX_RETRIES ]; do
        # Run all health checks
        if test_mysql_connectivity && \
           test_webapp_credentials && \
           test_required_tables && \
           test_data_integrity && \
           test_permissions; then
            
            log_info "🎉 Database is fully healthy and ready for application use!"
            exit 0
        fi
        
        retry_count=$((retry_count + 1))
        if [ $retry_count -lt $MAX_RETRIES ]; then
            log_warn "Health check failed (attempt $retry_count/$MAX_RETRIES). Retrying in ${RETRY_DELAY}s..."
            sleep $RETRY_DELAY
        fi
    done
    
    log_error "❌ Database health check failed after $MAX_RETRIES attempts"
    log_error "Database is not ready for application use"
    exit 1
}

# Handle script termination gracefully
trap 'log_error "Health check interrupted"; exit 1' INT TERM

# Run the main function
main "$@"