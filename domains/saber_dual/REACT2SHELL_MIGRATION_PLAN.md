# React2Shell Migration for SABER Dual

## Goal

Integrate **react2shell** (CVE-2025-55182 Azure cloud attack simulation) into **saber_dual** domain alongside **lite_dual**.

---

## Current Status (2026-01-15)

### ✅ Completed

1. **Phase 1: Image Registration** - All 12 react2shell images in [domain.yaml](domain.yaml):
   - azure-ad, imds, azurite, keyvault, arm-api, app-service, front-door, functions, sentinel, init-seed

2. **Phase 2: Blue Team Compose** - [react2shell_blue_team_sandbox.compose.yml](server/config/environments/sandbox/react2shell_blue_team_sandbox.compose.yml):
   - All services have `${EPISODE_ID}` substitution for episode isolation
   - Proper SABER labels (`saber.execution.service`, `saber.domain`, `saber.scenario`)
   - Init-seed uses HTTP seeding (no shared volumes needed)
   - Network stub for local validation (ComposeOrchestrator injects `saber-episode-network` at runtime)

3. **Images Built**:
   ```bash
   uv run saber-domain build saber_dual --rebuild react2shell
   ```

4. **Services Validated Healthy** (8/10):
   - ✅ azure-ad, imds, azurite, keyvault, arm-api, app-service, front-door, functions
   - ✅ init-seed (seeds all services via HTTP, exits successfully)
   - ⏳ kusto-emulator (requires x64 - `linux/amd64` only image)
   - ⏳ sentinel (blocked on kusto)

### ⏳ In Progress

**Kusto Emulator** - `mcr.microsoft.com/azuredataexplorer/kustainer-linux:latest` is x64-only. Compose file has `platform: linux/amd64` for QEMU emulation on ARM, but it's too slow. **Moving to x64 machine to continue.**

### 🔲 Remaining

| Phase | Description |
|-------|-------------|
| Kusto + Sentinel | Validate on x64 machine |
| Red Team Compose | `react2shell_red_team_sandbox.compose.yml` |
| Task Definition | `server/config/tasks/react2shell/react2shell.yaml` |
| Prompts | Blue/red team instruction prompts |
| Scoring | Azure-specific attack indicators in `constants.py` |

---

## Key Architecture Notes

- **Init-seed pattern**: Services seeded via HTTP APIs (POST /admin/config), not file mounts
- **Network**: Single `saber-episode-network` - ComposeOrchestrator auto-injects it
- **Execution container**: `react2shell-sentinel` with `saber.execution.service=true`
- **Kusto dependency**: Sentinel's `app.py` blocks on kusto initialization (30 retries)

---

## Test Commands

```bash
# Build images
uv run saber-domain build saber_dual --rebuild react2shell

# Start environment
cd domains/saber_dual/server/config/environments/sandbox
EPISODE_ID=test001 docker compose -f react2shell_blue_team_sandbox.compose.yml up -d

# Check status
docker ps --filter "name=react2shell" --format "table {{.Names}}\t{{.Status}}"

# Cleanup
EPISODE_ID=test001 docker compose -f react2shell_blue_team_sandbox.compose.yml down
```
