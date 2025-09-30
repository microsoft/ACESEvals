// Simple SIEM ingestion helper for Node.js services (api_gateway, vault)
// Usage:
//   const { emitSecurityEvent } = require('./siem_ingest');
//   emitSecurityEvent({ source: 'api_gateway', event_type: 'file_upload', request_uri: '/api/upload', data: { filename: 'shell.js' } });

const http = require('http');
const { v4: uuidv4 } = require('uuid');

const SIEM_INGEST_URL = process.env.SIEM_INGEST_URL || 'http://siem_aggregator:8080/api/events/ingest';
const SIEM_API_KEY = process.env.SIEM_INGEST_API_KEY || 'siem_ingest_key_2024';

function buildEvent({
  source,
  event_type,
  destination_service, // only for simulator-like sources
  source_ip = '127.0.0.1',
  status = 'success',
  session_id,
  user_agent,
  request_uri,
  method,
  data = {},
  event_id,
  timestamp
}) {
  return {
    timestamp: (timestamp || new Date()).toISOString(),
    source,
    destination_service,
    source_ip,
    event_type,
    event_id: event_id || uuidv4(),
    session_id,
    user_agent,
    request_uri,
    method,
    status,
    data
  };
}

function emitSecurityEvent(event) {
  return new Promise((resolve, reject) => {
    try {
      const url = new URL(SIEM_INGEST_URL);
      const payload = JSON.stringify(event);
      const options = {
        hostname: url.hostname,
        port: url.port,
        path: url.pathname,
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Content-Length': Buffer.byteLength(payload),
          'X-API-Key': SIEM_API_KEY,  // Fixed: use correct header name
          'X-Source': event.source     // Fixed: use correct header name
        }
      };
      const req = http.request(options, (res) => {
        let data = '';
        res.on('data', chunk => data += chunk);
        res.on('end', () => {
          if (res.statusCode >= 200 && res.statusCode < 300) {
            resolve(data ? JSON.parse(data) : {});
          } else {
            reject(new Error(`SIEM ingest failed ${res.statusCode}: ${data.slice(0,200)}`));
          }
        });
      });
      req.on('error', reject);
      req.write(payload);
      req.end();
    } catch (e) {
      reject(e);
    }
  });
}

module.exports = { buildEvent, emitSecurityEvent };
