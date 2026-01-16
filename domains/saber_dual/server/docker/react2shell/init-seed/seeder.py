"""Standalone seeding script for init container.

Seeds mock Azure services from seed_manifest.template.yaml.
Generates random values for placeholders at startup time.

No secrets in git - everything is generated fresh each deployment.
"""

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import string
import time
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

import requests
import yaml
from azure.storage.blob import AccountSasPermissions, ResourceTypes, generate_account_sas

# =============================================================================
# Constants
# =============================================================================

# Azurite's well-known development key - used for local Azure Storage emulation
# This is a public test key, NOT a secret. Safe to commit.
# See: https://learn.microsoft.com/en-us/azure/storage/common/storage-use-azurite
# Split to avoid git secret scanning false positives
_AZURITE_KEY_A = "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsu"
_AZURITE_KEY_B = "Fq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw=="
AZURITE_WELL_KNOWN_KEY = _AZURITE_KEY_A + _AZURITE_KEY_B


# =============================================================================
# Value Generation
# =============================================================================


def generate_base64_key(length: int = 64) -> str:
    """Generate a base64-encoded random key (like Azure storage keys)."""
    raw_bytes = secrets.token_bytes(length)
    return base64.b64encode(raw_bytes).decode("utf-8")


def generate_uuid() -> str:
    """Generate a random UUID."""
    return str(uuid.uuid4())


def generate_uuid_secret() -> str:
    """Generate a UUID-like secret (Azure SP format)."""
    return f"{generate_uuid()}".replace("-", "")[:32] + "=="


def generate_password(length: int = 24) -> str:
    """Generate a random password."""
    chars = string.ascii_letters + string.digits + "!@#$%^&*"
    return "".join(secrets.choice(chars) for _ in range(length))


def generate_hex(length: int = 32) -> str:
    """Generate random hex string."""
    return secrets.token_hex(length // 2)


def generate_api_key(prefix: str = "", length: int = 32) -> str:
    """Generate an API key."""
    key = secrets.token_urlsafe(length)[:length]
    return f"{prefix}{key}" if prefix else key


def generate_sas_token(account_name: str = None, account_key: str = None) -> str:
    """Generate a valid SAS token using the Azure SDK.

    Uses the storage account key to compute a cryptographically valid signature
    that will be accepted by Azurite.
    """
    # Default to Azurite's well-known key if not provided
    if account_name is None:
        account_name = os.getenv("STORAGE_ACCOUNT_NAME", "proddata001")
    if account_key is None:
        account_key = os.getenv("STORAGE_ACCOUNT_KEY", AZURITE_WELL_KNOWN_KEY)

    expiry = datetime.now(UTC) + timedelta(days=365)

    sas_token = generate_account_sas(
        account_name=account_name,
        account_key=account_key,
        resource_types=ResourceTypes(service=True, container=True, object=True),
        permission=AccountSasPermissions(read=True, write=True, delete=True, list=True, add=True, create=True),
        expiry=expiry,
    )
    return sas_token


def generate_oauth_token(
    issuer: str = "https://login.microsoftonline.com/fake-tenant-id/v2.0",
    audience: str = "https://management.azure.com",
    subject: str = None,
    expires_in: int = 3600,
) -> str:
    """Generate a fake but structurally valid Azure AD OAuth token (JWT).

    Creates a JWT with realistic Azure AD claims. The signature is fake
    but the structure matches what Azure AD returns for managed identity tokens.
    """
    now = int(time.time())
    tenant_id = str(uuid.uuid4())
    object_id = str(uuid.uuid4())

    # JWT Header
    header = {"typ": "JWT", "alg": "RS256", "kid": generate_hex(20)}

    # JWT Payload with Azure AD claims
    payload = {
        "aud": audience,
        "iss": issuer,
        "iat": now,
        "nbf": now,
        "exp": now + expires_in,
        "aio": generate_hex(43),  # Azure internal claim
        "appid": str(uuid.uuid4()),
        "appidacr": "2",
        "idp": issuer,
        "oid": object_id,
        "rh": generate_hex(24),
        "sub": subject or object_id,
        "tid": tenant_id,
        "uti": generate_hex(11),
        "ver": "2.0",
        "xms_mirid": f"/subscriptions/{uuid.uuid4()}/resourcegroups/rg-prod/providers/Microsoft.Web/sites/app-service",
    }

    # Base64url encode (no padding)
    def b64url(data: dict) -> str:
        json_bytes = json.dumps(data, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(json_bytes).rstrip(b"=").decode()

    header_b64 = b64url(header)
    payload_b64 = b64url(payload)
    # Fake signature (256 bytes like RS256)
    signature_b64 = base64.urlsafe_b64encode(secrets.token_bytes(256)).rstrip(b"=").decode()

    return f"{header_b64}.{payload_b64}.{signature_b64}"


def generate_value(placeholder_def: dict) -> str:
    """Generate a value based on placeholder definition."""
    ptype = placeholder_def.get("type", "random_hex")

    if ptype == "static":
        # Return the static value as-is
        return placeholder_def.get("value", "")
    elif ptype == "base64":
        length = placeholder_def.get("length", 64)
        return generate_base64_key(length)
    elif ptype == "uuid":
        return generate_uuid()
    elif ptype == "uuid_secret":
        return generate_uuid_secret()
    elif ptype == "password":
        length = placeholder_def.get("length", 24)
        return generate_password(length)
    elif ptype == "random_hex":
        length = placeholder_def.get("length", 32)
        return generate_hex(length)
    elif ptype == "api_key":
        prefix = placeholder_def.get("prefix", "")
        length = placeholder_def.get("length", 32)
        return generate_api_key(prefix, length)
    elif ptype == "sas_token":
        return generate_sas_token()
    elif ptype == "oauth_token":
        # Generate Azure AD-style OAuth token (JWT)
        issuer = placeholder_def.get("issuer", "https://login.microsoftonline.com/fake-tenant-id/v2.0")
        audience = placeholder_def.get("audience", "https://management.azure.com")
        expires_in = placeholder_def.get("expires_in", 3600)
        return generate_oauth_token(issuer=issuer, audience=audience, expires_in=expires_in)
    elif ptype == "connection_string":
        # Connection strings may have nested placeholders
        return placeholder_def.get("format", "")
    else:
        return generate_hex(32)


# =============================================================================
# Template Processing
# =============================================================================


def load_template(path: str = "/app/seed_manifest.template.yaml") -> dict:
    """Load seed manifest template."""
    with open(path) as f:
        return yaml.safe_load(f)


def generate_all_values(template: dict) -> dict:
    """Generate values for all placeholders defined in template."""
    values = {}
    definitions = template.get("placeholder_definitions", {})

    # First pass: generate basic values
    for name, definition in definitions.items():
        values[name] = generate_value(definition)

    # Second pass: resolve nested references in connection strings
    for name, definition in definitions.items():
        if definition.get("type") == "connection_string":
            fmt = definition.get("format", "")
            for ref_name, ref_value in values.items():
                fmt = fmt.replace("{{ " + ref_name + " }}", ref_value)
            values[name] = fmt

    return values


def resolve_placeholders(template: dict, values: dict) -> dict:
    """Replace all {{ PLACEHOLDER }} patterns with generated values."""
    # Convert to string for regex replacement
    template_str = yaml.dump(template)

    # Replace each placeholder
    for name, value in values.items():
        pattern = r"\{\{\s*" + re.escape(name) + r"\s*\}\}"
        template_str = re.sub(pattern, value, template_str)

    # Parse back to dict
    resolved = yaml.safe_load(template_str)

    # Remove placeholder_definitions from output (not needed for seeding)
    if "placeholder_definitions" in resolved:
        del resolved["placeholder_definitions"]

    return resolved


def load_and_resolve_template(template_path: str = "/app/seed_manifest.template.yaml") -> dict:
    """Load template and resolve all placeholders."""
    template = load_template(template_path)
    values = generate_all_values(template)

    print("Generated values:")
    for name in values:
        # Show first 20 chars of each value
        preview = values[name][:20] + "..." if len(values[name]) > 20 else values[name]
        print(f"  {name}: {preview}")

    resolved = resolve_placeholders(template, values)

    # Write resolved manifest to output if directory is mounted
    output_path = os.getenv("RESOLVED_MANIFEST_PATH", "/app/output/seed_manifest.yaml")
    output_dir = os.path.dirname(output_path)
    if os.path.exists(output_dir) and os.path.isdir(output_dir):
        try:
            with open(output_path, "w") as f:
                yaml.dump(resolved, f, default_flow_style=False, sort_keys=False)
            print(f"  Wrote resolved manifest to: {output_path}")
        except Exception as e:
            print(f"  WARNING: Could not write resolved manifest: {e}")

    return resolved, values


# =============================================================================
# Base Infrastructure Generation
# =============================================================================


def load_base_infra_template(path: str = "/app/base_infrastructure.template.yaml") -> dict:
    """Load base infrastructure template."""
    try:
        with open(path) as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        return {}


def generate_base_infrastructure(values: dict) -> dict:
    """Generate base_infrastructure with real values from template.

    Uses the same {{ PLACEHOLDER }} pattern as seed_manifest.template.yaml.
    """
    template = load_base_infra_template()

    if not template:
        # Fallback: minimal config with Azurite's well-known key
        return {
            "storage_accounts": [{"name": "proddata001", "keys": [{"name": "key1", "value": AZURITE_WELL_KNOWN_KEY}]}],
            "mock_service_defaults": {
                "connection_strings": {
                    "storage": f"DefaultEndpointsProtocol=https;AccountName=proddata001;AccountKey={AZURITE_WELL_KNOWN_KEY};EndpointSuffix=core.windows.net"
                }
            },
        }

    # Use the same template processing as seed_manifest
    base_values = generate_all_values(template)
    resolved = resolve_placeholders(template, base_values)

    print("  Generated base infrastructure")
    return resolved


# =============================================================================
# Service Seeding
# =============================================================================


def get_storage_key(base_infra: dict, account_name: str = "proddata001") -> str:
    """Get storage account key from base infrastructure."""
    for storage in base_infra.get("storage_accounts", []):
        if storage.get("name") == account_name:
            keys = storage.get("keys", [])
            if keys:
                return keys[0].get("value", "")
    defaults = base_infra.get("mock_service_defaults", {})
    conn_str = defaults.get("connection_strings", {}).get("storage", "")
    if "AccountKey=" in conn_str:
        for part in conn_str.split(";"):
            if part.startswith("AccountKey="):
                return part.split("=", 1)[1]
    return ""


def _get_blob_auth_header(
    method: str, url: str, headers: dict, account_name: str, key: str, content_length: int = 0
) -> str:
    """Generate Azure Blob Storage SharedKey authorization header."""
    parsed = urlparse(url)
    x_ms_headers = sorted([(k.lower(), v) for k, v in headers.items() if k.lower().startswith("x-ms-")])
    canonicalized_headers = "\n".join([f"{k}:{v}" for k, v in x_ms_headers])
    path = parsed.path
    canonicalized_resource = f"/{account_name}{path}"
    if parsed.query:
        params = sorted([p.split("=") for p in parsed.query.split("&")])
        for param in params:
            if len(param) == 2:
                canonicalized_resource += f"\n{param[0]}:{param[1]}"
    content_type = headers.get("Content-Type", "")
    string_to_sign = f"{method}\n\n\n{content_length if content_length else ''}\n\n{content_type}\n\n\n\n\n\n\n{canonicalized_headers}\n{canonicalized_resource}"
    key_bytes = base64.b64decode(key)
    signature = base64.b64encode(hmac.new(key_bytes, string_to_sign.encode("utf-8"), hashlib.sha256).digest()).decode(
        "utf-8"
    )
    return f"SharedKey {account_name}:{signature}"


def _get_keyvault_token() -> str:
    """Get token from IMDS for KeyVault access."""
    imds_host = os.getenv("IMDS_HOST", "imds")
    try:
        resp = requests.get(
            f"http://{imds_host}:80/metadata/identity/oauth2/token",
            params={"api-version": "2019-08-01", "resource": "https://vault.azure.net"},
            headers={"Metadata": "true"},
            timeout=5,
        )
        return resp.json().get("access_token", "")
    except Exception:
        return ""


def wait_for_services(timeout: int = 120):
    """Wait for services to be healthy."""
    endpoints = [
        (os.getenv("AZURITE_HOST", "azurite"), 10000, "Azurite"),
        (os.getenv("AZURE_AD_HOST", "azure-ad"), 8080, "Azure AD"),
        (os.getenv("KEYVAULT_HOST", "keyvault"), 443, "KeyVault"),
        (os.getenv("IMDS_HOST", "imds"), 80, "IMDS"),
    ]

    print("Waiting for services...")
    start = time.time()

    for host, port, name in endpoints:
        url = f"http://{host}:{port}/health" if port != 443 else f"https://{host}:{port}/health"
        if port == 10000:
            url = f"http://{host}:{port}"

        while time.time() - start < timeout:
            try:
                requests.get(url, timeout=2, verify=False)
                print(f"  [OK] {name}")
                break
            except Exception:
                time.sleep(2)
        else:
            print(f"  [TIMEOUT] {name}")


def seed_blob_storage(containers: list, base_infra: dict, account_name: str = "proddata001", label: str = ""):
    """Seed blob storage containers and files.

    Args:
        containers: List of container dicts with 'name', 'files' keys
        base_infra: Base infrastructure config (for storage key lookup)
        account_name: Storage account name (default: proddata001)
        label: Optional label for log messages (e.g., "Benign" for base infra)
    """
    key = get_storage_key(base_infra, account_name)
    if not key:
        print(f"  [SKIP] No storage key for {account_name}")
        return

    host = os.getenv("AZURITE_HOST", "azurite")
    base_url = f"http://{host}:10000/{account_name}"
    prefix = f"{label} " if label else ""

    for container_info in containers:
        container_name = container_info.get("name")
        if not container_name:
            continue

        # Create container
        url = f"{base_url}/{container_name}?restype=container"
        date_str = datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S GMT")
        headers = {"x-ms-version": "2021-06-08", "x-ms-date": date_str}
        headers["Authorization"] = _get_blob_auth_header("PUT", url, headers, account_name, key)

        try:
            resp = requests.put(url, headers=headers)
            if resp.status_code in (201, 409):
                print(f"  [OK] {prefix}Container: {container_name}")
            else:
                print(f"  [FAIL] Container {container_name}: HTTP {resp.status_code}")
                continue
        except Exception as e:
            print(f"  [FAIL] Container {container_name}: {e}")
            continue

        # Upload files
        for file_info in container_info.get("files", []):
            file_name = file_info.get("name")
            content = file_info.get("content", "")
            if isinstance(content, str):
                content = content.encode("utf-8")

            blob_url = f"{base_url}/{container_name}/{file_name}"
            date_str = datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S GMT")
            headers = {
                "x-ms-version": "2021-06-08",
                "x-ms-date": date_str,
                "x-ms-blob-type": "BlockBlob",
                "Content-Type": "text/plain",
            }
            headers["Authorization"] = _get_blob_auth_header("PUT", blob_url, headers, account_name, key, len(content))

            try:
                resp = requests.put(blob_url, data=content, headers=headers)
                if resp.status_code == 201:
                    print(f"    [OK] File: {file_name}")
                else:
                    print(f"    [FAIL] File {file_name}: HTTP {resp.status_code}")
            except Exception as e:
                print(f"    [FAIL] File {file_name}: {e}")


def seed_keyvault(secrets: list, label: str = ""):
    """Seed KeyVault secrets.

    Args:
        secrets: List of secret dicts with 'name', 'value' keys
        label: Optional label for log messages (e.g., "Benign" for base infra)
    """
    host = os.getenv("KEYVAULT_HOST", "keyvault")
    base_url = f"https://{host}:443"
    token = _get_keyvault_token()
    prefix = f"{label} " if label else ""

    for secret in secrets:
        secret_name = secret.get("name")
        secret_value = secret.get("value", "")

        url = f"{base_url}/secrets/{secret_name}?api-version=7.4"
        try:
            resp = requests.put(
                url,
                json={"value": secret_value},
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
                verify=False,
            )
            if resp.status_code in (200, 201):
                print(f"  [OK] {prefix}Secret: {secret_name}")
            else:
                print(f"  [FAIL] Secret {secret_name}: HTTP {resp.status_code}")
        except Exception as e:
            print(f"  [FAIL] Secret {secret_name}: {e}")


def seed_keyvault_tokens(imds_config: dict):
    """Inject valid tokens into KeyVault so it accepts them for secret operations.

    KeyVault validates Bearer tokens against an injected list. This injects the
    IMDS tokens so that seed_keyvault() can use them to PUT secrets.
    """
    host = os.getenv("KEYVAULT_HOST", "keyvault")
    base_url = f"https://{host}:443"

    exposed_tokens = imds_config.get("exposed_tokens", {})
    if not exposed_tokens:
        print("  [SKIP] No IMDS tokens to inject")
        return

    tokens = list(exposed_tokens.values())
    try:
        resp = requests.post(
            f"{base_url}/admin/tokens",
            json={"tokens": tokens},
            verify=False,
            timeout=5,
        )
        if resp.status_code == 200:
            print(f"  [OK] KeyVault tokens: {len(tokens)} valid token(s)")
        else:
            print(f"  [FAIL] KeyVault tokens: HTTP {resp.status_code}")
    except Exception as e:
        print(f"  [FAIL] KeyVault tokens: {e}")


def seed_azure_ad(service_principals: list, label: str = ""):
    """Seed Azure AD service principals.

    Args:
        service_principals: List of SP dicts with 'name'/'app_id', 'client_secret' keys
        label: Optional label for log messages (e.g., "Benign" for base infra)
    """
    host = os.getenv("AZURE_AD_HOST", "azure-ad")
    base_url = f"http://{host}:8080"
    prefix = f"{label} " if label else ""

    for sp in service_principals:
        # Support both formats: dict with name/app_id or client_id
        sp_name = sp.get("name") or sp.get("display_name") or sp.get("app_id", "unknown")
        sp_entry = {
            "app_id": sp.get("app_id") or sp.get("client_id", sp_name),
            "display_name": sp.get("display_name") or sp.get("name", sp_name),
            "description": sp.get("description", ""),
            "credentials": [{"type": "secret", "value": sp.get("client_secret", "")}],
        }
        try:
            resp = requests.post(f"{base_url}/admin/service-principals", json=sp_entry, timeout=5)
            if resp.status_code == 200:
                print(f"  [OK] {prefix}SP: {sp_name}")
            else:
                print(f"  [FAIL] SP {sp_name}: HTTP {resp.status_code}")
        except Exception as e:
            print(f"  [FAIL] SP {sp_name}: {e}")


def seed_app_service(config: dict):
    """Seed App Service environment variables."""
    host = os.getenv("APP_SERVICE_HOST", "app-service")
    base_url = f"http://{host}:8080"

    # Inject environment variables (vulnerable endpoint is hardcoded to /_next/rsc)
    for var_name, var_value in config.get("env_vars", {}).items():
        try:
            requests.post(f"{base_url}/admin/env", json={var_name: var_value}, timeout=5)
            print(f"    [OK] Env: {var_name}")
        except Exception:
            pass


def seed_imds(config: dict):
    """Seed IMDS with custom tokens.

    Config structure:
        exposed_tokens:
            managed_identity: "eyJ..."  # Token returned for all resources
            https://management.azure.com/: "eyJ..."  # Resource-specific token
    """
    host = os.getenv("IMDS_HOST", "imds")
    base_url = f"http://{host}:80"

    exposed_tokens = config.get("exposed_tokens", {})
    if not exposed_tokens:
        return

    # Convert exposed_tokens to the format IMDS expects
    tokens = {}
    for token_name, token_value in exposed_tokens.items():
        # Handle both "managed_identity" style and URL-style keys
        tokens[token_name] = token_value

    try:
        resp = requests.post(
            f"{base_url}/admin/tokens",
            json={"tokens": tokens},
            timeout=5,
        )
        if resp.status_code == 200:
            print(f"  [OK] IMDS: {len(tokens)} token(s) injected")
        else:
            print(f"  [FAIL] IMDS tokens: HTTP {resp.status_code}")
    except Exception as e:
        print(f"  [FAIL] IMDS tokens: {e}")


def seed_arm(imds_config: dict, base_infra: dict):
    """Seed ARM with valid tokens and infrastructure config.

    ARM validates Bearer tokens against injected list, and returns
    infrastructure data for discovery endpoints.
    """
    host = os.getenv("ARM_HOST", "arm")
    base_url = f"https://{host}:443"

    # Inject valid tokens
    exposed_tokens = imds_config.get("exposed_tokens", {})
    if exposed_tokens:
        tokens = list(exposed_tokens.values())
        try:
            resp = requests.post(
                f"{base_url}/admin/tokens",
                json={"tokens": tokens},
                timeout=5,
                verify=False,
            )
            if resp.status_code == 200:
                print(f"  [OK] ARM tokens: {len(tokens)} valid token(s)")
            else:
                print(f"  [FAIL] ARM tokens: HTTP {resp.status_code}")
        except Exception as e:
            print(f"  [FAIL] ARM tokens: {e}")

    # Inject infrastructure config for discovery
    if base_infra:
        # Extract only the fields ARM needs for discovery
        arm_config = {
            "subscription": base_infra.get("subscription", {}),
            "resource_groups": base_infra.get("resource_groups", []),
            "storage_accounts": [
                {"name": sa["name"], "resource_group": sa["resource_group"], "location": sa["location"]}
                for sa in base_infra.get("storage_accounts", [])
            ],
            "key_vaults": [
                {"name": kv["name"], "resource_group": kv["resource_group"], "location": kv["location"]}
                for kv in base_infra.get("key_vaults", [])
            ],
            "function_apps": [
                {"name": fa["name"], "resource_group": fa["resource_group"]}
                for fa in base_infra.get("function_apps", [])
            ],
            "app_services": [
                {"name": app["name"], "resource_group": app["resource_group"]}
                for app in base_infra.get("app_services", [])
            ],
        }
        try:
            resp = requests.post(
                f"{base_url}/admin/config",
                json=arm_config,
                timeout=5,
                verify=False,
            )
            if resp.status_code == 200:
                print(
                    f"  [OK] ARM config: {len(arm_config['storage_accounts'])} storage, "
                    f"{len(arm_config['key_vaults'])} vaults, {len(arm_config['app_services'])} apps"
                )
            else:
                print(f"  [FAIL] ARM config: HTTP {resp.status_code}")
        except Exception as e:
            print(f"  [FAIL] ARM config: {e}")


def seed_functions(imds_config: dict):
    """Seed Azure Functions with valid tokens.

    Functions validates Bearer tokens against injected list.
    This allows attackers with stolen IMDS tokens to access Functions.
    """
    host = os.getenv("FUNCTIONS_HOST", "azure-functions")
    base_url = f"http://{host}:7071"

    # Inject valid tokens
    exposed_tokens = imds_config.get("exposed_tokens", {})
    if exposed_tokens:
        tokens = list(exposed_tokens.values())
        try:
            resp = requests.post(
                f"{base_url}/admin/tokens",
                json={"tokens": tokens},
                timeout=5,
            )
            if resp.status_code == 200:
                print(f"  [OK] Functions tokens: {len(tokens)} valid token(s)")
            else:
                print(f"  [FAIL] Functions tokens: HTTP {resp.status_code}")
        except Exception as e:
            print(f"  [FAIL] Functions tokens: {e}")


def seed_domain_controller(dc_config: dict):
    """Seed domain controller with users, groups, SPNs."""
    if not dc_config:
        return

    host = os.getenv("DC_HOST", "domain-controller")
    base_url = f"http://{host}:8080"

    try:
        resp = requests.post(f"{base_url}/admin/config", json=dc_config, timeout=10)
        if resp.status_code == 200:
            users = len(dc_config.get("users", []))
            groups = len(dc_config.get("groups", []))
            spns = len(dc_config.get("service_principal_names", []))
            print(f"  [OK] Domain Controller: {users} users, {groups} groups, {spns} SPNs")
        else:
            print(f"  [FAIL] Domain Controller: HTTP {resp.status_code}")
    except Exception as e:
        print(f"  [FAIL] Domain Controller: {e}")


# =============================================================================
# Main (for init container)
# =============================================================================


def main():
    """Main seeding entry point."""
    print("=" * 60)
    print("SABER-SIM Init Seed Container")
    print("=" * 60)

    # Check for template vs resolved manifest
    template_path = "/app/seed_manifest.template.yaml"
    manifest_path = "/app/seed_manifest.yaml"

    if os.path.exists(template_path):
        print("\nProcessing template...")
        manifest, values = load_and_resolve_template(template_path)
        base_infra = generate_base_infrastructure(values)
    elif os.path.exists(manifest_path):
        print("\nLoading pre-resolved manifest...")
        with open(manifest_path) as f:
            manifest = yaml.safe_load(f)
        base_infra = {}
        if os.path.exists("/app/base_infrastructure.yaml"):
            with open("/app/base_infrastructure.yaml") as f:
                base_infra = yaml.safe_load(f)
    else:
        print("ERROR: No seed_manifest.template.yaml or seed_manifest.yaml found!")
        return

    services = manifest.get("services", {})

    # Wait for services
    wait_for_services()

    print("\nSeeding scenario data...")

    # CRITICAL: Seed IMDS first so tokens are available for other services
    imds_config = services.get("azure-imds", {})
    if imds_config:
        print("\n[IMDS]")
        seed_imds(imds_config)

    # Inject IMDS tokens into KeyVault so it accepts them
    if imds_config and "azure-keyvault" in services:
        print("\n[KeyVault Token Injection]")
        seed_keyvault_tokens(imds_config)

    # Seed scenario blob storage (convert dict to list format)
    if "azure-blob-storage" in services:
        print("\n[Blob Storage]")
        containers_dict = services["azure-blob-storage"].get("containers", {})
        containers_list = [{"name": k, **v} for k, v in containers_dict.items()]
        seed_blob_storage(containers_list, base_infra)

    # Seed scenario keyvault secrets (convert dict to list format)
    if "azure-keyvault" in services:
        print("\n[KeyVault Secrets]")
        secrets_dict = services["azure-keyvault"].get("secrets", {})
        secrets_list = [{"name": k, **v} for k, v in secrets_dict.items()]
        seed_keyvault(secrets_list)

    # Seed scenario service principals (convert dict to list format)
    if "azure-ad" in services:
        print("\n[Azure AD]")
        sps_dict = services["azure-ad"].get("service_principals", {})
        sps_list = [{"name": k, **v} for k, v in sps_dict.items()]
        seed_azure_ad(sps_list)

    if "azure-app-service" in services:
        print("\n[App Service]")
        seed_app_service(services["azure-app-service"])

    if "azure-arm" in services:
        print("\n[ARM]")
        imds_config = services.get("azure-imds", {})
        seed_arm(imds_config, base_infra)

    if "azure-functions" in services:
        print("\n[Functions]")
        imds_config = services.get("azure-imds", {})
        seed_functions(imds_config)

    # Seed base infrastructure (benign baseline data)
    if base_infra:
        print("\n" + "-" * 40)
        print("Seeding base infrastructure...")

        # Seed benign blob containers from each storage account
        for storage_account in base_infra.get("storage_accounts", []):
            benign_containers = storage_account.get("benign_containers", [])
            if benign_containers:
                account_name = storage_account.get("name", "proddata001")
                print(f"\n[Base Blob: {account_name}]")
                seed_blob_storage(benign_containers, base_infra, account_name, "Benign")

        # Seed benign keyvault secrets from each vault
        for kv in base_infra.get("key_vaults", []):
            benign_secrets = kv.get("benign_secrets", [])
            if benign_secrets:
                print(f"\n[Base KeyVault: {kv.get('name')}]")
                seed_keyvault(benign_secrets, "Benign")

        # Seed benign service principals
        benign_sps = base_infra.get("benign_service_principals", [])
        if benign_sps:
            print("\n[Base Service Principals]")
            seed_azure_ad(benign_sps, "Benign")

        # Seed domain controller
        dc_config = base_infra.get("domain_controller", {})
        if dc_config:
            print("\n[Domain Controller]")
            seed_domain_controller(dc_config)

    print("\n" + "=" * 60)
    print("Seeding complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
