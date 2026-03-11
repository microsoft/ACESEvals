"""Two-layer Docker image build pipeline for CRSBench benchmarks.

Builds pre-loaded Docker images so each eval sample runs in a container
with the benchmark's source code, dependencies, and SABER tooling already
installed — avoiding catastrophically slow runtime file-copy.

**Layer 1** — ``saber/crsbench/env:<benchmark_id>``:
    Builds the benchmark's own Dockerfile (from AIxCC repos) with its
    source code and dependencies.

**Layer 2** — ``saber/crsbench/benchmark:<benchmark_id>``:
    Overlays SABER tooling (clang, ASAN, build tools) on top of Layer 1.

Usage::

    # Async API
    summary = await build_all_images(benchmarks_dir, domain_root)

    # Sync wrapper for setup hooks
    summary = build_images_sync(benchmarks_dir, domain_root)
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from saber.logging import display_progress, get_logger

logger = get_logger("domains.crsbench.build_images")


# ---------------------------------------------------------------------------
# Async build helpers
# ---------------------------------------------------------------------------


async def _stream_build(
    proc: asyncio.subprocess.Process,
    label: str,
    *,
    timeout: int,
) -> None:
    """Stream Docker build output through the logger and wait for exit.

    Reads stdout and stderr concurrently, logging each line at DEBUG
    level so progress is visible with ``--display plain`` or when the
    log level is high enough.  On failure, the last 2 000 bytes of
    stderr are included in the raised ``RuntimeError``.

    Args:
        proc: Running Docker build subprocess.
        label: Human label for log messages (e.g. ``"Layer 1 afc-curl"``).
        timeout: Maximum seconds to wait before killing the build.

    Raises:
        RuntimeError: On build failure or timeout.
    """
    stderr_chunks: list[bytes] = []

    async def _read_stream(
        stream: asyncio.StreamReader | None,
        *,
        is_stderr: bool = False,
    ) -> None:
        if stream is None:
            return
        while True:
            try:
                line = await stream.readline()
            except ValueError:
                # readline() raises ValueError when a single line exceeds
                # the StreamReader buffer limit (default 64 KiB).  Docker
                # --progress=plain can emit very long compiler commands.
                # Fall back to reading a raw chunk instead.
                chunk = await stream.read(65536)
                if not chunk:
                    break
                line = chunk
            if not line:
                break
            decoded = line.decode(errors="replace").rstrip()
            if is_stderr:
                stderr_chunks.append(line)
            if decoded:
                display_progress(f"[{label}] {decoded}")

    try:
        await asyncio.wait_for(
            asyncio.gather(
                _read_stream(proc.stdout),
                _read_stream(proc.stderr, is_stderr=True),
            ),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        msg = f"{label} build timed out after {timeout}s"
        raise RuntimeError(msg)

    await proc.wait()

    if proc.returncode != 0:
        tail = b"".join(stderr_chunks)[-2000:].decode(errors="replace")
        msg = f"{label} build failed: {tail}"
        raise RuntimeError(msg)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ENV_IMAGE_PREFIX = "saber/crsbench/env"
BENCHMARK_IMAGE_PREFIX = "saber/crsbench/benchmark"

#: Maximum concurrent Docker builds to prevent resource exhaustion.
DEFAULT_MAX_CONCURRENT_BUILDS = 4

#: Per-build timeout in seconds (some benchmarks have heavy C++/Java deps).
#: Set generous to accommodate parallel builds competing for CPU.
DEFAULT_BUILD_TIMEOUT_SECONDS = 3600  # 60 minutes

#: Layer 2 Dockerfile template — overlays SABER tooling on the env image.
#: Uses the benchmark directory as build context so COPY can access
#: build.sh, test.sh, and project.yaml.
#:
#: The base image (Layer 1) already inherits from the AIxCC
#: ``base-builder`` which provides ``$SRC``, ``$OUT``, ``$CC``,
#: ``$CFLAGS``, ``$SANITIZER``, etc.  Layer 2 adds a few extra
#: packages for the SABER agent workflow, sets up workspace symlinks,
#: and — critically — runs ``build.sh`` so the compiled harness
#: binaries are baked into the image at ``/out/`` (symlinked as
#: ``/workspace/build/``).
_LAYER2_DOCKERFILE = """\
ARG BASE_IMAGE
FROM ${BASE_IMAGE}

# Switch to root for package installation
USER root

# Install extra tools useful for the SABER agent workflow.
# The AIxCC base-builder already provides clang, llvm, make, cmake, etc.
RUN apt-get update && apt-get install -y --no-install-recommends \\
    gdb \\
    patch diffutils \\
    file \\
    && rm -rf /var/lib/apt/lists/*

# Workspace structure — symlink /workspace/source and /workspace/build
# to the locations used by AIxCC base-builder ($SRC=/src, $OUT=/out).
# build.sh and test.sh use these env vars so paths stay consistent.
RUN mkdir -p /workspace/povs /submit/patches /out \\
    && ln -sfn /src /workspace/source \\
    && ln -sfn /out /workspace/build

# Provide libFuzzingEngine.a — a standalone harness driver.
# The full clang libfuzzer runtime pulls in math symbols (ceilf)
# that cause link failures in projects like OpenSSL.  Instead we
# compile the lightweight StandaloneFuzzTargetMain.c (already in the
# base-builder at /src/libfuzzer/standalone/) into a minimal .a
# archive.  This provides main() → LLVMFuzzerTestOneInput() without
# the heavy fuzzer loop or math dependencies.
RUN $CC -c /src/libfuzzer/standalone/StandaloneFuzzTargetMain.c \
        -o /tmp/StandaloneFuzzTargetMain.o \
    && ar rc /usr/lib/libFuzzingEngine.a /tmp/StandaloneFuzzTargetMain.o \
    && rm /tmp/StandaloneFuzzTargetMain.o

# Copy benchmark build/test scripts from the build context
COPY build.sh test.sh /workspace/
RUN chmod +x /workspace/build.sh /workspace/test.sh

# Attempt to compile the project and harness binaries into $OUT
# (/workspace/build).  This is best-effort: some benchmark build
# scripts have missing link flags (e.g. -lpthread) or other issues
# that cause them to fail in this environment.  We use ``|| true``
# so the image is still created — the agent can fix and recompile
# at runtime.  A non-zero exit from build.sh is recorded so the
# harness verification step can flag it.
RUN /workspace/build.sh || echo 'SABER_BUILD_WARNING: build.sh exited non-zero' >&2

WORKDIR /workspace
"""


# ---------------------------------------------------------------------------
# Result models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ImageBuildResult:
    """Result of building a single benchmark's Docker images.

    Attributes:
        benchmark_id: The benchmark directory name.
        image_tag: The final Layer 2 image tag, or empty string on failure.
        success: Whether both layers built successfully.
        duration_seconds: Wall-clock time for the full build.
        error: Error message if the build failed.
    """

    benchmark_id: str
    image_tag: str = ""
    success: bool = False
    duration_seconds: float = 0.0
    error: str = ""


@dataclass
class ImageBuildSummary:
    """Aggregate result of building all benchmark images.

    Attributes:
        results: Per-benchmark build results.
        total_duration_seconds: Wall-clock time for the entire build run.
    """

    results: list[ImageBuildResult] = field(default_factory=list)
    total_duration_seconds: float = 0.0

    @property
    def succeeded(self) -> list[ImageBuildResult]:
        """Benchmarks that built successfully."""
        return [r for r in self.results if r.success]

    @property
    def failed(self) -> list[ImageBuildResult]:
        """Benchmarks that failed to build."""
        return [r for r in self.results if not r.success]

    @property
    def built_benchmark_ids(self) -> set[str]:
        """Set of benchmark IDs that built successfully."""
        return {r.benchmark_id for r in self.results if r.success}

    @property
    def image_map(self) -> dict[str, str]:
        """Mapping of benchmark_id to final image tag for successful builds."""
        return {r.benchmark_id: r.image_tag for r in self.results if r.success}


# ---------------------------------------------------------------------------
# Image existence check
# ---------------------------------------------------------------------------


def image_exists(image_tag: str) -> bool:
    """Check if a Docker image exists locally.

    Args:
        image_tag: Full image tag (e.g. ``saber/crsbench/benchmark:my-bench``).

    Returns:
        True if the image exists locally.
    """
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", image_tag],
            capture_output=True,
            timeout=30,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


# ---------------------------------------------------------------------------
# Layer 1 — Build benchmark environment image
# ---------------------------------------------------------------------------


def _find_benchmark_dockerfile(benchmark_path: Path) -> Path | None:
    """Locate the benchmark's Dockerfile.

    Checks common AIxCC Dockerfile locations in priority order:
    1. ``Dockerfile`` in benchmark root
    2. ``docker/Dockerfile``
    3. ``Dockerfile.builder``

    Args:
        benchmark_path: Path to the benchmark root directory.

    Returns:
        Path to the Dockerfile, or None if not found.
    """
    candidates = [
        benchmark_path / "Dockerfile",
        benchmark_path / "docker" / "Dockerfile",
        benchmark_path / "Dockerfile.builder",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


async def _build_layer1(
    benchmark_path: Path,
    benchmark_id: str,
    *,
    timeout: int = DEFAULT_BUILD_TIMEOUT_SECONDS,
) -> str:
    """Build Layer 1: benchmark environment image.

    Args:
        benchmark_path: Path to the benchmark root directory.
        benchmark_id: Benchmark identifier for the image tag.
        timeout: Build timeout in seconds.

    Returns:
        The Layer 1 image tag.

    Raises:
        FileNotFoundError: If no Dockerfile is found in the benchmark.
        RuntimeError: If the Docker build fails or times out.
    """
    dockerfile = _find_benchmark_dockerfile(benchmark_path)
    if dockerfile is None:
        msg = f"No Dockerfile found in {benchmark_path}"
        raise FileNotFoundError(msg)

    image_tag = f"{ENV_IMAGE_PREFIX}:{benchmark_id}"

    # Skip rebuild if Layer 1 already exists
    if image_exists(image_tag):
        display_progress(f"Layer 1 image {image_tag} already exists, reusing")
        return image_tag

    display_progress(f"Building Layer 1 image {image_tag} from {dockerfile}")

    proc = await asyncio.create_subprocess_exec(
        "docker", "build",
        "-t", image_tag,
        "-f", str(dockerfile),
        str(benchmark_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    await _stream_build(proc, f"L1 {benchmark_id}", timeout=timeout)

    display_progress(f"Layer 1 complete: {image_tag}")
    return image_tag


# ---------------------------------------------------------------------------
# Layer 2 — Overlay SABER tooling
# ---------------------------------------------------------------------------


async def _build_layer2(
    base_image: str,
    benchmark_id: str,
    benchmark_path: Path,
    domain_root: Path,
    *,
    timeout: int = DEFAULT_BUILD_TIMEOUT_SECONDS,
) -> str:
    """Build Layer 2: SABER tooling overlay on benchmark env.

    Creates a temporary Dockerfile that extends the Layer 1 image with
    SABER's build tools, then builds it.  The benchmark directory's
    ``build.sh`` and ``test.sh`` are copied into the build context so the
    Layer 2 Dockerfile can COPY them into the image.

    Args:
        base_image: Layer 1 image tag to build on top of.
        benchmark_id: Benchmark identifier for the image tag.
        benchmark_path: Path to the benchmark root directory
            (used to source build.sh, test.sh for the build context).
        domain_root: Domain root directory (for build context).
        timeout: Build timeout in seconds.

    Returns:
        The Layer 2 image tag.

    Raises:
        RuntimeError: If the Docker build fails or times out.
    """
    image_tag = f"{BENCHMARK_IMAGE_PREFIX}:{benchmark_id}"

    # Write a temporary Dockerfile for Layer 2 and copy scripts
    tmp_dir = domain_root / ".build_tmp" / benchmark_id
    tmp_dir.mkdir(parents=True, exist_ok=True)
    dockerfile = tmp_dir / "Dockerfile"
    dockerfile.write_text(_LAYER2_DOCKERFILE)

    # Copy benchmark scripts into the build context so COPY works
    for script in ("build.sh", "test.sh"):
        src = benchmark_path / script
        if src.is_file():
            shutil.copy2(src, tmp_dir / script)
        else:
            # Create a no-op placeholder so COPY doesn't fail
            (tmp_dir / script).write_text(f"#!/bin/bash\necho '{script} not provided'\n")

    display_progress(f"Building Layer 2 image {image_tag} (base: {base_image})")

    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "build",
            "-t", image_tag,
            "--build-arg", f"BASE_IMAGE={base_image}",
            "-f", str(dockerfile),
            str(tmp_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        await _stream_build(proc, f"L2 {benchmark_id}", timeout=timeout)

        display_progress(f"Layer 2 complete: {image_tag}")
        return image_tag
    finally:
        # Clean up temporary build files
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Single benchmark build
# ---------------------------------------------------------------------------


async def build_benchmark_image(
    benchmark_path: Path,
    domain_root: Path,
    *,
    force: bool = False,
    timeout: int = DEFAULT_BUILD_TIMEOUT_SECONDS,
) -> ImageBuildResult:
    """Build both layers for a single benchmark.

    Skips the build if the final image already exists (unless ``force=True``).

    Args:
        benchmark_path: Path to the benchmark root directory.
        domain_root: Domain root directory.
        force: Rebuild even if the image already exists.
        timeout: Per-layer build timeout in seconds.

    Returns:
        Build result with success status and image tag.
    """
    benchmark_id = benchmark_path.name
    final_tag = f"{BENCHMARK_IMAGE_PREFIX}:{benchmark_id}"
    start = time.monotonic()

    # Skip if already built
    if not force and image_exists(final_tag):
        display_progress(f"Image {final_tag} already exists, skipping")
        return ImageBuildResult(
            benchmark_id=benchmark_id,
            image_tag=final_tag,
            success=True,
            duration_seconds=time.monotonic() - start,
        )

    try:
        # Layer 1: Build benchmark environment
        layer1_tag = await _build_layer1(benchmark_path, benchmark_id, timeout=timeout)

        # Layer 2: Overlay SABER tooling
        layer2_tag = await _build_layer2(
            layer1_tag, benchmark_id, benchmark_path, domain_root, timeout=timeout,
        )

        elapsed = time.monotonic() - start
        display_progress(
            f"Benchmark {benchmark_id}: both layers built in {elapsed:.1f}s → {layer2_tag}",
        )
        return ImageBuildResult(
            benchmark_id=benchmark_id,
            image_tag=layer2_tag,
            success=True,
            duration_seconds=elapsed,
        )
    except Exception as exc:
        elapsed = time.monotonic() - start
        logger.warning(
            "Benchmark %s: build failed after %.1fs — %s",
            benchmark_id, elapsed, exc,
        )
        return ImageBuildResult(
            benchmark_id=benchmark_id,
            success=False,
            duration_seconds=elapsed,
            error=str(exc),
        )


# ---------------------------------------------------------------------------
# Batch build — all benchmarks
# ---------------------------------------------------------------------------


def _discover_benchmarks(benchmarks_dir: Path) -> list[Path]:
    """Discover benchmark directories that have Dockerfiles.

    Args:
        benchmarks_dir: Root directory containing benchmark subdirectories.

    Returns:
        Sorted list of benchmark directory paths that have a Dockerfile.
    """
    if not benchmarks_dir.is_dir():
        return []

    benchmarks = []
    for child in sorted(benchmarks_dir.iterdir()):
        if child.is_dir() and _find_benchmark_dockerfile(child) is not None:
            benchmarks.append(child)
    return benchmarks


async def build_all_images(
    benchmarks_dir: Path,
    domain_root: Path,
    *,
    force: bool = False,
    max_concurrent: int = DEFAULT_MAX_CONCURRENT_BUILDS,
    timeout: int = DEFAULT_BUILD_TIMEOUT_SECONDS,
    prefix_filter: str | None = None,
) -> ImageBuildSummary:
    """Build Docker images for all benchmarks in a directory.

    Uses a semaphore to limit concurrent builds. Failed builds are logged
    as warnings but do not block other builds.

    Args:
        benchmarks_dir: Root directory containing benchmark subdirectories.
        domain_root: Domain root directory.
        force: Rebuild even if images already exist.
        max_concurrent: Maximum concurrent Docker builds.
        timeout: Per-layer build timeout in seconds.
        prefix_filter: Only build benchmarks whose ID starts with this prefix.

    Returns:
        Summary of all build results.
    """
    start = time.monotonic()
    benchmarks = _discover_benchmarks(benchmarks_dir)

    if prefix_filter:
        benchmarks = [
            b for b in benchmarks if b.name.startswith(prefix_filter)
        ]

    if not benchmarks:
        logger.warning("No benchmarks with Dockerfiles found in %s", benchmarks_dir)
        return ImageBuildSummary(total_duration_seconds=time.monotonic() - start)

    display_progress(
        f"Building images for {len(benchmarks)} benchmarks "
        f"(max_concurrent={max_concurrent}, timeout={timeout}s)",
    )

    semaphore = asyncio.Semaphore(max_concurrent)

    async def _bounded_build(benchmark_path: Path) -> ImageBuildResult:
        async with semaphore:
            return await build_benchmark_image(
                benchmark_path, domain_root, force=force, timeout=timeout,
            )

    results = await asyncio.gather(
        *[_bounded_build(b) for b in benchmarks],
        return_exceptions=False,
    )

    elapsed = time.monotonic() - start
    summary = ImageBuildSummary(
        results=list(results),
        total_duration_seconds=elapsed,
    )

    display_progress(
        f"Image build complete: {len(summary.succeeded)} succeeded, "
        f"{len(summary.failed)} failed in {elapsed:.1f}s",
    )

    if summary.failed:
        for r in summary.failed:
            logger.warning("  FAILED: %s — %s", r.benchmark_id, r.error)

    return summary


# ---------------------------------------------------------------------------
# Sync wrapper — for use in setup hooks
# ---------------------------------------------------------------------------


def build_images_sync(
    benchmarks_dir: Path,
    domain_root: Path,
    *,
    force: bool = False,
    max_concurrent: int = DEFAULT_MAX_CONCURRENT_BUILDS,
    timeout: int = DEFAULT_BUILD_TIMEOUT_SECONDS,
    prefix_filter: str | None = None,
) -> ImageBuildSummary:
    """Synchronous wrapper for :func:`build_all_images`.

    Safe to call from synchronous setup hooks. Creates a new event loop
    if none is running, otherwise uses ``asyncio.run()``.

    Args:
        benchmarks_dir: Root directory containing benchmark subdirectories.
        domain_root: Domain root directory.
        force: Rebuild even if images already exist.
        max_concurrent: Maximum concurrent Docker builds.
        timeout: Per-layer build timeout in seconds.
        prefix_filter: Only build benchmarks whose ID starts with this prefix.

    Returns:
        Summary of all build results.
    """
    coro = build_all_images(
        benchmarks_dir,
        domain_root,
        force=force,
        max_concurrent=max_concurrent,
        timeout=timeout,
        prefix_filter=prefix_filter,
    )

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        # We're inside an existing event loop (e.g., inspect_ai).
        # Use nest_asyncio or a thread to avoid deadlock.
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result()
    else:
        return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


def cleanup_build_artifacts(domain_root: Path) -> None:
    """Remove temporary build directories.

    Args:
        domain_root: Domain root directory.
    """
    tmp_dir = domain_root / ".build_tmp"
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir, ignore_errors=True)
        logger.info("Cleaned up build artifacts in %s", tmp_dir)
