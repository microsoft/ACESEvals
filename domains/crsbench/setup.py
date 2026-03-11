"""CRSBench domain setup hooks.

Provides setup hooks that run before task evaluation:

0. ``LinkDataDir`` — (optional) symlinks ``<domain_root>/data`` to an
   external directory on a larger drive so downloads don't fill the
   root filesystem.
1. ``DownloadBenchmarkData`` — downloads CRSBench benchmark data from
   HuggingFace if not already present locally.
2. ``StageBenchmarkData`` — extracts benchmark.tar.gz and ground-truth.tar.gz
   in each benchmark directory so Dockerfiles and .aixcc/meta.yaml are ready.
3. ``BuildBenchmarkImages`` — builds two-layer Docker images for each
   benchmark so containers launch pre-loaded with source, deps, and tooling.
4. ``GenerateTaskYAMLs`` — generates task YAML files from benchmark metadata
   after data is downloaded and images are built.

The ``get_hooks()`` entry point returns all hooks in the correct order
and is auto-discovered by ``saber.setup_discovery``.
"""

from __future__ import annotations

import os
import shutil
import tarfile
from pathlib import Path
from typing import TYPE_CHECKING

from saber.hooks import SetupHook
from saber.logging import display_progress, get_logger

if TYPE_CHECKING:
    from crsbench.scripts.build_images import ImageBuildSummary

logger = get_logger("domains.crsbench.setup")

_DATA_SUBDIR = "data"
_BENCHMARK_SUBDIR = "data/benchmarks"
_TASKS_SUBDIR = "tasks"
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
        ImportError: If ``huggingface_hub`` is not installed and no
            benchmark data already exists locally.
    """
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        # If data already exists on disk, skip the download gracefully.
        # This allows extract/stage to proceed with locally-available data.
        if output_dir.exists() and any(
            d.is_dir() and not d.name.startswith(".")
            for d in output_dir.iterdir()
        ):
            logger.info(
                "huggingface_hub not installed but data already exists at %s; "
                "skipping download",
                output_dir,
            )
            return output_dir
        raise ImportError(
            "huggingface_hub is required for CRSBench data download. "
            "Install it with: pip install 'oss_saber[crsbench]'"
        )

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


class LinkDataDir:
    """Setup hook that symlinks the data directory to an external path.

    When benchmark data is large (CRSBench is ~13 GB compressed, ~120 GB
    extracted), storing it on the root filesystem can be impractical.
    This hook creates a symlink from ``<domain_root>/data`` to a
    user-specified directory on a larger drive.

    If ``<domain_root>/data`` already exists as a real directory **with
    content**, the hook logs a warning and skips — it will not overwrite
    existing data.  If it already points to the target, it's a no-op.

    Args:
        target_dir: Absolute path to the external data directory
            (e.g. ``/mnt/crsbench_data``).  Created if it does not exist.
    """

    def __init__(self, target_dir: str) -> None:
        self._target = Path(target_dir)

    @property
    def name(self) -> str:
        """Human-readable hook name."""
        return "link_data_dir"

    def should_run(self, domain_root: Path) -> bool:
        """Return True unless the symlink already points to the target."""
        link_path = domain_root / _DATA_SUBDIR
        if link_path.is_symlink():
            return link_path.resolve() != self._target.resolve()
        # Real directory with content — don't clobber
        if link_path.is_dir() and any(link_path.iterdir()):
            return False
        return True

    def run(self, domain_root: Path) -> None:
        """Create or update the data directory symlink."""
        link_path = domain_root / _DATA_SUBDIR

        # Ensure the target exists
        self._target.mkdir(parents=True, exist_ok=True)

        # Remove empty dir or stale symlink
        if link_path.is_symlink() or (link_path.is_dir() and not any(link_path.iterdir())):
            if link_path.is_symlink():
                link_path.unlink()
            else:
                link_path.rmdir()

        if link_path.exists():
            logger.warning(
                "Cannot link data dir: %s already exists with content. "
                "Remove it manually or move its contents to %s.",
                link_path, self._target,
            )
            return

        # Create parent directories if needed
        link_path.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(str(self._target), str(link_path))
        logger.info("Linked data directory: %s -> %s", link_path, self._target)


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
        force_build: bool = False,
        rebuild_images: str | None = None,
    ) -> None:
        self._include_ground_truth = include_ground_truth
        self._datasets = datasets
        self._force_download = force_download
        self._force_build = force_build
        self._rebuild_images = rebuild_images

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
        """Return True if benchmark data is missing, unstaged, images need building, or task YAMLs are absent."""
        if self._force_download or self._force_build:
            return True
        if self._rebuild_images is not None:
            return True
        data_dir = domain_root / _BENCHMARK_SUBDIR
        if not data_dir.exists():
            return True
        resolved = self._resolve_datasets(data_dir)
        dirs = _list_benchmark_dirs(data_dir, resolved)
        if not dirs:
            return True
        if any(not _is_benchmark_ready(d) for d in dirs):
            return True
        # Also check that task YAMLs have been generated
        tasks_dir = domain_root / "tasks"
        if not tasks_dir.exists():
            return True
        task_yamls = [
            f for f in tasks_dir.rglob("*.yaml")
            if f.name not in {"global.yaml", "shared.yaml"}
        ]
        if len(task_yamls) == 0:
            return True
        # Check that at least one task YAML has benchmark_image
        # (self-healing: re-runs if YAMLs were generated before image support)
        return not _any_yaml_has_benchmark_image(tasks_dir)

    def run(self, domain_root: Path) -> None:
        """Download benchmark data from HuggingFace, stage it, and generate task YAMLs."""
        output_dir = domain_root / _BENCHMARK_SUBDIR

        # Resolve groups before download if possible; if the directory
        # doesn't exist yet we must download everything first and resolve
        # afterwards for extract/stage/generate.
        if output_dir.exists():
            resolved = self._resolve_datasets(output_dir)
        else:
            resolved = self._datasets  # may be ["competition"] etc.

        # For named groups that haven't been expanded yet, download all
        # benchmarks so we have the directory listing to resolve against.
        download_resolved = resolved
        if (
            resolved is not None
            and len(resolved) == 1
            and resolved[0] in _DATASET_GROUPS
        ):
            download_resolved = None  # download everything

        download_benchmarks(
            output_dir,
            include_ground_truth=self._include_ground_truth,
            benchmarks=download_resolved,
        )

        # Download is done. Extract/stage/build/generate are handled
        # by subsequent hooks in the hook chain returned by get_hooks().
        logger.info("Download complete for %s", output_dir)


# ---------------------------------------------------------------------------
# Helpers used by DownloadBenchmarkData.should_run() and others
# ---------------------------------------------------------------------------


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


def _any_yaml_has_benchmark_image(tasks_dir: Path) -> bool:
    """Check if at least one task YAML has ``benchmark_image`` in initial_context.

    A cheap heuristic to detect whether task YAMLs were generated with
    pre-built image support.  Uses raw text search (no YAML parsing) for
    speed.

    Args:
        tasks_dir: Root tasks directory with group subdirectories.

    Returns:
        True if at least one task YAML contains ``benchmark_image:``.
    """
    for yaml_file in tasks_dir.rglob("*.yaml"):
        if yaml_file.name in {"global.yaml", "shared.yaml"}:
            continue
        try:
            if "benchmark_image:" in yaml_file.read_text():
                return True
        except OSError:
            continue
    return False


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
# Benchmark directory helpers
# ---------------------------------------------------------------------------


def _is_benchmark_dir(path: Path) -> bool:
    """Return True if *path* looks like a benchmark directory.

    A benchmark directory contains either downloaded tarballs (pre-extraction)
    or an ``.aixcc/`` metadata directory (post-extraction).  Directories like
    ``index/`` that hold only metadata files are excluded.

    Args:
        path: Path to test.

    Returns:
        True if the directory contains benchmark data.
    """
    if not path.is_dir() or path.name.startswith("."):
        return False
    return (path / "benchmark.tar.gz").exists() or (path / ".aixcc").is_dir()


def _list_benchmark_dirs(benchmarks_dir: Path, datasets: list[str] | None = None) -> list[Path]:
    """List benchmark directories, optionally filtered by name.

    Args:
        benchmarks_dir: Root directory containing benchmark subdirectories.
        datasets: Optional list of benchmark names.  When ``None``, all
            benchmark directories are returned.

    Returns:
        Sorted list of benchmark directory paths.
    """
    if datasets is not None:
        return [benchmarks_dir / name for name in datasets if _is_benchmark_dir(benchmarks_dir / name)]
    return sorted(d for d in benchmarks_dir.iterdir() if _is_benchmark_dir(d))


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

    display_progress(f"Extracting {benchmark_dir.name}...")
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
    for child in _list_benchmark_dirs(benchmarks_dir, datasets):
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

    display_progress(f"Staging {benchmark_dir.name}...")
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
    for child in _list_benchmark_dirs(benchmarks_dir, datasets):
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

    all_dirs = sorted(d.name for d in _list_benchmark_dirs(benchmarks_dir))

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


# ---------------------------------------------------------------------------
# Modular setup hooks — Extract, Build, Generate
# ---------------------------------------------------------------------------


class StageBenchmarkData:
    """Setup hook that extracts benchmark tarballs after download.

    Each benchmark directory from HuggingFace contains:
    - ``benchmark.tar.gz`` — Dockerfile, source code, build scripts
    - ``ground-truth.tar.gz`` — ``.aixcc/meta.yaml``, POV blobs, patches

    This hook extracts both tarballs in-place so that subsequent hooks
    (image build, task generation) can find Dockerfiles and metadata.

    Extraction is skipped for any benchmark that already has a
    ``.aixcc/meta.yaml`` file (indicating previous extraction).

    Args:
        prefix_filter: Only extract benchmarks whose directory name starts
            with this prefix. When ``None``, extract all benchmarks.
    """

    def __init__(self, *, prefix_filter: str | None = None) -> None:
        self._prefix_filter = prefix_filter

    @property
    def name(self) -> str:
        """Human-readable hook name."""
        return "stage_benchmark_data"

    def _matches_filter(self, benchmark_name: str) -> bool:
        """Return True if the benchmark name matches the prefix filter."""
        if self._prefix_filter is None:
            return True
        return benchmark_name.startswith(self._prefix_filter)

    def should_run(self, domain_root: Path) -> bool:
        """Return True if any benchmark has tarballs that need extraction."""
        benchmarks_dir = domain_root / _BENCHMARK_SUBDIR
        if not benchmarks_dir.is_dir():
            return False

        for child in benchmarks_dir.iterdir():
            if not child.is_dir() or not self._matches_filter(child.name):
                continue
            tar_file = child / "benchmark.tar.gz"
            meta_file = child / ".aixcc" / "meta.yaml"
            if tar_file.is_file() and not meta_file.is_file():
                return True
        return False

    def run(self, domain_root: Path) -> None:
        """Extract benchmark tarballs in each benchmark directory."""
        benchmarks_dir = domain_root / _BENCHMARK_SUBDIR
        extracted = 0
        skipped = 0

        for child in sorted(benchmarks_dir.iterdir()):
            if not child.is_dir() or not self._matches_filter(child.name):
                continue

            meta_file = child / ".aixcc" / "meta.yaml"
            if meta_file.is_file():
                skipped += 1
                continue

            # Extract ground-truth first (contains .aixcc/meta.yaml)
            gt_tar = child / "ground-truth.tar.gz"
            if gt_tar.is_file():
                logger.debug("Extracting %s", gt_tar)
                with tarfile.open(gt_tar, "r:gz") as tf:
                    tf.extractall(path=child)

            # Extract benchmark (contains Dockerfile, source, etc.)
            bench_tar = child / "benchmark.tar.gz"
            if bench_tar.is_file():
                logger.debug("Extracting %s", bench_tar)
                with tarfile.open(bench_tar, "r:gz") as tf:
                    tf.extractall(path=child)

            extracted += 1

        logger.info(
            "Staged %d benchmark(s), skipped %d (already extracted)",
            extracted, skipped,
        )


class BuildBenchmarkImages:
    """Setup hook that builds two-layer Docker images for each benchmark.

    Satisfies the ``saber.hooks.SetupHook`` protocol. Checks whether
    benchmark directories have Dockerfiles and builds images for any
    benchmarks lacking a pre-built ``saber/crsbench/benchmark:<id>`` image.

    Args:
        force: Rebuild images even if they already exist.
        prefix_filter: Only build images for benchmarks matching this prefix.
    """

    def __init__(
        self,
        *,
        force: bool = False,
        prefix_filter: str | None = None,
    ) -> None:
        self._force = force
        self._prefix_filter = prefix_filter
        self._summary: object | None = None

    @property
    def name(self) -> str:
        """Human-readable hook name."""
        return "build_benchmark_images"

    @property
    def summary(self) -> object | None:
        """The ImageBuildSummary from the last run, or None."""
        return self._summary

    def should_run(self, domain_root: Path) -> bool:
        """Return True if any benchmark is missing a pre-built image."""
        from crsbench.build_images import (
            BENCHMARK_IMAGE_PREFIX,
            _discover_benchmarks,
            image_exists,
        )

        if self._force:
            return True

        benchmarks_dir = domain_root / _BENCHMARK_SUBDIR
        benchmarks = _discover_benchmarks(benchmarks_dir)

        if self._prefix_filter:
            benchmarks = [
                b for b in benchmarks if b.name.startswith(self._prefix_filter)
            ]

        if not benchmarks:
            return False

        # Check if any benchmark is missing its image
        return any(
            not image_exists(f"{BENCHMARK_IMAGE_PREFIX}:{b.name}")
            for b in benchmarks
        )

    def run(self, domain_root: Path) -> None:
        """Build Docker images for benchmarks."""
        from crsbench.build_images import build_images_sync

        summary = build_images_sync(
            domain_root / _BENCHMARK_SUBDIR,
            domain_root,
            force=self._force,
            prefix_filter=self._prefix_filter,
        )
        self._summary = summary

        if summary.failed:
            failed_ids = [r.benchmark_id for r in summary.failed]
            logger.warning(
                "Image builds failed for %d benchmark(s): %s",
                len(failed_ids),
                ", ".join(failed_ids),
            )

        logger.info(
            "Image build: %d succeeded, %d failed",
            len(summary.succeeded),
            len(summary.failed),
        )
        display_progress(
            f"Image build: {len(summary.succeeded)} succeeded, "
            f"{len(summary.failed)} failed",
        )


class GenerateTaskYAMLs:
    """Setup hook that generates task YAMLs from benchmark metadata.

    Scans benchmark directories for ``.aixcc/meta.yaml`` files and generates
    task YAML files. When ``built_benchmarks`` is provided, only generates
    tasks for benchmarks that have successfully built Docker images, and
    includes the ``benchmark_image`` in the task's initial_context.

    Args:
        built_benchmarks: Set of benchmark IDs that have pre-built images.
            When provided, only these benchmarks get task YAMLs generated
            and each task includes a ``benchmark_image`` key.
    """

    def __init__(
        self,
        *,
        built_benchmarks: set[str] | None = None,
    ) -> None:
        self._built_benchmarks = built_benchmarks

    @property
    def name(self) -> str:
        """Human-readable hook name."""
        return "generate_task_yamls"

    def should_run(self, domain_root: Path) -> bool:
        """Return True — always regenerate task YAMLs from metadata."""
        benchmarks_dir = domain_root / _BENCHMARK_SUBDIR
        if not benchmarks_dir.exists():
            return False
        # Check if any benchmarks have .aixcc/meta.yaml
        return any(benchmarks_dir.rglob(".aixcc/meta.yaml"))

    def run(self, domain_root: Path) -> None:
        """Generate task YAMLs from benchmark metadata."""
        from crsbench.scripts.generate_tasks import generate_all_tasks

        benchmarks_dir = domain_root / _BENCHMARK_SUBDIR
        output_dir = domain_root / _TASKS_SUBDIR

        generated = generate_all_tasks(
            benchmarks_dir,
            output_dir,
            built_benchmarks=self._built_benchmarks,
        )

        logger.info("Generated %d task YAML(s)", len(generated))


# ---------------------------------------------------------------------------
# Hook discovery entry point
# ---------------------------------------------------------------------------


def get_hooks(
    domain_root: Path,
    *,
    dataset: str | None = None,
    build: str | None = None,
    rebuild_images: str | None = None,
    data_dir: str | None = None,
    include_ground_truth: str | bool | None = None,
    force_download: str | bool | None = None,
    force_build: str | bool | None = None,
) -> list[SetupHook]:
    """Return ordered setup hooks for CRSBench.

    Called by ``saber.setup_discovery._discover_setup_hooks()`` before
    task evaluation. Returns hooks in dependency order:
    0. (optional) Link data directory to external drive
    1. Download benchmark data
    2. Stage (extract) benchmark tarballs
    3. Build Docker images
    4. Generate task YAMLs

    Args:
        domain_root: Domain root directory.
        dataset: Dataset selector (``competition``, ``sanity``, ``all``).
        build: When ``"true"``, force-build Docker images.
        rebuild_images: Prefix filter for rebuilding specific images.
        data_dir: External directory for benchmark data storage.
            When provided, ``<domain_root>/data`` is symlinked to this
            path so large datasets live on a bigger drive
            (e.g. ``-T data_dir=/mnt/crsbench_data``).
        include_ground_truth: ``"true"`` / ``"false"`` (default: true).
        force_download: ``"true"`` / ``"false"`` (default: false).
        force_build: ``"true"`` / ``"false"`` (default: false).
            Force rebuild all Docker images.

    Returns:
        Ordered list of setup hooks.
    """
    force = (
        _cli_bool(build) or _cli_bool(force_build) or rebuild_images is not None
    )

    hooks: list[SetupHook] = []

    # 0. (optional) Symlink data directory to external drive
    if data_dir:
        hooks.append(LinkDataDir(data_dir))

    # 1. Download benchmark data
    hooks.append(
        DownloadBenchmarkData(
            datasets=_parse_csv(dataset),
            include_ground_truth=_cli_bool(include_ground_truth, default=True),
            force_download=_cli_bool(force_download, default=False),
            force_build=force,
            rebuild_images=rebuild_images,
        )
    )

    # 2. Stage (extract) benchmark tarballs
    hooks.append(StageBenchmarkData(prefix_filter=rebuild_images))

    # 3. Build Docker images
    build_hook = BuildBenchmarkImages(
        force=force,
        prefix_filter=rebuild_images,
    )
    hooks.append(build_hook)

    # 4. Generate task YAMLs — we connect the build results to task generation
    #    via a wrapper that extracts built_benchmarks after the build hook runs.
    hooks.append(_ConnectedGenerateTaskYAMLs(
        build_hook=build_hook,
        dataset=dataset or "competition",
    ))

    return hooks


class _ConnectedGenerateTaskYAMLs:
    """Internal wrapper that connects build results to task generation.

    After the build hook runs, this hook extracts the set of successfully
    built benchmark IDs and passes them to GenerateTaskYAMLs.
    """

    def __init__(
        self,
        *,
        build_hook: BuildBenchmarkImages,
        dataset: str = "competition",
    ) -> None:
        self._build_hook = build_hook
        self._dataset = dataset

    @property
    def name(self) -> str:
        return "generate_task_yamls"

    def should_run(self, domain_root: Path) -> bool:
        benchmarks_dir = domain_root / _BENCHMARK_SUBDIR
        if not benchmarks_dir.exists():
            return False
        return any(benchmarks_dir.rglob(".aixcc/meta.yaml"))

    def run(self, domain_root: Path) -> None:
        from crsbench.build_images import (
            BENCHMARK_IMAGE_PREFIX,
            ImageBuildSummary,
            _discover_benchmarks,
            image_exists,
        )
        from crsbench.scripts.generate_tasks import generate_all_tasks

        # Extract built benchmarks from the build hook's summary
        built_benchmarks: set[str] | None = None
        summary = self._build_hook.summary
        if isinstance(summary, ImageBuildSummary) and summary.succeeded:
            built_benchmarks = summary.built_benchmark_ids
        else:
            # Build hook was skipped (images already exist) — detect which
            # L2 images are actually present so we only generate tasks for
            # benchmarks that have working images.
            benchmarks_dir = domain_root / _BENCHMARK_SUBDIR
            discovered = _discover_benchmarks(benchmarks_dir)
            existing = {
                b.name
                for b in discovered
                if image_exists(f"{BENCHMARK_IMAGE_PREFIX}:{b.name}")
            }
            if existing:
                built_benchmarks = existing
                logger.info(
                    "Build hook skipped — detected %d existing L2 images",
                    len(existing),
                )

        benchmarks_dir = domain_root / _BENCHMARK_SUBDIR
        output_dir = domain_root / _TASKS_SUBDIR

        generated = generate_all_tasks(
            benchmarks_dir,
            output_dir,
            built_benchmarks=built_benchmarks,
            dataset=self._dataset,
        )

        logger.info("Generated %d task YAML(s)", len(generated))
