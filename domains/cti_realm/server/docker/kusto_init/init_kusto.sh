#!/bin/bash
# Kusto Database Initialization Script for CTI Realm

set -e

echo "Initializing Kusto database with CTI data..."

# Wait for Kusto emulator to be ready
echo "Waiting for Kusto emulator to start..."
for i in {1..60}; do
    if curl -s http://localhost:8080/v1/rest/mgmt > /dev/null; then
        echo "Kusto emulator is ready!"
        break
    fi
    if [ $i -eq 60 ]; then
        echo "Timeout waiting for Kusto emulator"
        exit 1
    fi
    sleep 5
done

# Create CTI database
echo "Creating CTI database..."
curl -X POST http://localhost:8080/v1/rest/mgmt \
    -H "Content-Type: application/json" \
    -d '{
        "csl": ".create database CTIRealm",
        "db": ""
    }'

# Function to create table and ingest data
create_and_populate_table() {
    local table_name=$1
    local file_path=$2

    echo "Processing table: $table_name"

    # Read first line to determine schema
    first_line=$(head -n 1 "$file_path")

    # Create table based on JSON structure (simplified approach)
    echo "Creating table $table_name..."
    curl -X POST http://localhost:8080/v1/rest/mgmt \
        -H "Content-Type: application/json" \
        -d "{
            \"csl\": \".create table $table_name (TimeGenerated: datetime, EventData: dynamic)\",
            \"db\": \"CTIRealm\"
        }"

    # Ingest data (simplified - in production, use proper Kusto ingestion)
    echo "Ingesting data into $table_name..."
    while IFS= read -r line; do
        if [ ! -z "$line" ]; then
            # Convert JSONL to Kusto ingest format
            timestamp=$(date -u +"%Y-%m-%dT%H:%M:%S.%3NZ")
            curl -X POST http://localhost:8080/v1/rest/ingest \
                -H "Content-Type: application/json" \
                -d "{
                    \"db\": \"CTIRealm\",
                    \"table\": \"$table_name\",
                    \"format\": \"json\",
                    \"data\": [{\"TimeGenerated\": \"$timestamp\", \"EventData\": $line}]
                }" || true  # Continue on error
        fi
    done < "$file_path"
}

# Process all data files
echo "Processing CTI data files..."

# Map file names to table names
declare -A file_table_map=(
    ["aadserviceprincipalsigninlogs.jsonl"]="AADServicePrincipalSignInLogs"
    ["aksaudit.jsonl"]="AKSAudit"
    ["aksauditadmin.jsonl"]="AKSAuditAdmin"
    ["auditlogs.jsonl"]="AuditLogs"
    ["azureactivity.jsonl"]="AzureActivity"
    ["azurediagnostics.jsonl"]="AzureDiagnostics"
    ["devicefilevents.jsonl"]="DeviceFileEvents"
    ["deviceprocessevents.jsonl"]="DeviceProcessEvents"
    ["microsoftgraphactivitylogs.jsonl"]="MicrosoftGraphActivityLogs"
    ["officeactivity.jsonl"]="OfficeActivity"
    ["signinlogs.jsonl"]="SigninLogs"
    ["storageboblogs.jsonl"]="StorageBlobLogs"
)

# Process each file
for file in /opt/kusto_data/*.jsonl; do
    if [ -f "$file" ]; then
        filename=$(basename "$file")
        table_name=${file_table_map[$filename]}

        if [ ! -z "$table_name" ]; then
            create_and_populate_table "$table_name" "$file"
        else
            echo "Warning: No table mapping found for $filename"
        fi
    fi
done

echo "CTI Realm Kusto database initialization completed!"

# Keep the script running to maintain the container
tail -f /dev/null
