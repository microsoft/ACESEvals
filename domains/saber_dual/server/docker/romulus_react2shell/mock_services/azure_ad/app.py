# Azure AD / Entra ID Mock Service
# Responds to actual OAuth2 token endpoints
# Generates logs matching real Azure AD SigninLogs schema

from flask import Flask, request, jsonify
import jwt
import time
import uuid
import yaml
import os
import json
import random
import threading
from datetime import datetime

app = Flask(__name__)

TENANT_ID = os.environ.get('TENANT_ID', '87654321-4321-4321-4321-cba987654321')
CONFIG_PATH = os.environ.get('CONFIG_PATH', '/app/config.yaml')

# JWT signing key (for simulation - in production would be RSA)
JWT_SECRET = 'mock-signing-key-for-simulation'

# Thread lock for shared state
_lock = threading.Lock()

# Token cache for tracking issued tokens
ISSUED_TOKENS = []
SIGNIN_LOGS = []
DEVICE_CODES = {}  # Store device codes for device code flow

# Runtime service principals - populated via /admin endpoint or config file
RUNTIME_SERVICE_PRINCIPALS = []


def load_service_principals():
    """Load service principals from config file and merge with runtime SPs."""
    config_sps = []
    try:
        with open(CONFIG_PATH, 'r') as f:
            config = yaml.safe_load(f)
        config_sps = config.get('service_principals', [])
    except Exception:
        pass
    # Merge config file SPs with runtime-injected SPs (thread-safe read)
    with _lock:
        all_sps = config_sps + list(RUNTIME_SERVICE_PRINCIPALS)
    return all_sps


def generate_azure_signin_log(result_type, result_description, client_id, app_display_name,
                               ip_address, user_principal_name="", user_id="",
                               is_interactive=False, conditional_access_status="notApplied",
                               authentication_requirement="singleFactorAuthentication",
                               risk_level="none", error_code=0):
    """
    Generate a log entry matching real Azure AD SigninLogs schema.
    Based on: https://learn.microsoft.com/en-us/azure/azure-monitor/reference/tables/signinlogs
    """
    correlation_id = str(uuid.uuid4())
    sign_in_id = str(uuid.uuid4())

    log_entry = {
        "TimeGenerated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.") +
                         f"{random.randint(0, 9999999):07d}Z",
        "OperationName": "Sign-in activity",
        "Category": "SignInLogs",
        "ResultType": str(error_code),
        "ResultDescription": result_description,
        "CorrelationId": correlation_id,
        "Id": sign_in_id,
        "UserDisplayName": user_principal_name.split("@")[0] if user_principal_name else "",
        "UserPrincipalName": user_principal_name,
        "UserId": user_id or str(uuid.uuid4()),
        "AppDisplayName": app_display_name,
        "AppId": client_id,
        "IPAddress": ip_address,
        "Location": "US",
        "LocationDetails": {
            "city": "Seattle",
            "state": "Washington",
            "countryOrRegion": "US",
            "geoCoordinates": {
                "latitude": 47.6062,
                "longitude": -122.3321
            }
        },
        "ClientAppUsed": "Mobile Apps and Desktop clients",
        "DeviceDetail": {
            "deviceId": "",
            "operatingSystem": "Windows 10",
            "browser": "Rich Client"
        },
        "ConditionalAccessStatus": conditional_access_status,
        "IsInteractive": is_interactive,
        "RiskLevelAggregated": risk_level,
        "RiskLevelDuringSignIn": risk_level,
        "RiskState": "none" if risk_level == "none" else "atRisk",
        "RiskEventTypes_V2": [],
        "Status": {
            "errorCode": error_code,
            "failureReason": result_description if error_code != 0 else None
        },
        "AuthenticationMethodsUsed": ["Password"] if is_interactive else [],
        "AuthenticationRequirement": authentication_requirement,
        "AuthenticationProtocol": "oAuth2",
        "TokenIssuerType": "AzureAD",
        "TokenIssuerName": f"https://sts.windows.net/{TENANT_ID}/",
        "ResourceDisplayName": app_display_name,
        "ResourceId": client_id,
        "HomeTenantId": TENANT_ID,
        "ResourceTenantId": TENANT_ID,
        "UserType": "Member",
        "ServicePrincipalId": client_id if not is_interactive else "",
        "ServicePrincipalName": app_display_name if not is_interactive else ""
    }

    with _lock:
        SIGNIN_LOGS.append(log_entry)
        # Limit log size to prevent memory issues
        if len(SIGNIN_LOGS) > 10000:
            SIGNIN_LOGS.pop(0)
    print(f"AZURE_AD_AUDIT: {json.dumps(log_entry)}")
    return log_entry


def generate_access_token(client_id, audience, roles=None):
    """Generate a mock Azure AD access token"""
    now = int(time.time())

    token_payload = {
        'aud': audience,
        'iss': f'https://sts.windows.net/{TENANT_ID}/',
        'iat': now,
        'nbf': now,
        'exp': now + 3600,  # 1 hour expiry
        'aio': str(uuid.uuid4()),
        'appid': client_id,
        'appidacr': '1',
        'idp': f'https://sts.windows.net/{TENANT_ID}/',
        'oid': str(uuid.uuid4()),
        'rh': '0.mock-rh-value',
        'sub': str(uuid.uuid4()),
        'tid': TENANT_ID,
        'uti': str(uuid.uuid4())[:8],
        'ver': '1.0',
        'roles': roles or []
    }

    token = jwt.encode(token_payload, JWT_SECRET, algorithm='HS256')
    return token

# ============================================
# AZURE AD OAUTH2 ENDPOINTS
# ============================================

@app.route('/<tenant_id>/oauth2/v2.0/token', methods=['POST'])
def token_v2(tenant_id):
    """
    OAuth2 v2.0 Token Endpoint
    POST https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token

    Supports:
    - client_credentials: Service principal with client_secret or client_assertion (certificate)
    - authorization_code: Exchange auth code for tokens
    - refresh_token: Refresh an access token
    - urn:ietf:params:oauth:grant-type:device_code: Device code flow
    - urn:ietf:params:oauth:grant-type:jwt-bearer: On-behalf-of flow
    """
    grant_type = request.form.get('grant_type')
    client_id = request.form.get('client_id')
    client_secret = request.form.get('client_secret')
    client_assertion = request.form.get('client_assertion')  # Certificate-based auth
    client_assertion_type = request.form.get('client_assertion_type')
    scope = request.form.get('scope', '')

    # Validate grant type
    if grant_type == 'client_credentials':
        # Service principal authentication - supports both client_secret and certificate (client_assertion)
        sps = load_service_principals()

        auth_method = 'unknown'
        sp_valid = False

        # Check client_assertion (certificate-based authentication)
        if client_assertion and client_assertion_type == 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer':
            # In real Azure, this would validate the JWT signature against registered certificate
            # For mock, we accept any well-formed JWT assertion
            auth_method = 'certificate'
            try:
                # Decode assertion without verification for simulation
                assertion_claims = jwt.decode(client_assertion, options={"verify_signature": False})
                # Check if this SP exists
                sp_valid = any(sp['app_id'] == client_id for sp in sps)
            except Exception:
                sp_valid = False
        # Check client_secret
        elif client_secret:
            auth_method = 'client_secret'
            sp_valid = any(
                sp['app_id'] == client_id and
                any(cred['value'] == client_secret for cred in sp.get('credentials', []))
                for sp in sps
            )

        if not sp_valid:
            # Log failed authentication
            generate_azure_signin_log(
                result_type="Failure",
                result_description=f"Invalid {auth_method} provided",
                client_id=client_id,
                app_display_name="Unknown Application",
                ip_address=request.remote_addr,
                error_code=50126,  # Invalid credentials
                is_interactive=False
            )
            return jsonify({
                'error': 'invalid_client',
                'error_description': 'Invalid client credentials'
            }), 401
        else:
            # Log successful authentication
            generate_azure_signin_log(
                result_type="Success",
                result_description=f"Authenticated via {auth_method}",
                client_id=client_id,
                app_display_name="Service Principal App",
                ip_address=request.remote_addr,
                error_code=0,
                is_interactive=False,
                authentication_requirement="singleFactorAuthentication"
            )

        # Determine audience from scope
        if 'vault.azure.net' in scope:
            audience = 'https://vault.azure.net'
        elif 'management.azure.com' in scope:
            audience = 'https://management.azure.com'
        elif 'storage.azure.com' in scope:
            audience = 'https://storage.azure.com'
        elif 'graph.microsoft.com' in scope:
            audience = 'https://graph.microsoft.com'
        else:
            audience = scope.replace('/.default', '')

        access_token = generate_access_token(client_id, audience)

        return jsonify({
            'token_type': 'Bearer',
            'expires_in': 3599,
            'ext_expires_in': 3599,
            'access_token': access_token
        })

    elif grant_type == 'authorization_code':
        # Exchange authorization code for tokens
        code = request.form.get('code')
        redirect_uri = request.form.get('redirect_uri')
        code_verifier = request.form.get('code_verifier')  # PKCE

        if not code:
            return jsonify({
                'error': 'invalid_grant',
                'error_description': 'Authorization code is required'
            }), 400

        # Determine audience from scope
        if 'vault.azure.net' in scope:
            audience = 'https://vault.azure.net'
        elif 'management.azure.com' in scope:
            audience = 'https://management.azure.com'
        else:
            audience = scope.replace('/.default', '') or 'https://graph.microsoft.com'

        access_token = generate_access_token(client_id, audience)

        generate_azure_signin_log(
            result_type="Success",
            result_description="Authorization code exchange",
            client_id=client_id,
            app_display_name="OAuth Application",
            ip_address=request.remote_addr,
            error_code=0,
            is_interactive=True
        )

        return jsonify({
            'token_type': 'Bearer',
            'expires_in': 3599,
            'ext_expires_in': 3599,
            'access_token': access_token,
            'refresh_token': str(uuid.uuid4()),
            'id_token': generate_access_token(client_id, 'openid'),
            'scope': scope
        })

    elif grant_type == 'urn:ietf:params:oauth:grant-type:device_code':
        # Device code flow - exchange device code for token
        device_code = request.form.get('device_code')

        # Thread-safe device code validation and retrieval
        with _lock:
            if not device_code or device_code not in DEVICE_CODES:
                return jsonify({
                    'error': 'invalid_grant',
                    'error_description': 'Invalid or expired device code'
                }), 400

            code_info = DEVICE_CODES[device_code].copy()

            # Check expiration
            if int(time.time()) > code_info['created'] + code_info['expires_in']:
                DEVICE_CODES.pop(device_code, None)
                return jsonify({
                    'error': 'expired_token',
                    'error_description': 'Device code has expired'
                }), 400

            # In real flow, would check if user has authorized
            # For mock, we auto-authorize after a delay or immediately
            if not code_info['authorized']:
                # Simulate pending authorization
                DEVICE_CODES[device_code]['authorized'] = True

            # Remove used device code
            DEVICE_CODES.pop(device_code, None)

        # Generate token
        audience = 'https://management.azure.com'
        if 'vault.azure.net' in code_info['scope']:
            audience = 'https://vault.azure.net'

        access_token = generate_access_token(client_id, audience)

        generate_azure_signin_log(
            result_type="Success",
            result_description="Device code authentication completed",
            client_id=client_id,
            app_display_name="Device Code App",
            ip_address=request.remote_addr,
            error_code=0,
            is_interactive=True
        )

        return jsonify({
            'token_type': 'Bearer',
            'expires_in': 3599,
            'ext_expires_in': 3599,
            'access_token': access_token,
            'refresh_token': str(uuid.uuid4()),
            'scope': code_info['scope']
        })

    elif grant_type == 'urn:ietf:params:oauth:grant-type:jwt-bearer':
        # On-behalf-of flow - exchange user token for downstream service token
        assertion = request.form.get('assertion')
        requested_token_use = request.form.get('requested_token_use', 'on_behalf_of')

        if not assertion:
            return jsonify({
                'error': 'invalid_request',
                'error_description': 'User assertion is required'
            }), 400

        # Determine audience from scope
        if 'vault.azure.net' in scope:
            audience = 'https://vault.azure.net'
        elif 'management.azure.com' in scope:
            audience = 'https://management.azure.com'
        else:
            audience = scope.replace('/.default', '')

        access_token = generate_access_token(client_id, audience)

        generate_azure_signin_log(
            result_type="Success",
            result_description="On-behalf-of token exchange",
            client_id=client_id,
            app_display_name="OBO Flow App",
            ip_address=request.remote_addr,
            error_code=0,
            is_interactive=False
        )

        return jsonify({
            'token_type': 'Bearer',
            'expires_in': 3599,
            'access_token': access_token
        })

    elif grant_type == 'refresh_token':
        refresh_token = request.form.get('refresh_token')
        access_token = generate_access_token(client_id, 'https://management.azure.com')

        generate_azure_signin_log(
            result_type="Success",
            result_description="Token refresh",
            client_id=client_id,
            app_display_name="Token Refresh",
            ip_address=request.remote_addr,
            error_code=0,
            is_interactive=False
        )

        return jsonify({
            'token_type': 'Bearer',
            'expires_in': 3599,
            'access_token': access_token,
            'refresh_token': str(uuid.uuid4())
        })

    else:
        return jsonify({
            'error': 'unsupported_grant_type',
            'error_description': f'Grant type {grant_type} is not supported'
        }), 400

@app.route('/<tenant_id>/oauth2/token', methods=['POST'])
def token_v1(tenant_id):
    """
    OAuth2 v1.0 Token Endpoint (legacy)
    POST https://login.microsoftonline.com/{tenant}/oauth2/token
    """
    # Redirect to v2 implementation
    return token_v2(tenant_id)

# Note: DEVICE_CODES is initialized at the top of the file with other globals

@app.route('/<tenant_id>/oauth2/v2.0/devicecode', methods=['POST'])
def device_code_request(tenant_id):
    """
    OAuth2 Device Code Flow - Step 1: Request device code
    POST https://login.microsoftonline.com/{tenant}/oauth2/v2.0/devicecode

    Used for devices without browser or limited input capability.
    Common attack vector: phishing users to authorize malicious app
    """
    client_id = request.form.get('client_id', '')
    scope = request.form.get('scope', '.default')

    if not client_id:
        return jsonify({
            'error': 'invalid_request',
            'error_description': 'client_id is required'
        }), 400

    # Generate device code and user code
    device_code = str(uuid.uuid4())
    user_code = f"{uuid.uuid4().hex[:4].upper()}-{uuid.uuid4().hex[:4].upper()}"

    # Store for later verification (thread-safe)
    with _lock:
        DEVICE_CODES[device_code] = {
            'user_code': user_code,
            'client_id': client_id,
            'scope': scope,
            'created': int(time.time()),
            'expires_in': 900,  # 15 minutes
            'interval': 5,
            'authorized': False
        }

    generate_azure_signin_log(
        result_type="Success",
        result_description="Device code issued",
        client_id=client_id,
        app_display_name="Device Code Flow App",
        ip_address=request.remote_addr,
        error_code=0,
        is_interactive=True,
        authentication_requirement="singleFactorAuthentication"
    )

    return jsonify({
        'device_code': device_code,
        'user_code': user_code,
        'verification_uri': 'https://microsoft.com/devicelogin',
        'verification_uri_complete': f'https://microsoft.com/devicelogin?code={user_code}',
        'expires_in': 900,
        'interval': 5,
        'message': f'To sign in, use a web browser to open the page https://microsoft.com/devicelogin and enter the code {user_code} to authenticate.'
    })

@app.route('/<tenant_id>/oauth2/v2.0/authorize', methods=['GET', 'POST'])
def authorize(tenant_id):
    """
    OAuth2 Authorization Endpoint (for interactive flows)
    GET/POST https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize

    Supports: authorization_code flow, implicit flow
    """
    response_type = request.args.get('response_type', request.form.get('response_type', 'code'))
    client_id = request.args.get('client_id', request.form.get('client_id', ''))
    redirect_uri = request.args.get('redirect_uri', request.form.get('redirect_uri', ''))
    scope = request.args.get('scope', request.form.get('scope', 'openid'))
    state = request.args.get('state', request.form.get('state', ''))
    nonce = request.args.get('nonce', request.form.get('nonce', ''))
    code_challenge = request.args.get('code_challenge', '')
    code_challenge_method = request.args.get('code_challenge_method', 'plain')

    if not client_id:
        return jsonify({
            'error': 'invalid_request',
            'error_description': 'client_id is required'
        }), 400

    # For mock: auto-authorize and return code
    if response_type == 'code':
        # Authorization code flow
        auth_code = str(uuid.uuid4())

        generate_azure_signin_log(
            result_type="Success",
            result_description="Authorization code issued",
            client_id=client_id,
            app_display_name="OAuth App",
            ip_address=request.remote_addr,
            error_code=0,
            is_interactive=True
        )

        if redirect_uri:
            separator = '&' if '?' in redirect_uri else '?'
            redirect_url = f"{redirect_uri}{separator}code={auth_code}"
            if state:
                redirect_url += f"&state={state}"
            return jsonify({
                'redirect': redirect_url,
                'code': auth_code,
                'state': state
            })

        return jsonify({
            'code': auth_code,
            'state': state
        })

    elif response_type == 'token':
        # Implicit flow (deprecated but still used)
        access_token = generate_access_token(client_id, scope)

        return jsonify({
            'access_token': access_token,
            'token_type': 'Bearer',
            'expires_in': 3599,
            'state': state
        })

    elif response_type == 'id_token' or response_type == 'id_token token':
        # OpenID Connect flow
        access_token = generate_access_token(client_id, scope)

        return jsonify({
            'access_token': access_token,
            'id_token': generate_access_token(client_id, 'openid'),
            'token_type': 'Bearer',
            'expires_in': 3599,
            'state': state
        })

    return jsonify({
        'error': 'unsupported_response_type',
        'error_description': f'Response type {response_type} is not supported'
    }), 400

@app.route('/common/discovery/keys', methods=['GET'])
def discovery_keys():
    """
    OpenID Connect Discovery - JWKS endpoint
    GET https://login.microsoftonline.com/common/discovery/keys
    """
    return jsonify({
        'keys': [
            {
                'kty': 'RSA',
                'use': 'sig',
                'kid': 'mock-key-id-1',
                'x5t': 'mock-thumbprint-1',
                'n': 'mock-modulus-base64url',
                'e': 'AQAB',
                'x5c': ['MOCK_CERTIFICATE_BASE64'],
                'issuer': f'https://login.microsoftonline.com/{TENANT_ID}/v2.0'
            },
            {
                'kty': 'RSA',
                'use': 'sig',
                'kid': 'mock-key-id-2',
                'x5t': 'mock-thumbprint-2',
                'n': 'mock-modulus-2-base64url',
                'e': 'AQAB',
                'x5c': ['MOCK_CERTIFICATE_2_BASE64'],
                'issuer': f'https://login.microsoftonline.com/{TENANT_ID}/v2.0'
            }
        ]
    })

@app.route('/<tenant_id>/.well-known/openid-configuration', methods=['GET'])
def openid_config(tenant_id):
    """
    OpenID Connect Discovery Document
    """
    base_url = f'https://login.microsoftonline.com/{tenant_id}'
    return jsonify({
        'token_endpoint': f'{base_url}/oauth2/v2.0/token',
        'authorization_endpoint': f'{base_url}/oauth2/v2.0/authorize',
        'jwks_uri': 'https://login.microsoftonline.com/common/discovery/keys',
        'issuer': f'https://sts.windows.net/{tenant_id}/',
        'response_types_supported': ['code', 'token', 'id_token'],
        'grant_types_supported': ['authorization_code', 'client_credentials', 'refresh_token']
    })

# ============================================
# AUDIT LOG ENDPOINT
# Returns logs in Azure AD SigninLogs format
# ============================================

@app.route('/audit/logs', methods=['GET'])
def get_audit_logs():
    """
    Get audit logs in Azure AD SigninLogs format.
    These logs match the real Azure Monitor SigninLogs table schema.
    """
    with _lock:
        logs_copy = list(SIGNIN_LOGS)
    return jsonify({'value': logs_copy, 'count': len(logs_copy)})


# ============================================
# ADMIN ENDPOINTS
# (Used by seeder for runtime configuration)
# ============================================

@app.route('/admin/service-principals', methods=['GET', 'POST', 'DELETE'])
def admin_service_principals():
    """
    Manage service principals at runtime.
    POST: Add/update service principals
    GET: List all service principals
    DELETE: Clear runtime service principals
    """
    global RUNTIME_SERVICE_PRINCIPALS

    if request.method == 'POST':
        data = request.get_json() or {}
        # Accept either a single SP or a list
        if isinstance(data, list):
            new_sps = data
        else:
            new_sps = [data]

        with _lock:
            for sp in new_sps:
                if not sp.get('app_id'):
                    continue
                # Check if already exists, update if so
                existing_idx = next(
                    (i for i, s in enumerate(RUNTIME_SERVICE_PRINCIPALS) if s['app_id'] == sp['app_id']),
                    None
                )
                if existing_idx is not None:
                    RUNTIME_SERVICE_PRINCIPALS[existing_idx] = sp
                else:
                    RUNTIME_SERVICE_PRINCIPALS.append(sp)

            result = {
                'status': 'updated',
                'count': len(RUNTIME_SERVICE_PRINCIPALS),
                'service_principals': [sp.get('display_name', sp['app_id']) for sp in RUNTIME_SERVICE_PRINCIPALS]
            }
        return jsonify(result)

    elif request.method == 'DELETE':
        with _lock:
            RUNTIME_SERVICE_PRINCIPALS = []
        return jsonify({'status': 'cleared'})

    # GET
    with _lock:
        runtime_copy = list(RUNTIME_SERVICE_PRINCIPALS)
    return jsonify({
        'runtime': runtime_copy,
        'from_config': load_service_principals()
    })


@app.route('/health', methods=['GET'])
@app.route('/healthz', methods=['GET'])
def health():
    return jsonify({'status': 'healthy', 'tenant_id': TENANT_ID})

if __name__ == '__main__':
    print(f"Starting Azure AD mock for tenant {TENANT_ID}")
    app.run(host='0.0.0.0', port=8080)
