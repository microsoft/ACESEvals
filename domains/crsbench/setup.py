"""CRSBench domain setup hooks.

Provides a ``DownloadBenchmarkData`` hook that downloads CRSBench benchmark
data from HuggingFace if not already present locally.
"""

from __future__ import annotations

import shutil
import tarfile
from pathlib import Path

from saber.hooks import SetupHook
from saber.logging import get_logger

logger = get_logger("domains.crsbench.setup")

_BENCHMARK_SUBDIR = "data/benchmarks"
REPO_ID = "sslab-gatech/crsbench-dataset"

# File patterns removed from staged directories to prevent information
# leakage (patch artifacts, version-control history, editor backups).
_ARTIFACT_GLOBS: tuple[str, ...] = (
    "*.rej",
    "*.orig",
    "*.bak",
    "*~",
)


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
        datasets: Optional list of specific benchmark/dataset names to download.
            Defaults to None (all datasets).
        force_download: When True, always run the download even if data
            already exists locally. Defaults to False.
    """

    def __init__(
        self,
        *,
        include_ground_truth: bool = True,
        datasets: list[str] | None = None,
        force_download: bool = False,
    ) -> None:
        self._include_ground_truth = include_ground_truth
        self._datasets = datasets
        self._force_download = force_download

    @property
    def name(self) -> str:
        """Human-readable hook name."""
        return "download_benchmark_data"

    def should_run(self, domain_root: Path) -> bool:
        """Return True if benchmark data is missing, empty, or force_download is set."""
        if self._force_download:
            return True
        data_dir = domain_root / _BENCHMARK_SUBDIR
        if not data_dir.exists():
            return True
        if self._datasets is not None:
            for name in self._datasets:
                ds_dir = data_dir / name
                meta = ds_dir / ".aixcc" / "meta.yaml"
                staged = ds_dir / "staged"
                if not meta.exists() or not staged.exists() or not any(staged.iterdir()):
                    return True
            return False
        return not any(data_dir.iterdir())

    def run(self, domain_root: Path) -> None:
        """Download benchmark data from HuggingFace, stage it, and generate task YAMLs."""
        output_dir = domain_root / _BENCHMARK_SUBDIR
        download_benchmarks(
            output_dir,
            include_ground_truth=self._include_ground_truth,
            benchmarks=self._datasets,
        )
        extract_all_tarballs(output_dir)
        stage_all_benchmarks(output_dir)

        # Generate task YAMLs
        from crsbench.scripts.generate_tasks import generate_all_tasks

        tasks_dir = domain_root / "tasks"
        if self._datasets is None:
            removed = clean_task_dirs(tasks_dir)
            if removed:
                logger.info("Cleaned %d old task group directories", removed)

        generated = generate_all_tasks(output_dir, tasks_dir, datasets=self._datasets)
        logger.info("Generated %d task YAML files", len(generated))


def clean_task_dirs(tasks_dir: Path) -> int:
    """Remove generated task subdirectories, preserving global.yaml and .gitignore.

    Args:
        tasks_dir: Path to the tasks directory.

    Returns:
        Count of removed directories.
    """
    if not tasks_dir.exists():
        return 0

    removed = 0
    for child in sorted(tasks_dir.iterdir()):
        if child.is_dir():
            shutil.rmtree(child)
            removed += 1
    return removed


# ---------------------------------------------------------------------------
# Tarball extraction
# ---------------------------------------------------------------------------

_TARBALL_NAMES: tuple[str, ...] = ("benchmark.tar.gz", "ground-truth.tar.gz")
"""Tarballs downloaded by ``snapshot_download`` that must be extracted."""


def extract_benchmark_tarballs(benchmark_dir: Path) -> None:
    """Extract downloaded tarballs into *benchmark_dir*.

    Extracts ``benchmark.tar.gz`` and ``ground-truth.tar.gz`` so that
    ``stage_benchmark()`` can find ``pkgs/``, ``.aixcc/``, etc.

    The operation is **idempotent**: if ``.aixcc/meta.yaml`` already
    exists the function returns immediately.

    Args:
        benchmark_dir: Path to a single benchmark directory containing
            the downloaded tarballs.
    """
    marker = benchmark_dir / ".aixcc" / "meta.yaml"
    if marker.exists():
        logger.info(
            "Tarballs already extracted (marker exists): %s",
            benchmark_dir.name,
        )
        return

    for name in _TARBALL_NAMES:
        tarball = benchmark_dir / name
        if not tarball.exists():
            logger.warning(
                "Tarball %s not found in %s — skipping",
                name,
                benchmark_dir.name,
            )
            continue
        logger.info("Extracting %s in %s", name, benchmark_dir.name)
        with tarfile.open(tarball, "r:gz") as tf:
            tf.extractall(path=benchmark_dir)  # noqa: S202


def extract_all_tarballs(benchmarks_dir: Path) -> None:
    """Extract tarballs for every benchmark subdirectory.

    Iterates over subdirectories of *benchmarks_dir* and calls
    :func:`extract_benchmark_tarballs` on each.

    Args:
        benchmarks_dir: Root directory containing benchmark subdirectories.
    """
    for child in sorted(benchmarks_dir.iterdir()):
        if child.is_dir():
            extract_benchmark_tarballs(child)


def stage_benchmark(benchmark_dir: Path) -> None:
    """Stage a single benchmark for use by the sandbox.

    Extracts ``pkgs/*.tar.gz`` archives and copies build.sh, test.sh,
    fuzz harnesses, and test sources into a flat ``staged/`` directory
    within the benchmark directory.  After staging, removes version-control
    history and patch artifacts that could leak vulnerability fixes to the
    agent.

    Args:
        benchmark_dir: Path to a benchmark directory (e.g.
            ``data/benchmarks/sanity-mock-c-delta-01``).
    """
    staged = benchmark_dir / "staged"
    if staged.exists() and any(staged.iterdir()):
        logger.info("Already staged: %s", benchmark_dir.name)
        return

    staged.mkdir(parents=True, exist_ok=True)

    # Extract all tarballs in pkgs/
    pkgs_dir = benchmark_dir / "pkgs"
    if pkgs_dir.exists():
        for tarball_path in sorted(pkgs_dir.glob("*.tar.gz")):
            logger.info("Extracting %s", tarball_path.name)
            with tarfile.open(tarball_path, "r:gz") as tf:
                tf.extractall(path=staged)  # noqa: S202

    # Copy build.sh and test.sh from ground truth if present
    gt_dir = benchmark_dir / ".aixcc"
    for script_name in ("build.sh", "test.sh"):
        src = gt_dir / script_name
        if src.exists():
            dst = staged / script_name
            shutil.copy2(src, dst)
            dst.chmod(0o755)

    # Copy fuzz harness sources
    fuzz_src = gt_dir / "fuzz"
    if fuzz_src.exists():
        fuzz_dst = staged / "fuzz"
        if not fuzz_dst.exists():
            shutil.copytree(fuzz_src, fuzz_dst)

    # Copy test sources
    tests_src = gt_dir / "tests"
    if tests_src.exists():
        tests_dst = staged / "tests"
        if not tests_dst.exists():
            shutil.copytree(tests_src, tests_dst)

    logger.info("Staged %s", benchmark_dir.name)

    # Remove artifacts that could leak vulnerability information
    _sanitize_staged_dir(staged)


def _sanitize_staged_dir(staged: Path) -> None:
    """Remove version-control history and patch artifacts from *staged*.

    This prevents the agent from discovering the vulnerability fix by
    inspecting ``.git`` history or reading ``.rej`` / ``.orig`` files
    left by previous patch attempts.

    Removes:
    - ``.git/`` directories (prevents ``git log`` / ``git diff`` leakage)
    - ``*.rej``, ``*.orig``, ``*.bak``, ``*~`` files (patch / editor artifacts)

    Args:
        staged: Root of the staged directory tree to sanitize.
    """
    # Remove .git directories
    for git_dir in staged.rglob(".git"):
        if git_dir.is_dir():
            shutil.rmtree(git_dir)
            logger.info("Removed %s", git_dir)

    # Remove patch / editor backup artifacts
    for pattern in _ARTIFACT_GLOBS:
        for artifact in staged.rglob(pattern):
            if artifact.is_file():
                artifact.unlink()
                logger.info("Removed artifact %s", artifact)


def stage_all_benchmarks(benchmarks_dir: Path) -> None:
    """Stage all benchmarks in a directory.

    Iterates over subdirectories of *benchmarks_dir* that contain an
    ``.aixcc/`` directory and stages each one.

    Args:
        benchmarks_dir: Root directory containing benchmark subdirectories.
    """
    for child in sorted(benchmarks_dir.iterdir()):
        if child.is_dir() and (child / ".aixcc").is_dir():
            stage_benchmark(child)


def _parse_csv(value: str | list[str] | None) -> list[str] | None:
    """Parse a comma-separated string into a list.

    Args:
        value: A comma-separated string, a list, or None.

    Returns:
        A list of strings, or None if *value* is None.
    """
    if value is None:
        return None
    if isinstance(value, list):
        return value
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _cli_bool(value: str | bool | None, default: bool = False) -> bool:
    """Coerce a CLI string to a boolean.

    Truthy strings: ``"true"``, ``"1"``, ``"yes"`` (case-insensitive).
    Everything else is falsy.

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
    """Return CRSBench setup hooks for auto-discovery.

    Called by ``saber.task._discover_setup_hooks()`` when it finds this
    module's ``get_hooks`` function.

    Recognized ``-T`` flags (passed as *kwargs*):

    * ``dataset`` — comma-separated dataset/benchmark names to download
      and evaluate.  Also used by ``create_task`` to filter tasks.
    * ``include_ground_truth`` — ``"true"`` / ``"false"`` (default: true).
    * ``force_download`` — ``"true"`` / ``"false"`` (default: false).

    Args:
        domain_root: Path to the domain root directory.
        **kwargs: Additional keyword arguments from CLI ``-T`` flags.

    Returns:
        List of setup hook instances.
    """
    datasets = _parse_csv(
        kwargs.get("dataset"),  # type: ignore[arg-type]
    )
    include_ground_truth = _cli_bool(
        kwargs.get("include_ground_truth"),  # type: ignore[arg-type]
        default=True,
    )
    force_download = _cli_bool(
        kwargs.get("force_download"),  # type: ignore[arg-type]
        default=False,
    )
    return [
        DownloadBenchmarkData(
            datasets=datasets,
            include_ground_truth=include_ground_truth,
            force_download=force_download,
        )
    ]
