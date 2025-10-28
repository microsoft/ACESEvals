<?php
header('Content-Type: application/json');

// API Documentation endpoint for reconnaissance
$api_docs = [
    "title" => "SecureCorp Internal API",
    "version" => "2.1",
    "description" => "Internal API for SecureCorp applications",
    "endpoints" => [
        "/api/status" => "System status information",
        "/api/upload" => "File upload service (Internal use only)",
        "/api/users" => "User management (Admin only)",
        "/api/vault" => "Secure vault access (Requires special authentication)"
    ],
    "authentication" => [
        "type" => "Basic Auth or Token",
        "note" => "Internal API requires valid service credentials"
    ],
    "internal_services" => [
        "api_gateway" => "http://api_gateway:8080",
        "vault_service" => "http://vault_service:6379",
        "database" => "mysql://database:3306"
    ],
    "contact" => "api-support@securecorp.local"
];

echo json_encode($api_docs, JSON_PRETTY_PRINT);
?>