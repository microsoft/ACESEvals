# Exchange Online / Microsoft Graph Mail API Mock Service
# Simulates Microsoft Graph Mail API for email access
# Generates logs matching Office 365 MailItemsAccessed audit schema

from flask import Flask, request, jsonify
from functools import wraps
import os
import uuid
import json
import random
import threading
import base64
from datetime import datetime

app = Flask(__name__)

TENANT_ID = os.environ.get('TENANT_ID', '87654321-4321-4321-4321-cba987654321')
ORGANIZATION_ID = os.environ.get('ORGANIZATION_ID', 'org-12345678-1234-1234-1234-123456789abc')

_lock = threading.Lock()

# In-memory stores
MAILBOXES = {}  # user_id -> {folders: [...], messages: [...]}
AUDIT_LOGS = []
VALID_TOKENS = set()  # Explicit tokens with Mail.Read scope
VALID_APP_IDS = set()  # App IDs with Mail.Read permission


def generate_mail_audit_log(operation, result_status, user_id, folder_id=None,
                            internet_message_ids=None, client_ip=None,
                            app_id=None, operation_count=1):
    """Generate log entry matching Office 365 MailItemsAccessed schema."""
    log_entry = {
        "CreationTime": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.") +
                        f"{random.randint(0, 9999999):07d}Z",
        "Id": str(uuid.uuid4()),
        "Operation": operation,
        "OrganizationId": ORGANIZATION_ID,
        "RecordType": 50,  # ExchangeItemAggregated
        "ResultStatus": result_status,
        "UserKey": user_id,
        "UserType": 0,
        "Version": 1,
        "Workload": "Exchange",
        "ClientIP": client_ip or request.remote_addr,
        "UserId": user_id,
        "AppId": app_id or str(uuid.uuid4()),
        "ClientAppId": app_id,
        "ClientInfoString": request.headers.get('User-Agent', 'unknown'),
        "ExternalAccess": False,
        "InternalLogonType": 0,
        "LogonType": 0,
        "LogonUserSid": f"S-1-5-21-{random.randint(1000000000,9999999999)}-{random.randint(1000,9999)}",
        "MailboxGuid": str(uuid.uuid4()),
        "MailboxOwnerSid": f"S-1-5-21-{random.randint(1000000000,9999999999)}-{random.randint(1000,9999)}",
        "MailboxOwnerUPN": user_id,
        "OperationProperties": [],
        "SessionId": str(uuid.uuid4()),
        "AffectedItems": [],
        "Folders": [
            {
                "Id": folder_id or "inbox",
                "Path": "\\Inbox"
            }
        ] if folder_id else [],
        "OperationCount": operation_count
    }

    if internet_message_ids:
        log_entry["AffectedItems"] = [
            {"InternetMessageId": msg_id} for msg_id in internet_message_ids
        ]

    with _lock:
        AUDIT_LOGS.append(log_entry)
        if len(AUDIT_LOGS) > 10000:
            AUDIT_LOGS.pop(0)

    print(f"EXCHANGE_AUDIT: {json.dumps(log_entry)}")
    return log_entry


def decode_jwt_payload(token):
    """Decode JWT payload without verification (mock service)."""
    try:
        parts = token.split('.')
        if len(parts) != 3:
            return None
        # Decode payload (second part)
        payload = parts[1]
        # Add padding if needed
        padding = 4 - len(payload) % 4
        if padding != 4:
            payload += '=' * padding
        decoded = base64.urlsafe_b64decode(payload)
        return json.loads(decoded)
    except Exception as e:
        print(f"JWT decode error: {e}")
        return None


def validate_mail_token(f):
    """Validates Bearer token has Mail.Read scope."""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization', '')

        if not auth_header.startswith('Bearer '):
            generate_mail_audit_log(
                "MailItemsAccessed", "Failed", "unknown",
                client_ip=request.remote_addr
            )
            return jsonify({
                'error': {'code': 'InvalidAuthenticationToken',
                         'message': 'Access token is missing or malformed.'}
            }), 401

        token = auth_header[7:]

        # Check if token is in explicitly seeded tokens
        if token in VALID_TOKENS:
            return f(*args, **kwargs)

        # Try to decode as JWT and validate
        payload = decode_jwt_payload(token)
        if payload:
            audience = payload.get('aud', '')
            app_id = payload.get('appid') or payload.get('azp') or payload.get('sub', '')

            # Accept if token is for graph.microsoft.com
            if 'graph.microsoft.com' in audience:
                # If we have registered app IDs, check against them
                if VALID_APP_IDS:
                    if app_id in VALID_APP_IDS:
                        print(f"EXCHANGE: Accepted token for app_id={app_id}")
                        return f(*args, **kwargs)
                else:
                    # No app IDs configured, accept any graph token
                    print(f"EXCHANGE: Accepted graph token (no app_id filter)")
                    return f(*args, **kwargs)

        # Token validation failed
        generate_mail_audit_log(
            "MailItemsAccessed", "Failed", "unknown",
            client_ip=request.remote_addr
        )
        return jsonify({
            'error': {'code': 'InvalidAuthenticationToken',
                     'message': 'Token validation failed. Insufficient permissions.'}
        }), 403

    return decorated


def _default_folders():
    """Return default mailbox folder structure."""
    return [
        {'id': 'inbox', 'displayName': 'Inbox', 'parentFolderId': None,
         'childFolderCount': 0, 'unreadItemCount': 5, 'totalItemCount': 50},
        {'id': 'drafts', 'displayName': 'Drafts', 'parentFolderId': None,
         'childFolderCount': 0, 'unreadItemCount': 0, 'totalItemCount': 3},
        {'id': 'sentitems', 'displayName': 'Sent Items', 'parentFolderId': None,
         'childFolderCount': 0, 'unreadItemCount': 0, 'totalItemCount': 100},
        {'id': 'deleteditems', 'displayName': 'Deleted Items', 'parentFolderId': None,
         'childFolderCount': 0, 'unreadItemCount': 0, 'totalItemCount': 25},
        {'id': 'archive', 'displayName': 'Archive', 'parentFolderId': None,
         'childFolderCount': 0, 'unreadItemCount': 0, 'totalItemCount': 200}
    ]


# ============================================
# MICROSOFT GRAPH MAIL API ENDPOINTS
# ============================================

@app.route('/v1.0/users/<user_id>/messages', methods=['GET'])
@app.route('/v1.0/me/messages', methods=['GET'])
@validate_mail_token
def list_messages(user_id='me'):
    """GET /v1.0/users/{id}/messages - List emails in mailbox."""
    top = request.args.get('$top', 10, type=int)
    skip = request.args.get('$skip', 0, type=int)

    if user_id == 'me':
        user_id = 'cfo@contoso.com'

    mailbox = MAILBOXES.get(user_id, {'messages': [], 'folders': []})
    messages = mailbox.get('messages', [])

    paginated = messages[skip:skip + top]

    msg_ids = [m.get('internetMessageId', '') for m in paginated]
    generate_mail_audit_log(
        "MailItemsAccessed", "Succeeded", user_id,
        folder_id="inbox", internet_message_ids=msg_ids,
        operation_count=len(paginated)
    )

    return jsonify({
        '@odata.context': f'https://graph.microsoft.com/v1.0/$metadata#users(\'{user_id}\')/messages',
        '@odata.count': len(messages),
        'value': paginated
    })


@app.route('/v1.0/users/<user_id>/messages/<message_id>', methods=['GET'])
@app.route('/v1.0/me/messages/<message_id>', methods=['GET'])
@validate_mail_token
def get_message(user_id='me', message_id=None):
    """GET /v1.0/users/{id}/messages/{id} - Get specific email."""
    if user_id == 'me':
        user_id = 'cfo@contoso.com'

    mailbox = MAILBOXES.get(user_id, {'messages': []})
    message = next((m for m in mailbox.get('messages', [])
                   if m.get('id') == message_id), None)

    if not message:
        generate_mail_audit_log(
            "MailItemsAccessed", "Failed", user_id,
            client_ip=request.remote_addr
        )
        return jsonify({
            'error': {'code': 'ErrorItemNotFound',
                     'message': 'The specified object was not found in the store.'}
        }), 404

    generate_mail_audit_log(
        "MailItemsAccessed", "Succeeded", user_id,
        internet_message_ids=[message.get('internetMessageId', '')]
    )

    return jsonify(message)


@app.route('/v1.0/users/<user_id>/mailFolders', methods=['GET'])
@app.route('/v1.0/me/mailFolders', methods=['GET'])
@validate_mail_token
def list_mail_folders(user_id='me'):
    """GET /v1.0/users/{id}/mailFolders - List mail folders."""
    if user_id == 'me':
        user_id = 'cfo@contoso.com'

    mailbox = MAILBOXES.get(user_id, {'folders': []})
    folders = mailbox.get('folders', _default_folders())

    generate_mail_audit_log(
        "FolderBind", "Succeeded", user_id
    )

    return jsonify({
        '@odata.context': f'https://graph.microsoft.com/v1.0/$metadata#users(\'{user_id}\')/mailFolders',
        'value': folders
    })


# ============================================
# ADMIN ENDPOINTS (for seeder)
# ============================================

@app.route('/admin/tokens', methods=['GET', 'POST', 'DELETE'])
def admin_tokens():
    """Manage valid tokens and app IDs with Mail.Read scope."""
    global VALID_TOKENS, VALID_APP_IDS

    if request.method == 'POST':
        data = request.get_json() or {}
        tokens = data.get('tokens', [])
        app_ids = data.get('app_ids', [])
        VALID_TOKENS.update(tokens)
        VALID_APP_IDS.update(app_ids)
        print(f"EXCHANGE_ADMIN: Injected {len(tokens)} token(s), {len(app_ids)} app_id(s)")
        return jsonify({
            "status": "ok",
            "tokens_count": len(VALID_TOKENS),
            "app_ids_count": len(VALID_APP_IDS)
        })

    elif request.method == 'DELETE':
        token_count = len(VALID_TOKENS)
        app_id_count = len(VALID_APP_IDS)
        VALID_TOKENS.clear()
        VALID_APP_IDS.clear()
        return jsonify({"status": "ok", "cleared_tokens": token_count, "cleared_app_ids": app_id_count})

    else:
        return jsonify({
            "tokens_count": len(VALID_TOKENS),
            "app_ids": list(VALID_APP_IDS)
        })


@app.route('/admin/mailboxes', methods=['GET', 'POST', 'DELETE'])
def admin_mailboxes():
    """Seed mailbox data."""
    global MAILBOXES

    if request.method == 'POST':
        data = request.get_json() or {}
        for user_id, mailbox_data in data.items():
            MAILBOXES[user_id] = mailbox_data
        print(f"EXCHANGE_ADMIN: Seeded {len(data)} mailbox(es)")
        return jsonify({"status": "ok", "mailboxes": list(MAILBOXES.keys())})

    elif request.method == 'DELETE':
        count = len(MAILBOXES)
        MAILBOXES.clear()
        return jsonify({"status": "ok", "cleared": count})

    else:
        return jsonify({"mailboxes": list(MAILBOXES.keys()),
                       "count": len(MAILBOXES)})


@app.route('/audit/logs', methods=['GET'])
def get_audit_logs():
    """Get audit logs in Office 365 MailItemsAccessed format."""
    with _lock:
        logs_copy = list(AUDIT_LOGS)
    return jsonify({'value': logs_copy, 'count': len(logs_copy)})


@app.route('/health', methods=['GET'])
@app.route('/healthz', methods=['GET'])
def health():
    return jsonify({'status': 'healthy', 'service': 'exchange-online'})


if __name__ == '__main__':
    print(f"Starting Exchange Online mock for tenant {TENANT_ID}")
    app.run(host='0.0.0.0', port=443, ssl_context='adhoc')
