"""CRSBench domain setup hooks.

Provides a ``DownloadBenchmarkData`` hook that downloads CRSBench benchmark
data from HuggingFace if not already present locally.
"""

from __future__ import annotations

from pathlib import Path

from saber.logging import get_logger

logger = get_logger("domains.crsbench.setup")

_BENCHMARK_SUBDIR = "data/benchmarks"
REPO_ID = "sslab-gatech/crsbench-dataset"


def download_benchmarks(
    output_dir: Path,
    *,
    include_ground_truth: bool = True,
    benchmarks: list[str] | None = None,
) -> Path:
    """Download CRSBench benchmark data via ``huggingface_hub.snapshot_download``.

    Args:
        output_dir: Directory where benchmark data will be downloaded.
        include_ground_truth: When True (default), download everything
            including ``.aixcc/`` ground truth. When False, download only
            ``*/benchmark.tar.gz`` files.
        benchmarks: Optional list of specific benchmark names to download
            (e.g. ``["afc-curl-delta-01"]``). When None, download all.

    Returns:
        Path to the downloaded snapshot directory.

    Raises:
        ImportError: If ``huggingface_hub`` is not installed.
    """
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise ImportError(
            "huggingface_hub is required for CRSBench data download. "
            "Install it with: pip install 'oss_saber[crsbench]'"
        ) from exc

    output_dir.mkdir(parents=True, exist_ok=True)

    # Build allow_patterns for filtering
    allow_patterns: list[str] | None = None
    if not include_ground_truth:
        allow_patterns = ["*/benchmark.tar.gz"]
    elif benchmarks:
        # Download only specific benchmarks (all files within each)
        allow_patterns = [f"{name}/**" for name in benchmarks]

    logger.info(
        "Downloading CRSBench data from %s to %s "
        "(ground_truth=%s, benchmarks=%s)",
        REPO_ID,
        output_dir,
        include_ground_truth,
        benchmarks or "all",
    )

    result = snapshot_download(
        repo_id=REPO_ID,
        repo_type="dataset",
        local_dir=str(output_dir),
        allow_patterns=allow_patterns,
    )

    logger.info("CRSBench download complete: %s", result)
    return Path(result)


class DownloadBenchmarkData:
    """Setup hook that downloads CRSBench data if not present.

    Satisfies the ``saber.hooks.SetupHook`` protocol. The hook checks
    whether ``<domain_root>/data/benchmarks/`` exists and is non-empty.
    If so, the hook is skipped. Otherwise, it calls
    ``download_benchmarks()`` to fetch data from HuggingFace.

    Args:
        include_ground_truth: Download ``.aixcc/`` ground truth data.
            Defaults to True.
        benchmarks: Optional list of specific benchmark names to download.
            Defaults to None (all benchmarks).
    """

    def __init__(
        self,
        *,
        include_ground_truth: bool = True,
        benchmarks: list[str] | None = None,
    ) -> None:
        self._include_ground_truth = include_ground_truth
        self._benchmarks = benchmarks

    @property
    def name(self) -> str:
        """Human-readable hook name."""
        return "download_benchmark_data"

    def should_run(self, domain_root: Path) -> bool:
        """Return True if benchmark data is missing or empty."""
        data_dir = domain_root / _BENCHMARK_SUBDIR
        if not data_dir.exists():
            return True
        return not any(data_dir.iterdir())

    def run(self, domain_root: Path) -> None:
        """Download benchmark data from HuggingFace."""
        output_dir = domain_root / _BENCHMARK_SUBDIR
        download_benchmarks(
            output_dir,
            include_ground_truth=self._include_ground_truth,
            benchmarks=self._benchmarks,
        )
