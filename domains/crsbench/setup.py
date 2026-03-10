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

_BENCHMARK_SUBDIR = "data/_benchmarks"
REPO_ID = "sslab-gatech/crsbench-dataset"

# Named dataset groups.  Values are either ``None`` (meaning "all
# benchmarks") or a callable ``(list[str]) -> list[str]`` that filters
# a list of benchmark directory names.
_DATASET_GROUPS: dict[str, str] = {
    "all": "*",
    "competition": "!sanity-*",
    "sanity": "sanity-*",
}
"""Predefined dataset groups for ``-T dataset=<group>``.

Each value is a simple pattern string:
- ``"*"`` — match all benchmarks
- ``"prefix-*"`` — match benchmarks starting with *prefix-*
- ``"!prefix-*"`` — match all benchmarks **except** those starting with *prefix-*
"""

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
    whether ``<domain_root>/data/_benchmarks/`` exists and is non-empty.
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

    def _resolve_datasets(self, data_dir: Path) -> list[str] | None:
        """Expand named dataset groups into concrete benchmark names.

        If ``self._datasets`` contains a single entry that matches a key
        in :data:`_DATASET_GROUPS`, it is expanded using the directory
        listing of *data_dir*.  Otherwise the original list is returned
        unchanged.

        Returns:
            Resolved list of benchmark names, or ``None`` (meaning *all*).
        """
        if self._datasets is None:
            return None
        if len(self._datasets) == 1 and self._datasets[0] in _DATASET_GROUPS:
            return _expand_group(self._datasets[0], data_dir)
        return self._datasets

    def should_run(self, domain_root: Path) -> bool:
        """Return True if benchmark data is missing, unstaged, or force_download is set."""
        if self._force_download:
            return True
        data_dir = domain_root / _BENCHMARK_SUBDIR
        if not data_dir.exists():
            return True
        resolved = self._resolve_datasets(data_dir)
        if resolved is not None:
            dirs = [data_dir / name for name in resolved]
        else:
            dirs = [d for d in sorted(data_dir.iterdir()) if d.is_dir() and not d.name.startswith(".")]
        if not dirs:
            return True
        return any(not _is_benchmark_ready(d) for d in dirs)

    def run(self, domain_root: Path) -> None:
        """Download benchmark data from HuggingFace, stage it, and generate task YAMLs."""
        output_dir = domain_root / _BENCHMARK_SUBDIR
        resolved = self._resolve_datasets(output_dir)
        download_benchmarks(
            output_dir,
            include_ground_truth=self._include_ground_truth,
            benchmarks=resolved,
        )
        extract_all_tarballs(output_dir, datasets=resolved)
        stage_all_benchmarks(output_dir, datasets=resolved)

        # Generate task YAMLs
        from crsbench.scripts.generate_tasks import generate_all_tasks

        tasks_dir = domain_root / "tasks"
        if resolved is None:
            removed = clean_task_dirs(tasks_dir)
            if removed:
                logger.info("Cleaned %d old task group directories", removed)

        generated = generate_all_tasks(output_dir, tasks_dir, datasets=resolved)
        logger.info("Generated %d task YAML files", len(generated))


def _is_benchmark_ready(benchmark_dir: Path) -> bool:
    """Check if a single benchmark directory is fully staged.

    A benchmark is ready when it has both ``.aixcc/meta.yaml`` and a
    non-empty ``staged/`` directory.

    Args:
        benchmark_dir: Path to a benchmark directory.

    Returns:
        True if the benchmark is extracted and staged.
    """
    meta = benchmark_dir / ".aixcc" / "meta.yaml"
    staged = benchmark_dir / "staged"
    return meta.exists() and staged.exists() and any(staged.iterdir())


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


def extract_all_tarballs(
    benchmarks_dir: Path,
    *,
    datasets: list[str] | None = None,
) -> None:
    """Extract tarballs for benchmark subdirectories.

    Iterates over subdirectories of *benchmarks_dir* and calls
    :func:`extract_benchmark_tarballs` on each.  When *datasets* is
    provided, only those named directories are processed.

    Args:
        benchmarks_dir: Root directory containing benchmark subdirectories.
        datasets: Optional list of benchmark names to process.  When None,
            all non-dot subdirectories are processed.
    """
    if datasets is not None:
        dirs = [benchmarks_dir / name for name in datasets if (benchmarks_dir / name).is_dir()]
    else:
        dirs = [d for d in sorted(benchmarks_dir.iterdir()) if d.is_dir() and not d.name.startswith(".")]
    for child in dirs:
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
            ``data/_benchmarks/sanity-mock-c-delta-01``).
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


def stage_all_benchmarks(
    benchmarks_dir: Path,
    *,
    datasets: list[str] | None = None,
) -> None:
    """Stage benchmarks in a directory.

    Iterates over subdirectories of *benchmarks_dir* that contain an
    ``.aixcc/`` directory and stages each one.  When *datasets* is
    provided, only those named directories are processed.

    Args:
        benchmarks_dir: Root directory containing benchmark subdirectories.
        datasets: Optional list of benchmark names to process.  When None,
            all non-dot subdirectories are processed.
    """
    if datasets is not None:
        dirs = [benchmarks_dir / name for name in datasets if (benchmarks_dir / name).is_dir()]
    else:
        dirs = [d for d in sorted(benchmarks_dir.iterdir()) if d.is_dir() and not d.name.startswith(".")]
    for child in dirs:
        if (child / ".aixcc").is_dir():
            stage_benchmark(child)


def _expand_group(group_name: str, benchmarks_dir: Path) -> list[str] | None:
    """Expand a named dataset group into benchmark directory names.

    Args:
        group_name: Key in :data:`_DATASET_GROUPS`.
        benchmarks_dir: Root directory containing benchmark subdirectories.

    Returns:
        Filtered list of benchmark names, or ``None`` if the group
        resolves to *all* benchmarks.
    """
    pattern = _DATASET_GROUPS[group_name]
    if pattern == "*":
        return None

    all_dirs = sorted(
        d.name for d in benchmarks_dir.iterdir()
        if d.is_dir() and not d.name.startswith(".")
    )

    if pattern.startswith("!"):
        # Exclusion pattern: "!sanity-*" → keep everything NOT matching
        prefix = pattern[1:].removesuffix("*")
        return [name for name in all_dirs if not name.startswith(prefix)]

    # Inclusion pattern: "sanity-*" → keep only matching
    prefix = pattern.removesuffix("*")
    return [name for name in all_dirs if name.startswith(prefix)]


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
    *,
    dataset: str | list[str] | None = None,
    include_ground_truth: str | bool | None = None,
    force_download: str | bool | None = None,
) -> list[SetupHook]:
    """Return CRSBench setup hooks for auto-discovery.

    Called by ``saber.task._discover_setup_hooks()`` when it finds this
    module's ``get_hooks`` function.

    Recognized ``-T`` flags:

    * ``dataset`` — comma-separated dataset/benchmark names, or a named
      group: ``all`` (everything), ``competition`` (non-sanity),
      ``sanity`` (sanity only).  Defaults to all.
    * ``include_ground_truth`` — ``"true"`` / ``"false"`` (default: true).
    * ``force_download`` — ``"true"`` / ``"false"`` (default: false).

    Args:
        domain_root: Path to the domain root directory.
        dataset: Comma-separated dataset/benchmark names to download,
            or ``None`` for all.
        include_ground_truth: ``"true"`` / ``"false"`` (default: true).
        force_download: ``"true"`` / ``"false"`` (default: false).

    Returns:
        List of setup hook instances.
    """
    return [
        DownloadBenchmarkData(
            datasets=_parse_csv(dataset),
            include_ground_truth=_cli_bool(include_ground_truth, default=True),
            force_download=_cli_bool(force_download, default=False),
        )
    ]
