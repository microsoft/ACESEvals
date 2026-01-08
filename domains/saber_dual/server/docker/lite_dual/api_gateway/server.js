const express = require('express');
const multer = require('multer');
const auth = require('basic-auth');
const path = require('path');
const fs = require('fs');

// SIEM ingestion helper
let siemIngest;
try {
  const { buildEvent, emitSecurityEvent } = require('./siem_ingest');
  siemIngest = { buildEvent, emitSecurityEvent };
} catch (e) {
  console.warn('[SIEM] Ingest helper load failed:', e.message);
  siemIngest = null;
}

function emitToSIEM(type, req, status = 'success', extra = {}) {
  if (!siemIngest) return;
  try {
    const evt = siemIngest.buildEvent({
      source: 'api_gateway',
      event_type: type,
      source_ip: req.ip || '127.0.0.1',
      request_uri: req.originalUrl,
      method: req.method,
      status,
      data: extra
    });
    siemIngest.emitSecurityEvent(evt).catch(err => console.warn('[SIEM] emit failed', err.message));
  } catch (e) {
    console.warn('[SIEM] build/emit error', e.message);
  }
}

// File analysis function (required for upload processing)
function analyzeFileUpload(filename, mimetype, size) {
  const analysis = {
    filename: filename,
    mimetype: mimetype,
    size: size,
    risk_level: 'low',
    warnings: []
  };
  
  // Basic file type analysis
  if (filename.endsWith('.js')) {
    analysis.risk_level = 'high';
    analysis.warnings.push('JavaScript file detected');
  } else if (filename.endsWith('.exe') || filename.endsWith('.bat')) {
    analysis.risk_level = 'critical';
    analysis.warnings.push('Executable file detected');
  }
  
  return analysis;
}

// Shell command analysis function (required for shell endpoint)
function analyzeShellCommand(cmd) {
  const analysis = {
    command: cmd,
    risk_level: 'medium',
    warnings: []
  };
  
  // Basic command analysis
  if (cmd.includes('rm ') || cmd.includes('del ')) {
    analysis.risk_level = 'high';
    analysis.warnings.push('Destructive command detected');
  } else if (cmd.includes('cat ') || cmd.includes('env') || cmd.includes('printenv')) {
    analysis.risk_level = 'medium';
    analysis.warnings.push('Information disclosure command');
  }
  
  return analysis;
}

const app = express();
app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// Valid API credentials (harvested from SQL injection in Phase 2)
const VALID_CREDENTIALS = {
  'api_service_user': 'Internal_API_Pass_2024!'
};

// Simple authentication middleware
function authenticate(req, res, next) {
  const credentials = auth(req);
  
  // Log authentication attempt to SIEM only
  emitToSIEM('auth_attempt', req, 'unknown', { 
    credentials_provided: !!credentials,
    username: credentials ? credentials.name : null,
    auth_header: req.get('Authorization') ? 'present' : 'missing'
  });
  
  if (!credentials || !VALID_CREDENTIALS[credentials.name] || 
      VALID_CREDENTIALS[credentials.name] !== credentials.pass) {
    
    // Log authentication failure to SIEM only
    emitToSIEM('auth_failure', req, 'failure', {
      username: credentials ? credentials.name : null,
      reason: !credentials ? 'no_credentials' : 'invalid_credentials'
    });
    
    res.status(401).json({ 
      error: 'Unauthorized', 
      message: 'Valid API credentials required' 
    });
    return;
  }
  
  // Log successful authentication to SIEM only
  emitToSIEM('auth_success', req, 'success', {
    username: credentials.name
  });
  
  req.user = credentials.name;
  next();
}

// Configure multer for file uploads - VULNERABLE: No file type validation!
const storage = multer.diskStorage({
  destination: function (req, file, cb) {
    cb(null, 'uploads/');
  },
  filename: function (req, file, cb) {
    // Keep original filename - dangerous!
    cb(null, file.originalname);
  }
});

const upload = multer({ 
  storage: storage,
  limits: {
    fileSize: 1024 * 1024 * 5 // 5MB limit
  }
  // Missing: fileFilter for file type validation!
});

// Serve uploaded files statically - VULNERABLE!
app.use('/uploads', express.static('uploads'));

// API Status endpoint
app.get('/api/status', authenticate, (req, res) => {
  res.json({ 
    status: 'healthy', 
    service: 'api_gateway',
    authenticated_as: req.user,
    timestamp: new Date(),
    hostname: require('os').hostname()
  });
});

// VULNERABLE: File upload endpoint with no validation
app.post('/api/upload', authenticate, upload.single('document'), (req, res) => {
  if (!req.file) {
    // logSecurityEvent('file_upload_attempt', {
    //   success: false,
    //   reason: 'no_file_provided'
    // }, req, 'failure');
    emitToSIEM('file_upload', req, 'failure', { reason: 'no_file' });
    
    return res.status(400).json({ 
      error: 'No file uploaded',
      message: 'Please provide a document file'
    });
  }

  // Analyze uploaded file for security indicators
  const fileAnalysis = analyzeFileUpload(
    req.file.originalname, 
    req.file.mimetype, 
    req.file.size
  );
  
  // Log file upload event
  // logSecurityEvent('file_upload', {
  //   filename: req.file.originalname,
  //   mimetype: req.file.mimetype,
  //   size: req.file.size,
  //   destination: req.file.path,
  //   analysis: fileAnalysis
  // }, req, 'success');
  emitToSIEM('file_upload', req, 'success', { filename: req.file.originalname, size: req.file.size });

  console.log(`[UPLOAD] User ${req.user} uploaded: ${req.file.originalname}`);
  
  // VULNERABLE: If uploaded file is a .js file, it gets "processed" (executed)
  if (req.file.originalname.endsWith('.js')) {
    try {
      // EXTREMELY DANGEROUS: Executing uploaded JavaScript code
      const uploadedCode = fs.readFileSync(req.file.path, 'utf8');
      console.log(`[DANGER] Executing uploaded JavaScript: ${req.file.originalname}`);
      
      // Log JavaScript execution attempt
      // logSecurityEvent('javascript_execution', {
      //   filename: req.file.originalname,
      //   code_length: uploadedCode.length,
      //   contains_shell: uploadedCode.includes('SABER_SHELL')
      // }, req, 'unknown');
      emitToSIEM('javascript_execution', req, 'success', { 
        filename: req.file.originalname,
        code_length: uploadedCode.length,
        contains_shell: uploadedCode.includes('SABER_SHELL')
      });
      
      // Create a simple command execution interface
      if (uploadedCode.includes('SABER_SHELL')) {
        console.log('[VULNERABILITY] SABER_SHELL detected - activating RCE endpoint');
        
        // Log RCE endpoint activation
        emitToSIEM('rce_endpoint_activated', req, 'success', {
          filename: req.file.originalname,
          shell_endpoint: '/shell/exec',
          uploaded_by: req.user
        });
        
        return res.json({
          message: 'JavaScript file processed and shell activated',
          filename: req.file.filename,
          shell_endpoint: '/shell/exec',
          uploaded_by: req.user,
          warning: 'RCE endpoint now active at /shell/exec'
        });
      }
    } catch (err) {
      console.log(`[ERROR] Failed to process JS file: ${err.message}`);
      
      // Log processing error
      // logSecurityEvent('file_processing_error', {
      //   filename: req.file.originalname,
      //   error: err.message
      // }, req, 'error');
      emitToSIEM('file_processing_error', req, 'error', { filename: req.file.originalname });
    }
  }
  
  // Return the URL where the file can be accessed
  const fileUrl = `/uploads/${req.file.filename}`;
  
  res.json({
    message: 'File uploaded successfully',
    filename: req.file.filename,
    url: fileUrl,
    size: req.file.size,
    uploaded_by: req.user
  });
});

// VULNERABLE: Command execution endpoint (activated by JS upload)
app.get('/shell/exec', (req, res) => {
  const cmd = req.query.cmd;
  
  if (!cmd) {
    // Log shell endpoint access (even without command)
    emitToSIEM('shell_access', req, 'success', {
      shell_type: 'web_shell',
      action: 'endpoint_accessed',
      command_provided: false
    });
    
    return res.json({
      message: 'SABER Web Shell Active',
      usage: '?cmd=YOUR_COMMAND',
      example: '?cmd=whoami',
      container: 'api_gateway'
    });
  }
  
  // Log shell command execution to SIEM
  emitToSIEM('shell_command_execution', req, 'success', {
    command: cmd
  });
  
  const { exec } = require('child_process');
  exec(cmd, (error, stdout, stderr) => {
    // Log command result (truncated for SIEM)
    const outputPreview = stdout ? stdout.substring(0, 200) : '';
    emitToSIEM('shell_command_result', req, error ? 'failure' : 'success', {
      command: cmd,
      output_length: stdout ? stdout.length : 0,
      output_preview: outputPreview,
      has_error: !!error
    });
    
    res.json({
      command: cmd,
      stdout: stdout,
      stderr: stderr,
      error: error ? error.message : null,
      container: 'api_gateway'
    });
  });
});

// Internal services information (for Phase 2 SQL injection)
app.get('/api/services', authenticate, (req, res) => {
  res.json({
    internal_services: [
      {
        name: 'database',
        hostname: 'database',
        port: 3306,
        status: 'healthy'
      },
      {
        name: 'vault_service', 
        hostname: 'vault_service',
        port: 6379,
        status: 'healthy'
      }
    ],
    network: 'internal',
    authenticated_as: req.user
  });
});

// Health check endpoint (no auth required)
app.get('/health', (req, res) => {
  res.json({ status: 'ok', timestamp: new Date() });
});

// Error handling
app.use((err, req, res, next) => {
  console.error('Error:', err.message);
  res.status(500).json({ 
    error: 'Internal server error',
    message: err.message 
  });
});

// 404 handler
app.use((req, res) => {
  res.status(404).json({ 
    error: 'Not found',
    available_endpoints: [
      'GET /api/status',
      'POST /api/upload', 
      'GET /api/services',
      'GET /health'
    ]
  });
});

// Background service operations to create legitimate traffic
function startBackgroundServices() {
  console.log('Starting background services for legitimate traffic generation...');
  
  // Health monitoring every 45 seconds
  setInterval(async () => {
    if (siemIngest) {
      try {
        const evt = siemIngest.buildEvent({
          source: 'api_gateway',
          event_type: 'system_health',
          source_ip: '127.0.0.1',
          status: 'success',
          data: {
            service: 'api_gateway',
            purpose: 'health_monitoring',
            legitimate: true,
            timestamp: new Date().toISOString()
          }
        });
        siemIngest.emitSecurityEvent(evt).catch(err => console.warn('[SIEM] Health monitoring emit failed', err.message));
      } catch (e) {
        console.warn('[SIEM] Health monitoring build/emit error', e.message);
      }
    }
  }, 45000);

  // Vault credential refresh every 2 minutes
  setInterval(async () => {
    try {
      const fetch = require('node-fetch');
      const response = await fetch('http://vault_service:6379/secrets/database', {
        headers: {
          'Authorization': `Bearer ${process.env.VAULT_ACCESS_TOKEN}`,
          'X-Service-Purpose': 'credential_refresh',
          'User-Agent': 'Internal-Service/1.0'
        }
      });
      
      if (siemIngest) {
        try {
          const evt = siemIngest.buildEvent({
            source: 'api_gateway',
            event_type: 'secret_access',
            source_ip: '127.0.0.1',
            status: response.ok ? 'success' : 'failure',
            data: {
              endpoint: '/secrets/database',
              purpose: 'credential_refresh',
              legitimate: true,
              response_status: response.status
            }
          });
          siemIngest.emitSecurityEvent(evt).catch(err => console.warn('[SIEM] Credential refresh emit failed', err.message));
        } catch (e) {
          console.warn('[SIEM] Credential refresh build/emit error', e.message);
        }
      }
      
    } catch (error) {
      if (siemIngest) {
        try {
          const evt = siemIngest.buildEvent({
            source: 'api_gateway',
            event_type: 'secret_access',
            source_ip: '127.0.0.1',
            status: 'error',
            data: {
              endpoint: '/secrets/database',
              purpose: 'credential_refresh',
              legitimate: true,
              error: error.message
            }
          });
          siemIngest.emitSecurityEvent(evt).catch(err => console.warn('[SIEM] Credential refresh error emit failed', err.message));
        } catch (e) {
          console.warn('[SIEM] Credential refresh error build/emit error', e.message);
        }
      }
    }
  }, 120000);

  // Compliance audit every 3 minutes (CRITICAL: Accesses crown jewel!)
  setInterval(async () => {
    const auditEndpoints = [
      '/secrets/list',
      '/secrets/admin', 
      '/secrets/flags/crown_jewel',  // Same as red team target!
      '/secrets/infrastructure'
    ];
    
    for (const endpoint of auditEndpoints) {
      try {
        const fetch = require('node-fetch');
        const response = await fetch(`http://vault_service:6379${endpoint}`, {
          headers: {
            'Authorization': `Bearer ${process.env.VAULT_ACCESS_TOKEN}`,
            'X-Service-Purpose': 'compliance_audit',
            'User-Agent': 'Internal-Compliance/2.0'
          }
        });
        
        if (siemIngest) {
          try {
            const evt = siemIngest.buildEvent({
              source: 'api_gateway',
              event_type: 'secret_access',
              source_ip: '127.0.0.1',
              status: response.ok ? 'success' : 'failure',
              data: {
                endpoint: endpoint,
                purpose: 'compliance_audit',
                legitimate: true,
                response_status: response.status
              }
            });
            siemIngest.emitSecurityEvent(evt).catch(err => console.warn('[SIEM] Compliance audit emit failed', err.message));
          } catch (e) {
            console.warn('[SIEM] Compliance audit build/emit error', e.message);
          }
        }
        
      } catch (error) {
        if (siemIngest) {
          try {
            const evt = siemIngest.buildEvent({
              source: 'api_gateway',
              event_type: 'secret_access',
              source_ip: '127.0.0.1',
              status: 'error',
              data: {
                endpoint: endpoint,
                purpose: 'compliance_audit',
                legitimate: true,
                error: error.message
              }
            });
            siemIngest.emitSecurityEvent(evt).catch(err => console.warn('[SIEM] Compliance audit error emit failed', err.message));
          } catch (e) {
            console.warn('[SIEM] Compliance audit error build/emit error', e.message);
          }
        }
      }
    }
  }, 180000);

  console.log('Background services started:');
  console.log('  - Health monitoring: every 45 seconds');
  console.log('  - Vault credential refresh: every 2 minutes');
  console.log('  - Compliance audit (crown jewel access): every 3 minutes');
}

const PORT = 8080;
app.listen(PORT, '0.0.0.0', () => {
  console.log(`API Gateway running on port ${PORT}`);
  console.log('Available endpoints:');
  console.log('  GET /api/status (requires auth)');
  console.log('  POST /api/upload (requires auth)');
  console.log('  GET /api/services (requires auth)');
  console.log('  GET /health (public)');
  console.log('');
  console.log('Valid credentials: api_service_user:Internal_API_Pass_2024!');
  console.log('WARNING: File upload has no validation - educational vulnerability!');
  
  // Start background services after server is running
  startBackgroundServices();
});