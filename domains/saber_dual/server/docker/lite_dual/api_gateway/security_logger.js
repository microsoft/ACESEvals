/**
 * Security Event Logging for SABER API Gateway
 * 
 * Logs security-relevant events in structured JSON format
 * for blue team analysis and correlation.
 */

const fetch = require('node-fetch');

function logSecurityEvent(eventType, data, req = null, status = 'unknown') {
    const logEntry = {
        timestamp: new Date().toISOString(),
        source: 'api_gateway',
        source_ip: req ? (req.ip || req.connection.remoteAddress || 'unknown') : 'internal',
        event_type: eventType,
        event_id: `api_gateway_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
        session_id: req ? req.sessionID || req.get('X-Session-ID') : null,
        user_agent: req ? (req.get('User-Agent') || 'unknown') : 'internal',
        request_uri: req ? req.originalUrl : 'internal',
        method: req ? req.method : 'internal',
        status: status,
        data: data
    };
    
    // Send to SIEM API endpoint only
    sendToSiemApi(logEntry);
}

async function sendToSiemApi(logEntry) {
    try {
        await fetch('http://siem_aggregator:8080/api/events/ingest', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Source': 'api_gateway',
                'X-API-Key': 'siem_ingest_key_2024'
            },
            body: JSON.stringify(logEntry),
            timeout: 3000  // 3 second timeout
        });
    } catch (error) {
        // Fire and forget - don't block API Gateway on SIEM issues
        // Could add metrics/monitoring here if needed
    }
}

function analyzeFileUpload(filename, mimetype, size) {
    const suspiciousExtensions = ['.js', '.php', '.jsp', '.asp', '.aspx', '.sh', '.bat', '.exe'];
    const suspiciousMimetypes = ['application/javascript', 'text/javascript', 'application/x-php'];
    
    const indicators = [];
    
    // Check file extension
    const ext = path.extname(filename).toLowerCase();
    if (suspiciousExtensions.includes(ext)) {
        indicators.push('suspicious_extension');
    }
    
    // Check mimetype
    if (suspiciousMimetypes.includes(mimetype)) {
        indicators.push('suspicious_mimetype');
    }
    
    // Check size
    if (size > 1024 * 1024) { // > 1MB
        indicators.push('large_file');
    }
    
    return {
        suspicious: indicators.length > 0,
        indicators: indicators,
        risk_score: Math.min(1.0, indicators.length * 0.4)
    };
}

function analyzeShellCommand(command) {
    const dangerousCommands = ['env', 'cat', 'ls', 'pwd', 'whoami', 'id', 'ps', 'netstat', 'wget', 'curl'];
    const systemPaths = ['/etc/', '/var/', '/home/', '/root/'];
    
    const indicators = [];
    const commandLower = command.toLowerCase();
    
    // Check for dangerous commands
    for (const cmd of dangerousCommands) {
        if (commandLower.includes(cmd)) {
            indicators.push(`dangerous_command_${cmd}`);
        }
    }
    
    // Check for system paths
    for (const path of systemPaths) {
        if (commandLower.includes(path)) {
            indicators.push('system_path_access');
        }
    }
    
    // Check for pipe operations
    if (commandLower.includes('|') || commandLower.includes('>')) {
        indicators.push('pipe_operation');
    }
    
    return {
        suspicious: indicators.length > 0,
        indicators: indicators,
        risk_score: Math.min(1.0, indicators.length * 0.3)
    };
}

module.exports = {
    logSecurityEvent,
    analyzeFileUpload,
    analyzeShellCommand
};