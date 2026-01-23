# React2Shell Cyber Range

## Scenario Overview

**CVE-2025-55182 (React2Shell)** is a pre-authentication remote code execution vulnerability in React Server Components. This cyber range simulates an end-to-end attack chain where an adversary exploits this vulnerability to compromise Azure cloud infrastructure and exfiltrate sensitive data.

| Attribute | Value |
|-----------|-------|
| Difficulty | Intermediate |
| Duration | 2-4 hours |
| Focus Areas | Cloud Security, Threat Hunting, Azure Log Analysis |
| MITRE ATT&CK Coverage | Initial Access, Execution, Credential Access, Discovery, Privilege Escalation, Lateral Movement, Collection, Exfiltration |

## Attack Narrative

A threat actor discovers a public-facing Next.js application running React 19 with Server Components. They exploit CVE-2025-55182 by sending a malicious Flight protocol payload to achieve remote code execution on the Azure App Service.

Once inside, the attacker pivots to the Azure Instance Metadata Service (IMDS) to steal the application's Managed Identity token. This token grants access to multiple Azure services including Key Vault, ARM API, and Azure Functions.

The attacker uses the stolen token to directly access Key Vault and extract a storage SAS token. The attack culminates in data exfiltration: the attacker uses the SAS token to access a sensitive blob container and downloads customer PII.

## Infrastructure

```
┌─────────────────────────────────────────────────────────────────────┐
│                          ATTACK CHAIN                               │
│                                                                     │
│   ATTACKER                                                          │
│       │                                                             │
│       ▼                                                             │
│  ┌──────────┐   CVE-2025-55182    ┌──────────────┐                 │
│  │  Front   │ ─────────────────►  │  App Service │  (RCE)          │
│  │   Door   │   POST /_next/rsc   │  [Next.js]   │                 │
│  └──────────┘                     └──────┬───────┘                 │
│                                          │                          │
│                                          ▼                          │
│                                   ┌──────────────┐                 │
│                                   │     IMDS     │                 │
│                                   │169.254.169.254                 │
│                                   └──────┬───────┘                 │
│                                          │                          │
│                                          │ Managed Identity Token   │
│                                          │                          │
│                          ┌───────────────┼───────────────┐         │
│                          ▼               ▼               ▼         │
│                    ┌──────────┐   ┌──────────┐   ┌──────────┐     │
│                    │   ARM    │   │ KeyVault │   │Functions │     │
│                    │   API    │   │          │   │          │     │
│                    └──────────┘   └────┬─────┘   └──────────┘     │
│                          │             │               │           │
│                          │             │               │           │
│                    Enumeration    SAS Token      Credentials       │
│                                        │                           │
│                                        ▼                           │
│                                 ┌──────────────┐                   │
│                                 │ Blob Storage │                   │
│                                 │ sensitive-   │                   │
│                                 │    data/     │                   │
│                                 └──────┬───────┘                   │
│                                        │                           │
│                                        ▼                           │
│                                   EXFILTRATION                     │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Services

| Service | Role | Network |
|---------|------|---------|
| Front Door | WAF / Reverse Proxy (entry point) | DMZ |
| App Service | Vulnerable Next.js application | DMZ, Corp, Mgmt |
| IMDS | Managed Identity token provider | Mgmt |
| Azure AD | OAuth2 authentication | Mgmt |
| ARM API | Resource Manager (discovery) | Mgmt |
| Key Vault | Secret storage (SAS token) | Corp |
| Azure Functions | Serverless compute (lateral movement) | Corp, Mgmt |
| Blob Storage | Data storage (exfiltration target) | Corp |
| Azure Sentinel | SIEM / Log aggregation | Mgmt |

## Attack Steps

### Step 1: Initial Access (T1190)

The attacker sends a crafted POST request to the React Server Components Flight endpoint, triggering prototype pollution that leads to RCE.

```http
POST /_next/rsc HTTP/1.1
Host: target.azurewebsites.net
Content-Type: application/json

{"__proto__": {"polluted": true}}
```

The response leaks environment variables and reveals an `/exec` endpoint for command execution.

### Step 2: Credential Access (T1552.005)

From the compromised App Service, the attacker uses the `/exec` endpoint to query IMDS and obtain the Managed Identity OAuth token.

```http
GET /metadata/identity/oauth2/token?api-version=2018-02-01&resource=https://management.azure.com/
Host: 169.254.169.254
Metadata: true
```

The returned token grants access to ARM API, Key Vault, and Azure Functions.

### Step 3: Discovery & Lateral Movement (T1526, T1078.004)

Using the stolen token, the attacker can:

**ARM API Enumeration:**
- List subscriptions and resource groups
- Discover storage accounts and key vaults
- Find web apps and function apps

**Azure Functions Access:**
- List available functions
- Extract master key via `/admin/host/keys`
- Leak connection strings from `/api/vfs/local.settings.json`

### Step 4: Key Vault Access (T1552.004)

The attacker uses the Managed Identity token to directly access Key Vault and retrieve a storage SAS token. The Key Vault has an over-permissive access policy that allows the App Service's Managed Identity to read secrets.

```http
GET /secrets/storage-sas-token
Host: prod-secrets-kv.vault.azure.net
Authorization: Bearer <managed_identity_token>
```

### Step 5: Data Exfiltration (T1530)

The attacker uses the SAS token to access the sensitive blob container and download customer data.

```http
GET /proddata001/sensitive-data/customer-data.json?<sas_token>
Host: proddata001.blob.core.windows.net
```

## Benign Activity & Baseline Data

To create a realistic threat hunting environment, the scenario seeds benign data alongside attack artifacts. Threat hunters must distinguish malicious activity from normal operations.

### Baseline Infrastructure

| Category | Benign Data | Attack Data |
|----------|-------------|-------------|
| Blob Containers | `public-assets/`, `app-logs/` | `sensitive-data/` |
| Key Vault Secrets | `app-insights-instrumentation-key`, `redis-connection-dev`, 2 others | `storage-sas-token` |
| Service Principals | 18 benign application identities | App Service Managed Identity |

### Historical Logs

At startup, the scenario generates **48 hours of historical logs** representing normal business operations:

- Routine Azure AD sign-ins from legitimate users
- Regular blob storage access patterns
- Scheduled function executions
- Standard ARM API calls for deployments

This baseline provides context for anomaly detection—attack activity should stand out against the background of normal operations.

## Service Endpoints

| Service | URL |
|---------|-----|
| Front Door (Entry) | http://localhost:8086 |
| App Service | http://localhost:8085 |
| Azure AD | http://localhost:8081 |
| IMDS | http://localhost:8080 |
| Key Vault | https://localhost:8200 |
| ARM API | https://localhost:8445 |
| Azure Functions | http://localhost:7071 |
| Blob Storage | http://localhost:10000 |
| Azure Sentinel | http://localhost:5000 |

## References

- [CVE-2025-55182 - React Server Components RCE](https://www.microsoft.com/en-us/security/blog/2025/12/15/defending-against-the-cve-2025-55182-react2shell-vulnerability-in-react-server-components/)
- [MITRE ATT&CK Cloud Matrix](https://attack.mitre.org/matrices/enterprise/cloud/)
- [Azure Instance Metadata Service](https://docs.microsoft.com/en-us/azure/virtual-machines/windows/instance-metadata-service)

---

*Generated by SABER-SIM (Security Attack Behavior Extraction & Replay Simulator)*
