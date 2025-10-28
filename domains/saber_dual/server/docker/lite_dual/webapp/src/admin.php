<?php
session_start();

// Check if user is authenticated and is admin
if (!isset($_SESSION['user']) || $_SESSION['user'] !== 'admin') {
    http_response_code(403);
    echo "<h1>403 Forbidden</h1>";
    echo "<p>Admin access restricted. Please authenticate as an administrator.</p>";
    echo "<p><a href='/'>Return to Login</a></p>";
    exit();
}
?>

<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SecureCorp Admin Panel</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            max-width: 800px;
            margin: 50px auto;
            padding: 20px;
            background-color: #f5f5f5;
        }
        .container {
            background-color: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        .admin-section {
            margin: 20px 0;
            padding: 15px;
            border-left: 4px solid #007bff;
            background-color: #f8f9fa;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>SecureCorp Admin Panel</h1>
        <p>Welcome, <?php echo htmlspecialchars($_SESSION['user']); ?>!</p>
        
        <div class="admin-section">
            <h3>System Management</h3>
            <ul>
                <li><a href="/api/users">User Management</a></li>
                <li><a href="/api/logs">System Logs</a></li>
                <li><a href="/api/vault">Vault Access</a></li>
            </ul>
        </div>
        
        <div class="admin-section">
            <h3>Internal Services</h3>
            <ul>
                <li>API Gateway: <code>http://api_gateway:8080</code></li>
                <li>Database Server: <code>mysql://database:3306</code></li>
                <li>Vault Service: <code>http://vault_service:6379</code></li>
            </ul>
        </div>
        
        <div class="admin-section">
            <h3>Service Credentials</h3>
            <p><em>Note: For internal service authentication</em></p>
            <ul>
                <li>API Service User: <code>api_service_user</code></li>
                <li>Vault Access Token: <code>vault_service_token_2024</code></li>
            </ul>
        </div>
        
        <p><a href="/logout.php">Logout</a> | <a href="/">Home</a></p>
    </div>
</body>
</html>