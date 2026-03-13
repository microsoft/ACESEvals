"""Excytin domain setup hooks.

Provides a ``DownloadExcytinData`` hook that downloads excytin benchmark
data (csv_files/ and sql_files/) from HuggingFace if not already present
locally at ``domains/excytin/data/``.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from saber.hooks import SetupHook
from saber.logging import get_logger

logger = get_logger("domains.excytin.setup")

REPO_ID = "anandmudgerikar/excytin-bench"
DATA_ZIP_FILENAME = "data.zip"

# Subdirectories expected inside data/ after extraction
_EXPECTED_SUBDIRS = ("csv_files", "sql_files")


def download_and_extract_data(
    data_dir: Path,
    *,
    force: bool = False,
) -> None:
    """Download excytin data.zip from HuggingFace and extract it.

    Uses ``huggingface_hub.hf_hub_download`` to fetch ``data.zip`` from
    the excytin-bench dataset repo, then extracts it into *data_dir*.

    Args:
        data_dir: Target directory (``domains/excytin/data/``).
        force: Re-download even if data already exists.

    Raises:
        ImportError: If ``huggingface_hub`` is not installed.
    """
    try:
        from huggingface_hub import hf_hub_download
    except ImportError as exc:
        raise ImportError(
            "huggingface_hub is required for excytin data download. "
            "Install it with: pip install huggingface_hub"
        ) from exc

    data_dir.mkdir(parents=True, exist_ok=True)

    logger.info(
        "Downloading %s from %s ...",
        DATA_ZIP_FILENAME,
        REPO_ID,
    )

    zip_path = hf_hub_download(
        repo_id=REPO_ID,
        repo_type="dataset",
        filename=DATA_ZIP_FILENAME,
    )

    logger.info("Download complete: %s — extracting to %s", zip_path, data_dir)

    with zipfile.ZipFile(zip_path, "r") as zf:
        # The zip contains a top-level data/ directory (data/csv_files/,
        # data/sql_files/).  Strip that prefix so files land directly in
        # *data_dir* instead of data_dir/data/.
        prefix = "data/"
        for member in zf.infolist():
            if not member.filename.startswith(prefix):
                continue
            # Build the path with the prefix stripped
            rel = member.filename[len(prefix) :]
            if not rel:
                continue  # skip the prefix directory entry itself
            target = data_dir / rel
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, open(target, "wb") as dst:
                    dst.write(src.read())

    logger.info("Excytin data extraction complete.")


class DownloadExcytinData:
    """Setup hook that downloads excytin data if not present.

    Satisfies the ``saber.hooks.SetupHook`` protocol. The hook checks
    whether ``<domain_root>/data/csv_files/`` and ``data/sql_files/``
    exist and are non-empty. If not, it downloads ``data.zip`` from
    HuggingFace and extracts it.

    Args:
        force_download: When True, always run the download even if data
            already exists locally. Defaults to False.
    """

    def __init__(self, *, force_download: bool = False) -> None:
        self._force_download = force_download

    @property
    def name(self) -> str:
        """Human-readable hook name."""
        return "download_excytin_data"

    def should_run(self, domain_root: Path) -> bool:
        """Return True if data files are missing or force_download is set."""
        if self._force_download:
            return True
        data_dir = domain_root / "data"
        return any(
            not (data_dir / subdir).is_dir()
            or not any((data_dir / subdir).iterdir())
            for subdir in _EXPECTED_SUBDIRS
        )

    def run(self, domain_root: Path) -> None:
        """Download and extract excytin data from HuggingFace."""
        data_dir = domain_root / "data"
        download_and_extract_data(data_dir, force=self._force_download)

        # Validate extraction
        for subdir in _EXPECTED_SUBDIRS:
            subdir_path = data_dir / subdir
            if not subdir_path.is_dir() or not any(subdir_path.iterdir()):
                raise RuntimeError(
                    f"Extraction succeeded but {subdir}/ is missing or empty "
                    f"in {data_dir}. The data.zip structure may have changed."
                )

        logger.info(
            "Excytin data ready: %s",
            ", ".join(
                f"{s}/ ({sum(1 for _ in (data_dir / s).iterdir())} items)"
                for s in _EXPECTED_SUBDIRS
            ),
        )


def _cli_bool(value: str | bool | None, default: bool = False) -> bool:
    """Coerce a CLI string to a boolean."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"true", "1", "yes"}


def get_hooks(
    domain_root: Path,  # noqa: ARG001
    *,
    force_download: str | bool | None = None,
    **kwargs: object,
) -> list[SetupHook]:
    """Return excytin setup hooks for auto-discovery.

    Called by ``saber.task._discover_setup_hooks()`` when it finds this
    module's ``get_hooks`` function.

    Args:
        domain_root: Path to the domain root directory.
        force_download: ``"true"`` / ``"false"`` (default: false).
        **kwargs: Additional keyword arguments (ignored).

    Returns:
        List of setup hook instances.
    """
    return [
        DownloadExcytinData(
            force_download=_cli_bool(force_download, default=False),
        )
    ]
