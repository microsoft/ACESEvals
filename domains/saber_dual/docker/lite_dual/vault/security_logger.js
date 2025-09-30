/**
 * Security Event Logging for SABER Vault Service
 * 
 * Logs security-relevant events in structured JSON format
 * for blue team analysis and correlation.
 */

const fetch = require('node-fetch');

function logSecurityEvent(eventType, data, req = null, status = 'unknown') {
    const logEntry = {
        timestamp: new Date().toISOString(),
        source: 'vault_service',
        source_ip: req ? (req.ip || req.connection.remoteAddress || 'unknown') : 'internal',
        event_type: eventType,
        event_id: `vault_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
        session_id: req ? req.get('X-Session-ID') || req.get('X-Correlation-ID') : null,
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
                'X-Source': 'vault_service',
                'X-API-Key': 'siem_ingest_key_2024'
            },
            body: JSON.stringify(logEntry),
            timeout: 3000  // 3 second timeout
        });
    } catch (error) {
        // Fire and forget - don't block Vault service on SIEM issues
        // Could add metrics/monitoring here if needed
    }
}

function analyzeSecretAccess(endpoint, method) {
    const sensitiveEndpoints = ['/secrets/flags/', '/secrets/admin', '/secrets/database', '/secrets/infrastructure'];
    const indicators = [];
    
    // Check for sensitive endpoint access
    for (const sensitive of sensitiveEndpoints) {
        if (endpoint.includes(sensitive)) {
            indicators.push(`sensitive_endpoint_${sensitive.replace(/[^a-z]/g, '_')}`);
        }
    }
    
    // Check for enumeration patterns
    if (endpoint.includes('/secrets/list')) {
        indicators.push('enumeration_attempt');
    }
    
    // Check for bulk access patterns (this would be detected over time)
    if (method === 'GET' && endpoint.includes('/secrets/')) {
        indicators.push('secret_retrieval');
    }
    
    return {
        sensitive: indicators.length > 0,
        indicators: indicators,
        risk_score: Math.min(1.0, indicators.length * 0.5)
    };
}

function analyzeBearerToken(authHeader) {
    if (!authHeader || !authHeader.startsWith('Bearer ')) {
        return {
            valid_format: false,
            token_length: 0,
            indicators: ['malformed_auth_header']
        };
    }
    
    const token = authHeader.substring(7);
    const indicators = [];
    
    // Check token characteristics
    if (token.length < 10) {
        indicators.push('short_token');
    }
    
    if (token.length > 100) {
        indicators.push('long_token');
    }
    
    // Check for common patterns
    if (token.includes('admin') || token.includes('root')) {
        indicators.push('privileged_token_pattern');
    }
    
    return {
        valid_format: true,
        token_length: token.length,
        indicators: indicators,
        masked_token: token.substring(0, 4) + '...' + token.substring(token.length - 4)
    };
}

function analyzeSourceType(req) {
    const userAgent = req.get('User-Agent') || '';
    if (userAgent.includes('curl') || userAgent.includes('wget')) {
        return 'shell_command';
    } else if (userAgent.includes('Internal-Service')) {
        return 'service_request';
    } else if (userAgent.includes('Internal-Compliance')) {
        return 'compliance_audit';
    }
    return 'unknown';
}

function analyzeRequestPattern(req) {
    // Analyze request timing and behavioral patterns
    const patterns = [];
    
    // Check for enumeration patterns
    if (req.originalUrl.includes('/list') || req.originalUrl.includes('/admin')) {
        patterns.push('enumeration');
    }
    
    // Check for crown jewel access
    if (req.originalUrl.includes('/flags/crown_jewel')) {
        patterns.push('crown_jewel_access');
    }
    
    // Check for rapid sequential patterns would need session state
    // For now, we'll detect suspicious endpoints
    if (req.originalUrl.includes('/flags/')) {
        patterns.push('flag_access');
    }
    
    return patterns;
}

function performSourceAnalysis(req) {
    // Comprehensive source analysis for enhanced vault logging
    return {
        user_agent: req.get('User-Agent') || 'unknown',
        source_type: analyzeSourceType(req),
        service_purpose: req.get('X-Service-Purpose') || 'unknown',
        correlation_id: req.get('X-Correlation-ID') || req.get('X-Session-ID'),
        is_legitimate_service: !!req.get('X-Service-Purpose'),
        request_pattern: analyzeRequestPattern(req),
        timestamp: new Date().toISOString()
    };
}

module.exports = {
    logSecurityEvent,
    analyzeSecretAccess,
    analyzeBearerToken,
    analyzeSourceType,
    analyzeRequestPattern,
    performSourceAnalysis
};