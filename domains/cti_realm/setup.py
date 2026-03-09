"""CTI Realm domain setup hooks.

Provides a ``DownloadCTIData`` hook that downloads CTI Realm evaluation
data from Azure Blob Storage if not already present locally.

Data categories:
  1. Kusto telemetry data (JSONL files for Kusto emulator)
  2. CTI reports (reports.jsonl)
  3. Sigma rules (sigma_rules.json)
"""

from __future__ import annotations

from pathlib import Path

from saber.hooks import SetupHook
from saber.logging import get_logger

logger = get_logger("domains.cti_realm.setup")

# ---------------------------------------------------------------------------
# Azure Blob Storage defaults
# ---------------------------------------------------------------------------
_TENANT_ID = "72f988bf-86f1-41af-91ab-2d7cd011db47"
_STORAGE_ACCOUNT = "secbench20258034258673"
_CONTAINER = "cti-realm-data"

# ---------------------------------------------------------------------------
# Local directory layout (relative to domain_root)
# ---------------------------------------------------------------------------
_KUSTO_DATA_DIR = "docker/kusto_init/data"
_CTI_REPORTS_DIR = "data/cti_reports"
_SIGMA_RULES_DIR = "data"

# ---------------------------------------------------------------------------
# Blob source directories
# ---------------------------------------------------------------------------
_KUSTO_BLOB_DIR = "ground_truth_telemetry_data"
_KUSTO_BLOB_DIR_ANONYMIZED = "anonymized"
_CTI_REPORTS_BLOB_DIR = "reports"
_DETECTION_BLOB_DIR = "ground_truth_detection_specific"

# ---------------------------------------------------------------------------
# Kusto telemetry JSONL filenames
# ---------------------------------------------------------------------------
_KUSTO_FILES: tuple[str, ...] = (
    "aadserviceprincipalsigninlogs.jsonl",
    "aksaudit.jsonl",
    "aksauditadmin.jsonl",
    "auditlogs.jsonl",
    "azureactivity.jsonl",
    "azurediagnostics.jsonl",
    "deviceprocessevents.jsonl",
    "devicefileevents.jsonl",
    "microsoftgraphactivitylogs.jsonl",
    "officeactivity.jsonl",
    "signinlogs.jsonl",
    "storageboblogs.jsonl",
)


def download_cti_data(
    domain_root: Path,
    *,
    anonymized: bool = False,
    force_download: bool = False,
) -> None:
    """Download CTI Realm data from Azure Blob Storage.

    Downloads three categories of data:
      1. Kusto telemetry JSONL files
      2. CTI reports (reports.jsonl)
      3. Sigma rules (sigma_rules.json)

    Args:
        domain_root: Path to the CTI Realm domain root directory.
        anonymized: If True, download telemetry from the ``anonymized/``
            blob prefix instead of ``ground_truth_telemetry_data/``.
        force_download: If True, download even if files already exist.

    Raises:
        ImportError: If ``azure-identity`` or ``azure-storage-blob``
            is not installed.
    """
    try:
        from azure.identity import DefaultAzureCredential
    except ImportError as exc:
        raise ImportError(
            "azure-identity is required for CTI Realm data download. "
            "Install with: pip install azure-identity azure-storage-blob"
        ) from exc

    try:
        from azure.storage.blob import BlobServiceClient
    except ImportError as exc:
        raise ImportError(
            "azure-storage-blob is required for CTI Realm data download. "
            "Install with: pip install azure-identity azure-storage-blob"
        ) from exc

    # Authenticate
    logger.info("Authenticating with Azure tenant %s", _TENANT_ID)
    credential = DefaultAzureCredential(
        exclude_shared_token_cache_credential=True,
        additionally_allowed_tenants=[_TENANT_ID],
    )
    account_url = f"https://{_STORAGE_ACCOUNT}.blob.core.windows.net"
    blob_service_client = BlobServiceClient(account_url, credential=credential)
    container_client = blob_service_client.get_container_client(_CONTAINER)

    errors: list[str] = []

    # 1. Kusto telemetry data
    kusto_dir = domain_root / _KUSTO_DATA_DIR
    kusto_blob_prefix = _KUSTO_BLOB_DIR_ANONYMIZED if anonymized else _KUSTO_BLOB_DIR
    kusto_dir.mkdir(parents=True, exist_ok=True)

    logger.info(
        "Downloading Kusto telemetry from %s/ to %s",
        kusto_blob_prefix,
        kusto_dir,
    )
    try:
        for filename in _KUSTO_FILES:
            local_path = kusto_dir / filename
            if not force_download and local_path.exists():
                logger.info("  Skipping %s (already exists)", filename)
                continue
            blob_name = f"{kusto_blob_prefix}/{filename}"
            try:
                logger.info("  Downloading %s", blob_name)
                blob_client = container_client.get_blob_client(blob_name)
                data = blob_client.download_blob().readall()
                with open(local_path, "wb") as f:
                    f.write(data)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{blob_name}: {exc}")
                logger.warning("  Failed to download %s: %s", blob_name, exc)
                # Clean up partial file
                if local_path.exists():
                    local_path.unlink()
    except Exception as exc:  # noqa: BLE001
        errors.append(f"Kusto telemetry category: {exc}")
        logger.warning("Kusto telemetry category failed: %s", exc)

    # 2. CTI reports
    try:
        reports_dir = domain_root / _CTI_REPORTS_DIR
        reports_dir.mkdir(parents=True, exist_ok=True)
        reports_file = reports_dir / "reports.jsonl"
        if force_download or not reports_file.exists():
            blob_name = f"{_CTI_REPORTS_BLOB_DIR}/reports.jsonl"
            try:
                logger.info("Downloading CTI reports from %s", blob_name)
                blob_client = container_client.get_blob_client(blob_name)
                with open(reports_file, "wb") as f:
                    f.write(blob_client.download_blob().readall())
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{blob_name}: {exc}")
                logger.warning("Failed to download %s: %s", blob_name, exc)
        else:
            logger.info("Skipping CTI reports (already exists)")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"CTI reports category: {exc}")
        logger.warning("CTI reports category failed: %s", exc)

    # 3. Sigma rules
    try:
        sigma_dir = domain_root / _SIGMA_RULES_DIR
        sigma_dir.mkdir(parents=True, exist_ok=True)
        sigma_file = sigma_dir / "sigma_rules.json"
        if force_download or not sigma_file.exists():
            blob_name = f"{_DETECTION_BLOB_DIR}/sigma_rules.json"
            try:
                logger.info("Downloading sigma rules from %s", blob_name)
                blob_client = container_client.get_blob_client(blob_name)
                with open(sigma_file, "wb") as f:
                    f.write(blob_client.download_blob().readall())
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{blob_name}: {exc}")
                logger.warning("Failed to download %s: %s", blob_name, exc)
        else:
            logger.info("Skipping sigma rules (already exists)")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"Sigma rules category: {exc}")
        logger.warning("Sigma rules category failed: %s", exc)

    if errors:
        summary = "; ".join(errors)
        logger.warning(
            "CTI Realm data download completed with %d error(s): %s",
            len(errors),
            summary,
        )
        raise RuntimeError(
            f"CTI Realm data download had {len(errors)} error(s): {summary}"
        )

    logger.info("CTI Realm data download complete")


def _has_kusto_data(domain_root: Path) -> bool:
    """Check if Kusto telemetry data directory has at least one .jsonl file."""
    kusto_dir = domain_root / _KUSTO_DATA_DIR
    if not kusto_dir.exists():
        return False
    return any(kusto_dir.glob("*.jsonl"))


def _has_cti_reports(domain_root: Path) -> bool:
    """Check if CTI reports file exists."""
    return (domain_root / _CTI_REPORTS_DIR / "reports.jsonl").exists()


def _has_sigma_rules(domain_root: Path) -> bool:
    """Check if sigma rules file exists."""
    return (domain_root / _SIGMA_RULES_DIR / "sigma_rules.json").exists()


class DownloadCTIData:
    """Setup hook that downloads CTI Realm data if not present.

    Satisfies the ``saber.hooks.SetupHook`` protocol. Checks whether
    all three data categories are present locally. If any are missing,
    the hook triggers a download from Azure Blob Storage.

    Args:
        anonymized: Download anonymized telemetry data (PII-free).
        force_download: Always run the download regardless of local state.
    """

    def __init__(
        self,
        *,
        anonymized: bool = False,
        force_download: bool = False,
    ) -> None:
        self._anonymized = anonymized
        self._force_download = force_download

    @property
    def name(self) -> str:
        """Human-readable hook name."""
        return "download_cti_data"

    def should_run(self, domain_root: Path) -> bool:
        """Return True if any data category is missing or force_download is set."""
        if self._force_download:
            return True
        if not _has_kusto_data(domain_root):
            return True
        if not _has_cti_reports(domain_root):
            return True
        if not _has_sigma_rules(domain_root):
            return True
        return False

    def run(self, domain_root: Path) -> None:
        """Download CTI Realm data from Azure Blob Storage."""
        download_cti_data(
            domain_root,
            anonymized=self._anonymized,
            force_download=self._force_download,
        )


def _cli_bool(value: str | bool | None, default: bool = False) -> bool:
    """Coerce a CLI string to a boolean.

    Truthy strings: ``"true"``, ``"1"``, ``"yes"`` (case-insensitive).

    Args:
        value: The value to coerce.
        default: Returned when *value* is None.

    Returns:
        The boolean interpretation of *value*.
    """
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"true", "1", "yes"}


def get_hooks(
    domain_root: Path,  # noqa: ARG001
    **kwargs: object,
) -> list[SetupHook]:
    """Return CTI Realm setup hooks for auto-discovery.

    Called by ``saber.task._discover_setup_hooks()`` when it finds this
    module's ``get_hooks`` function.

    Recognized ``-T`` flags (passed as *kwargs*):

    * ``anonymized`` — ``"true"`` / ``"false"`` (default: false).
    * ``force_download`` — ``"true"`` / ``"false"`` (default: false).

    Args:
        domain_root: Path to the domain root directory.
        **kwargs: Additional keyword arguments from CLI ``-T`` flags.

    Returns:
        List of setup hook instances.
    """
    anonymized = _cli_bool(
        kwargs.get("anonymized"),  # type: ignore[arg-type]
        default=False,
    )
    force_download = _cli_bool(
        kwargs.get("force_download"),  # type: ignore[arg-type]
        default=False,
    )
    return [
        DownloadCTIData(
            anonymized=anonymized,
            force_download=force_download,
        )
    ]
