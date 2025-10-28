#!/bin/bash

# SABER Webapp Entrypoint
# Ensures proper permissions for security logging

echo "🔧 Setting up SABER security logging..."

# Create log directory and fix permissions
mkdir -p /var/log/saber
chown -R www-data:www-data /var/log/saber
chmod -R 755 /var/log/saber

# Also ensure backup log locations are available
mkdir -p /tmp
chmod 777 /tmp

echo "✅ Security logging setup complete"

# Start Apache
echo "🚀 Starting Apache..."
exec apache2-foreground