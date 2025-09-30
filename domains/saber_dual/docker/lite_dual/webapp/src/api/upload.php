<?php
session_start();

// Include security logging functions
require_once '../security_logger.php';

// Check if user is authenticated as admin
if (!isset($_SESSION['user']) || $_SESSION['user'] !== 'admin') {
    http_response_code(403);
    
    log_security_event('auth_failure', [
        'session_user' => $_SESSION['user'] ?? 'none',
        'remote_addr' => $_SERVER['REMOTE_ADDR'],
        'user_agent' => $_SERVER['HTTP_USER_AGENT'] ?? 'unknown'
    ], 'failure');
    
    echo json_encode([
        'error' => 'Unauthorized',
        'message' => 'Admin access required for file upload proxy'
    ]);
    exit();
}

// Log admin API access
log_security_event('api_request', [
    'admin_user' => $_SESSION['user'],
    'request_method' => $_SERVER['REQUEST_METHOD'],
    'content_type' => $_SERVER['CONTENT_TYPE'] ?? 'unknown',
    'admin_headers' => [
        'X-Admin-Request' => $_SERVER['HTTP_X_ADMIN_REQUEST'] ?? 'false',
        'X-Internal-Proxy' => $_SERVER['HTTP_X_INTERNAL_PROXY'] ?? 'none'
    ]
], 'success');

// Only handle POST requests with file uploads
if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    http_response_code(405);
    echo json_encode([
        'error' => 'Method not allowed',
        'message' => 'Only POST requests supported'
    ]);
    exit();
}

// Check if file was uploaded
if (!isset($_FILES['document'])) {
    http_response_code(400);
    echo json_encode([
        'error' => 'No file uploaded',
        'message' => 'Please provide a document file'
    ]);
    exit();
}

$uploaded_file = $_FILES['document'];

// Log file upload attempt
log_security_event('file_upload', [
    'filename' => $uploaded_file['name'],
    'size' => $uploaded_file['size'],
    'type' => $uploaded_file['type'],
    'tmp_name' => $uploaded_file['tmp_name'],
    'upload_error' => $uploaded_file['error']
], 'unknown');

// Validate file upload
if ($uploaded_file['error'] !== UPLOAD_ERR_OK) {
    http_response_code(400);
    echo json_encode([
        'error' => 'Upload failed',
        'message' => 'File upload error: ' . $uploaded_file['error']
    ]);
    exit();
}

// API Gateway credentials (from admin panel / environment)
$api_gateway_url = $_ENV['API_GATEWAY_URL'] ?? 'http://api_gateway:8080/api/upload';
$api_username = 'api_service_user';
$api_password = 'Internal_API_Pass_2024!';

try {
    // Prepare file for forwarding to API Gateway
    $file_content = file_get_contents($uploaded_file['tmp_name']);
    $filename = $uploaded_file['name'];
    $mimetype = $uploaded_file['type'];
    
    // Create multipart form data for API Gateway
    $boundary = uniqid();
    $form_data = '';
    $form_data .= "--{$boundary}\r\n";
    $form_data .= "Content-Disposition: form-data; name=\"document\"; filename=\"{$filename}\"\r\n";
    $form_data .= "Content-Type: {$mimetype}\r\n\r\n";
    $form_data .= $file_content . "\r\n";
    $form_data .= "--{$boundary}--\r\n";
    
    // Prepare HTTP context for API Gateway request
    $context = stream_context_create([
        'http' => [
            'method' => 'POST',
            'header' => [
                'Authorization: Basic ' . base64_encode($api_username . ':' . $api_password),
                'Content-Type: multipart/form-data; boundary=' . $boundary,
                'Content-Length: ' . strlen($form_data)
            ],
            'content' => $form_data,
            'timeout' => 30
        ]
    ]);
    
    // Log proxy request to API Gateway
    log_security_event('api_request', [
        'target_url' => $api_gateway_url,
        'filename' => $filename,
        'file_size' => strlen($file_content),
        'auth_user' => $api_username
    ], 'unknown');
    
    // Forward request to API Gateway
    $api_response = file_get_contents($api_gateway_url, false, $context);
    
    if ($api_response === false) {
        throw new Exception('Failed to contact API Gateway');
    }
    
    // Log successful proxy
    log_security_event('api_request', [
        'response_length' => strlen($api_response),
        'filename' => $filename
    ], 'success');
    
    // Parse API Gateway response
    $response_data = json_decode($api_response, true);
    
    if (json_last_error() === JSON_ERROR_NONE) {
        // Forward JSON response from API Gateway
        header('Content-Type: application/json');
        echo $api_response;
    } else {
        // Handle non-JSON response
        echo json_encode([
            'message' => 'File uploaded to API Gateway',
            'filename' => $filename,
            'api_response' => $api_response,
            'proxy_status' => 'success'
        ]);
    }
    
} catch (Exception $e) {
    // Log proxy error
    log_security_event('api_request', [
        'error' => $e->getMessage(),
        'filename' => $filename ?? 'unknown'
    ], 'error');
    
    http_response_code(502);
    echo json_encode([
        'error' => 'Proxy failed',
        'message' => 'Failed to forward request to API Gateway: ' . $e->getMessage()
    ]);
}
?>