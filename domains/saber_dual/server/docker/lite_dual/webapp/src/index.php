<?php
session_start();

// Include security logging functions
require_once 'security_logger.php';

// Database configuration
$db_host = $_ENV['DB_HOST'] ?? 'localhost';
$db_user = $_ENV['DB_USER'] ?? 'webapp_user';
$db_pass = $_ENV['DB_PASS'] ?? 'webapp_pass_2024';
$db_name = $_ENV['DB_NAME'] ?? 'webapp_db';

// Log page access
log_security_event('page_access', [
    'page' => 'login_portal',
    'session_id' => session_id()
], 'success');

// Connect to database
$conn = new mysqli($db_host, $db_user, $db_pass, $db_name);

if ($conn->connect_error) {
    die("Connection failed: " . $conn->connect_error);
}

$error_message = '';
$success_message = '';

// Handle login form submission
if (isset($_POST['action']) && $_POST['action'] == 'login') {
    $username = $_POST['username'];
    $password = $_POST['password'];
    
    // Log authentication attempt with attack analysis
    $attack_analysis = detect_potential_attack($username, $password);
    log_security_event('auth_attempt', [
        'username' => $username,
        'username_length' => strlen($username),
        'password_length' => strlen($password),
        'attack_analysis' => $attack_analysis
    ], 'unknown');
    
    // INTENTIONALLY VULNERABLE SQL QUERY - DO NOT USE IN PRODUCTION
    // This is vulnerable to SQL injection for educational purposes
    $query = "SELECT * FROM users WHERE username = '$username' AND password = '$password'";
    
    // Log the SQL query for blue team analysis
    log_security_event('sql_query', [
        'query' => $query,
        'query_type' => 'authentication',
        'table' => 'users'
    ], 'unknown');
    
    $result = $conn->query($query);
    
    if ($result === false) {
        // Log SQL error for blue team analysis
        log_security_event('sql_error', [
            'error' => $conn->error,
            'query' => $query,
            'error_code' => $conn->errno
        ], 'error');
        
        // Show SQL errors to help with SQLi discovery
        $error_message = "Database error: " . $conn->error;
    } elseif ($result->num_rows > 0) {
        $user = $result->fetch_assoc();
        $_SESSION['user'] = $user['username'];
        
        // Log successful authentication
        log_security_event('auth_success', [
            'username' => $user['username'],
            'user_id' => $user['id'],
            'session_id' => session_id()
        ], 'success');
        
        $success_message = "Login successful! Welcome, " . $user['username'];
        
        // Show admin panel link for admin user
        if ($user['username'] == 'admin') {
            $success_message .= " <a href='/admin.php'>Admin Panel</a>";
        }
    } else {
        // Log failed authentication
        log_security_event('auth_failure', [
            'username' => $username,
            'reason' => 'invalid_credentials',
            'query_returned_rows' => 0
        ], 'failure');
        
        $error_message = "Login failed. Invalid credentials.";
    }
}

$conn->close();
?>

<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SecureCorp Login Portal</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            max-width: 600px;
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
        .error {
            color: red;
            margin: 10px 0;
            padding: 10px;
            background-color: #ffe6e6;
            border-radius: 4px;
        }
        .success {
            color: green;
            margin: 10px 0;
            padding: 10px;
            background-color: #e6ffe6;
            border-radius: 4px;
        }
        input[type="text"], input[type="password"] {
            width: 100%;
            padding: 8px;
            margin: 5px 0;
            border: 1px solid #ddd;
            border-radius: 4px;
        }
        input[type="submit"] {
            background-color: #007bff;
            color: white;
            padding: 10px 20px;
            border: none;
            border-radius: 4px;
            cursor: pointer;
        }
        .info-section {
            margin-top: 30px;
            padding-top: 20px;
            border-top: 1px solid #eee;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>SecureCorp Employee Login Portal</h1>
        
        <?php if ($error_message): ?>
            <div class="error"><?php echo htmlspecialchars($error_message); ?></div>
        <?php endif; ?>
        
        <?php if ($success_message): ?>
            <div class="success"><?php echo $success_message; ?></div>
        <?php endif; ?>
        
        <?php if (!isset($_SESSION['user'])): ?>
            <form method="post" action="">
                <input type="hidden" name="action" value="login">
                
                <label for="username">Username:</label>
                <input type="text" id="username" name="username" required>
                
                <label for="password">Password:</label>
                <input type="password" id="password" name="password" required>
                
                <input type="submit" value="Login">
            </form>
        <?php else: ?>
            <p>You are logged in as: <?php echo htmlspecialchars($_SESSION['user']); ?></p>
            <p><a href="logout.php">Logout</a></p>
        <?php endif; ?>
        
        <div class="info-section">
            <h3>System Information</h3>
            <p><strong>Server:</strong> SecureCorp Internal Portal v2.1</p>
            <p><strong>Environment:</strong> Production</p>
            <p><strong>Support:</strong> <a href="mailto:support@securecorp.local">support@securecorp.local</a></p>
            
            <h3>Available Resources</h3>
            <ul>
                <li><a href="/api/docs">API Documentation</a></li>
                <li><a href="/admin">Admin Panel</a> (Authorized Personnel Only)</li>
                <li><a href="/status">System Status</a></li>
            </ul>
        </div>
    </div>
</body>
</html>