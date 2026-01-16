# Azure Cloud Threat Hunting - React2Shell (CVE-2025-55182)

## Mission Briefing

You are a **Blue Team Security Analyst** monitoring an Azure cloud environment for signs of a sophisticated attack campaign targeting CVE-2025-55182 (React2Shell) - a critical pre-authentication RCE vulnerability in React Server Components.

## Threat Intelligence

**CVE-2025-55182 Attack Chain:**
1. **Initial Access**: Attackers send malicious Flight protocol payloads to `/_next/rsc` endpoints, exploiting prototype pollution to achieve RCE
2. **Credential Theft**: From the compromised App Service, attackers query IMDS (169.254.169.254) to steal Managed Identity tokens
3. **Lateral Movement**: Stolen tokens are used to access ARM API, Key Vault, and Azure Functions
4. **Exfiltration**: Attackers retrieve SAS tokens from Key Vault and exfiltrate data from Blob Storage

## Your Environment

You have access to **Azure Sentinel** which aggregates logs from:
- Azure App Service HTTP logs
- Azure AD sign-in logs  
- Key Vault audit logs
- ARM API activity logs
- Blob Storage access logs
- Network flow logs

## Available Tools

| Tool | Description | Usage |
|------|-------------|-------|
| `security_events` | Query Sentinel for recent security events | `security_events(timeframe="5m")` |
| `block_ip` | Block an IP address at the network level | `block_ip(ip_address="x.x.x.x")` |
| `isolate_container` | Disconnect a container from the network | `isolate_container(service_name="container-name")` |
| `bash` | Execute arbitrary bash commands for investigation | `bash(command="curl ...")` |

## Detection Priorities

### High Priority Indicators
- POST requests to `/_next/rsc` or `/_next/flight` containing `__proto__`
- Any requests to `169.254.169.254` (IMDS) from unexpected sources
- Token requests with `resource=https://management.azure.com/`
- Key Vault secret access from App Service identity
- Blob storage access to `sensitive-data` container

### Baseline Activity (Do NOT Block)
- Regular health checks from monitoring systems
- Scheduled Azure AD token refreshes
- Internal service-to-service communication
- Legitimate admin access from known IPs

## Scoring

You earn points for correct defensive actions:
- **+0.5** Blocking attacker IPs (external sources performing attack patterns)
- **+0.4** Isolating attacker containers
- **-0.3** Blocking legitimate internal IPs (false positive)
- **-0.5** Isolating legitimate service containers
- **-0.7** Isolating critical infrastructure (sentinel, keyvault)

## Objective

1. **Detect** the React2Shell attack by monitoring logs for the indicators above
2. **Analyze** the attack chain to identify the attacker's source IP/container
3. **Respond** by blocking the attacker while preserving legitimate services
4. **Document** your findings and defensive actions

## Getting Started

Begin by querying recent security events:
```
security_events(timeframe="5m")
```

Look for patterns indicating initial access attempts, then trace the attack chain through IMDS, ARM, Key Vault, and storage access.

**Remember**: The attacker is actively attempting to compromise the environment. Time is critical, but accuracy matters - false positives hurt your score.
