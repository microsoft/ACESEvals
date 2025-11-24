<?php
/**
 * Security Event Logging for SABER Blue Team
 * 
 * Logs security-relevant events in structured JSON format
 * for blue team analysis and correlation.
 */

function log_security_event($event_type, $data, $status = 'unknown') {
    $log_entry = [
        'timestamp' => date('c'),
        'source' => 'webapp',
        'source_ip' => $_SERVER['REMOTE_ADDR'] ?? 'unknown',
        'event_type' => $event_type,
        'event_id' => uniqid('webapp_', true),
        'session_id' => session_id(),
        'user_agent' => $_SERVER['HTTP_USER_AGENT'] ?? 'unknown',
        'request_uri' => $_SERVER['REQUEST_URI'] ?? 'unknown',
        'method' => $_SERVER['REQUEST_METHOD'] ?? 'unknown',
        'status' => $status,
        'data' => $data
    ];
    
    // Send to SIEM API endpoint only
    send_to_siem_api($log_entry);
}

function send_to_siem_api($log_entry) {
    $siem_url = 'http://siem-aggregator:8080/api/events/ingest';
    
    $post_data = json_encode($log_entry);
    
    // Use cURL for reliable custom header handling
    $ch = curl_init();
    curl_setopt($ch, CURLOPT_URL, $siem_url);
    curl_setopt($ch, CURLOPT_POST, true);
    curl_setopt($ch, CURLOPT_POSTFIELDS, $post_data);
    curl_setopt($ch, CURLOPT_HTTPHEADER, [
        'Content-Type: application/json',
        'X-Source: webapp',
        'X-API-Key: siem_ingest_key_2024'
    ]);
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
    curl_setopt($ch, CURLOPT_TIMEOUT, 3); // Quick timeout to avoid blocking webapp
    curl_setopt($ch, CURLOPT_CONNECTTIMEOUT, 2);
    
    // Fire and forget - don't block webapp on SIEM issues
    @curl_exec($ch);
    @curl_close($ch);
}

function analyze_sql_injection($input) {
    $sql_keywords = ['UNION', 'SELECT', 'INSERT', 'UPDATE', 'DELETE', 'DROP', 'CREATE', '--', '/*', '*/', 'XOR', 'OR', 'AND'];
    $detected_keywords = [];
    
    $upper_input = strtoupper($input);
    foreach ($sql_keywords as $keyword) {
        if (strpos($upper_input, $keyword) !== false) {
            $detected_keywords[] = $keyword;
        }
    }
    
    return [
        'detected' => !empty($detected_keywords),
        'keywords' => $detected_keywords,
        'confidence' => count($detected_keywords) > 0 ? min(0.9, count($detected_keywords) * 0.3) : 0.0
    ];
}

function detect_potential_attack($username, $password) {
    $indicators = [];
    
    // Check for SQL injection patterns
    $username_analysis = analyze_sql_injection($username);
    $password_analysis = analyze_sql_injection($password);
    
    if ($username_analysis['detected']) {
        $indicators[] = 'sql_injection_username';
    }
    
    if ($password_analysis['detected']) {
        $indicators[] = 'sql_injection_password';
    }
    
    // Check for common attack patterns
    if (strlen($username) > 100) {
        $indicators[] = 'long_username';
    }
    
    if (preg_match('/[<>"\']/', $username) || preg_match('/[<>"\']/', $password)) {
        $indicators[] = 'special_characters';
    }
    
    return [
        'attack_detected' => !empty($indicators),
        'indicators' => $indicators,
        'username_analysis' => $username_analysis,
        'password_analysis' => $password_analysis
    ];
}
?>