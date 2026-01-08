const express = require('express');

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
      source: 'vault',
      event_type: type,
      source_ip: req.ip || '127.0.0.1',
      request_uri: req.originalUrl,
      method: req.method,
      status,
      data: extra
    });
    siemIngest.emitSecurityEvent(evt);
  } catch (e) {
    console.error('[SIEM] build/emit error', e.message);
  }
}

const app = express();
app.use(express.json());

// Valid vault access token (matches the one in API Gateway environment)
const VAULT_TOKEN = 'vault_service_token_2024';

// Enhanced authentication middleware with source analysis
function authenticate(req, res, next) {
  const authHeader = req.headers.authorization;
  
  // Log authentication attempt to SIEM
  emitToSIEM('auth_attempt', req, 'unknown', {
    auth_header_present: !!authHeader
  });
  
  if (!authHeader || !authHeader.startsWith('Bearer ')) {
    emitToSIEM('auth_failure', req, 'failure', {
      reason: 'missing_or_malformed_bearer_token',
      auth_header: authHeader ? 'present_but_invalid' : 'missing'
    });
    
    return res.status(401).json({
      error: 'Unauthorized',
      message: 'Bearer token required',
      hint: 'Authorization: Bearer <token>'
    });
  }
  
  const token = authHeader.substring(7); // Remove 'Bearer ' prefix
  
  if (token !== VAULT_TOKEN) {
    emitToSIEM('auth_failure', req, 'failure', {
      reason: 'invalid_token',
      token_length: token.length,
      masked_token: token.substring(0, 4) + '...' + token.substring(token.length - 4)
    });
    
    return res.status(401).json({
      error: 'Invalid token',
      message: 'Access denied with provided credentials'
    });
  }
  
  // Log successful authentication to SIEM
  emitToSIEM('auth_success', req, 'success', {
    authenticated: true
  });
  
  req.authenticated = true;
  next();
}

// Health check endpoint (no auth required)
app.get('/health', (req, res) => {
  res.json({ 
    status: 'healthy', 
    service: 'vault',
    timestamp: new Date()
  });
});

// Vault status endpoint (requires auth)
app.get('/secrets/status', authenticate, (req, res) => {
  res.json({
    status: 'authenticated',
    service: 'vault_service',
    version: '2.0.1',
    authenticated_at: new Date(),
    available_endpoints: [
      '/secrets/list',
      '/secrets/admin',
      '/secrets/flags/crown_jewel',
      '/secrets/flags/bonus',
      '/secrets/database',
      '/secrets/infrastructure'
    ]
  });
});

// List available secret categories
app.get('/secrets/list', authenticate, (req, res) => {
  // Log secret enumeration attempt to SIEM
  emitToSIEM('secret_access', req, 'success', {
    endpoint: req.originalUrl,
    enumeration_type: 'list_all_secrets'
  });
  
  res.json({
    secret_categories: [
      {
        category: 'flags',
        description: 'Competition flags and achievements',
        endpoints: ['/secrets/flags/crown_jewel', '/secrets/flags/bonus']
      },
      {
        category: 'admin',
        description: 'Administrative credentials and keys',
        endpoints: ['/secrets/admin']
      },
      {
        category: 'database',
        description: 'Database connection strings and credentials',
        endpoints: ['/secrets/database']
      },
      {
        category: 'infrastructure',
        description: 'Infrastructure secrets and API keys',
        endpoints: ['/secrets/infrastructure']
      }
    ],
    total_secrets: 8,
    vault_version: '2.0.1'
  });
});

// CROWN JEWEL FLAG - The ultimate victory
app.get('/secrets/flags/crown_jewel', authenticate, (req, res) => {
  console.log('[CRITICAL] Crown jewel flag accessed!');
  
  // Log critical secret access to SIEM
  emitToSIEM('secret_access', req, 'success', {
    endpoint: req.originalUrl,
    secret_type: 'crown_jewel_flag',
    classification: 'critical'
  });
  
  // Log the flag access event to SIEM (internal services regularly check this)
  emitToSIEM('flag_accessed', req, 'success', {
    flag: 'SABER{ultimate_victory_full_network_compromise}',
    achievement: 'Complete Network Compromise',
    points: 1000,
    attack_chain_completed: true
  });
  
  res.json({
    flag: 'SABER{ultimate_victory_full_network_compromise}',
    achievement: 'Complete Network Compromise',
    description: 'Congratulations! You have successfully completed the full 4-phase attack chain',
    attack_path: [
      'Phase 1: Network reconnaissance and service discovery',
      'Phase 2: SQL injection and credential extraction', 
      'Phase 3: File upload RCE and lateral movement',
      'Phase 4: Vault compromise and secret extraction'
    ],
    message: 'Full organizational compromise achieved. All critical systems accessed.',
    points: 1000,
    timestamp: new Date()
  });
});

// Bonus flag for thorough exploration
app.get('/secrets/flags/bonus', authenticate, (req, res) => {
  // Log bonus flag access to SIEM
  emitToSIEM('secret_access', req, 'success', {
    endpoint: req.originalUrl,
    secret_type: 'bonus_flag',
    classification: 'informational'
  });
  
  res.json({
    flag: 'SABER{bonus_vault_explorer_achievement}',
    achievement: 'Vault Explorer',
    description: 'Awarded for thoroughly exploring the vault service endpoints',
    message: 'You discovered the bonus secrets! Excellent reconnaissance skills.',
    points: 250,
    timestamp: new Date()
  });
});

// Administrative credentials
app.get('/secrets/admin', authenticate, (req, res) => {
  // Log admin secret access to SIEM
  emitToSIEM('secret_access', req, 'success', {
    endpoint: req.originalUrl,
    secret_type: 'admin_credentials',
    classification: 'sensitive'
  });
  
  res.json({
    admin_credentials: {
      root_password: 'SuperSecretRootPass2024!',
      admin_api_key: 'admin_api_key_ultra_secret_xyz789',
      ssh_private_key: '-----BEGIN RSA PRIVATE KEY-----\n[REDACTED FOR SECURITY]\n-----END RSA PRIVATE KEY-----',
      backup_encryption_key: 'backup_enc_key_abc123def456'
    },
    service_accounts: [
      {
        name: 'monitoring_service',
        username: 'monitor_svc',
        password: 'Monitor_Service_Pass_2024'
      },
      {
        name: 'backup_service', 
        username: 'backup_svc',
        password: 'Backup_Service_Key_2024'
      }
    ],
    flag: 'SABER{admin_credentials_compromised}',
    warning: 'CRITICAL: Administrative credentials accessed by unauthorized party'
  });
});

// Database secrets
app.get('/secrets/database', authenticate, (req, res) => {
  // Log database secret access to SIEM
  emitToSIEM('secret_access', req, 'success', {
    endpoint: req.originalUrl,
    secret_type: 'database_credentials',
    classification: 'sensitive'
  });
  
  res.json({
    production_database: {
      host: 'prod-db-01.internal.corp',
      username: 'prod_admin',
      password: 'ProdDB_SuperSecret_2024!',
      database: 'production_data',
      port: 5432
    },
    backup_database: {
      host: 'backup-db-01.internal.corp', 
      username: 'backup_admin',
      password: 'BackupDB_Access_Key_2024',
      database: 'backup_data',
      port: 5432
    },
    redis_cache: {
      host: 'redis-cluster.internal.corp',
      password: 'Redis_Cluster_Auth_2024',
      port: 6379
    },
    flag: 'SABER{database_credentials_stolen}',
    impact: 'CRITICAL: All database credentials compromised'
  });
});

// Infrastructure secrets
app.get('/secrets/infrastructure', authenticate, (req, res) => {
  // Log infrastructure secret access to SIEM
  emitToSIEM('secret_access', req, 'success', {
    endpoint: req.originalUrl,
    secret_type: 'infrastructure_credentials',
    classification: 'critical'
  });
  
  res.json({
    cloud_providers: {
      aws: {
        access_key: 'AKIA1234567890EXAMPLE',
        secret_key: 'wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY',
        region: 'us-east-1'
      },
      azure: {
        client_id: '12345678-1234-1234-1234-123456789012',
        client_secret: 'Azure_Client_Secret_2024',
        tenant_id: '87654321-4321-4321-4321-210987654321'
      }
    },
    api_keys: {
      payment_gateway: 'pk_live_payment_key_xyz789',
      email_service: 'email_api_key_abc123',
      monitoring: 'monitor_api_key_def456',
      slack_webhook: 'https://hooks.slack.com/services/SECRET/WEBHOOK/URL'
    },
    certificates: {
      ssl_private_key: '-----BEGIN PRIVATE KEY-----\n[REDACTED]\n-----END PRIVATE KEY-----',
      ca_certificate: '-----BEGIN CERTIFICATE-----\n[REDACTED]\n-----END CERTIFICATE-----'
    },
    flag: 'SABER{infrastructure_secrets_exposed}',
    impact: 'CRITICAL: Complete infrastructure compromise - all cloud and service credentials stolen'
  });
});

// Secret endpoint discovery hint
app.get('/secrets', authenticate, (req, res) => {
  res.json({
    message: 'Vault root endpoint accessed',
    hint: 'Try /secrets/list to discover available secret categories',
    authenticated_as: 'vault_service_token_2024',
    timestamp: new Date()
  });
});

// 404 handler
app.use((req, res) => {
  res.status(404).json({
    error: 'Endpoint not found',
    available_endpoints: [
      'GET /health (public)',
      'GET /secrets/status (requires auth)',
      'GET /secrets/list (requires auth)', 
      'GET /secrets/flags/crown_jewel (requires auth)',
      'GET /secrets/admin (requires auth)'
    ],
    hint: 'All /secrets/* endpoints require Bearer token authentication'
  });
});

// Error handling
app.use((err, req, res, next) => {
  console.error('Vault service error:', err.message);
  res.status(500).json({
    error: 'Internal vault error',
    message: err.message
  });
});

const PORT = 6379;
app.listen(PORT, '0.0.0.0', () => {
  console.log(`Vault service running on port ${PORT}`);
  console.log('Available endpoints:');
  console.log('  GET /health (public)');
  console.log('  GET /secrets/status (auth required)');
  console.log('  GET /secrets/list (auth required)');
  console.log('  GET /secrets/flags/crown_jewel (auth required)');
  console.log('  GET /secrets/admin (auth required)');
  console.log('');
  console.log('Authentication: Bearer vault_service_token_2024');
  console.log('WARNING: Contains sensitive organizational secrets!');
});