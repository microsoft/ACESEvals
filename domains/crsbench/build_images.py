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
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from saber.logging import display_progress, get_logger

try:
    from rich.console import Console, Group
    from rich.live import Live
    from rich.progress import (
        BarColumn,
        MofNCompleteColumn,
        Progress,
        SpinnerColumn,
        TextColumn,
        TimeElapsedColumn,
    )
    from rich.text import Text as RichText

    _HAS_RICH = True
except ImportError:
    _HAS_RICH = False

logger = get_logger("domains.crsbench.build_images")


# ---------------------------------------------------------------------------
# Build-phase detection
# ---------------------------------------------------------------------------


def _detect_build_phase(line: str) -> str | None:
    """Detect the current build phase from a Docker build output line.

    Returns a short human-readable status string when a recognisable
    build step is detected, or ``None`` otherwise.
    """
    lower = line.lower()
    if "apt-get" in lower:
        return "installing packages…"
    if "/workspace/build.sh" in lower:
        return "compiling project…"
    if "standalonefuzztargetmain" in lower or "libfuzzingengine" in lower:
        return "building fuzzer engine…"
    if "offline-cache.gradle" in lower:
        return "configuring Gradle cache…"
    if "gradle" in lower and ("build" in lower or "compile" in lower):
        return "building with Gradle…"
    if "mvn " in lower or "maven" in lower:
        return "building with Maven…"
    if "cmake" in lower:
        return "running cmake…"
    return None


# ---------------------------------------------------------------------------
# Async build helpers
# ---------------------------------------------------------------------------


async def _stream_build(
    proc: asyncio.subprocess.Process,
    label: str,
    *,
    timeout: int,
    quiet: bool = False,
    status_callback: Callable[[str], None] | None = None,
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
        quiet: If True, suppress per-line ``display_progress`` output.
        status_callback: Optional callback invoked with a short phase
            description whenever a recognisable build step is detected.

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
            if decoded and not quiet:
                display_progress(f"[{label}] {decoded}")
            if decoded and status_callback is not None:
                phase = _detect_build_phase(decoded)
                if phase is not None:
                    status_callback(phase)

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

#: Layer 1 .dockerignore — exclude staged/ (only used by Layer 2) and .aixcc/
_DOCKERIGNORE_LAYER1 = """\
staged/
.aixcc/
Dockerfile.saber
"""

#: Layer 2 .dockerignore — exclude pkgs/ and tarballs (only used by Layer 1)
_DOCKERIGNORE_LAYER2 = """\
pkgs/
.aixcc/
*.tar.gz
*.tar.bz2
*.tar.xz
Dockerfile
"""

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
_LAYER2_TEMPLATE = """\
FROM __ENV_IMAGE_TAG__

# Switch to root for package installation
USER root

# Install extra tools useful for the SABER agent workflow.
# The AIxCC base-builder already provides clang, llvm, make, cmake, etc.
RUN apt-get update && apt-get install -y --no-install-recommends \\
    gdb \\
    patch diffutils \\
    file \\
    && rm -rf /var/lib/apt/lists/*

# ── SABER agent tooling ──────────────────────────────────────────────
# Install Node.js 22 LTS (required by Copilot CLI and Claude Code CLI)
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \\
    apt-get install -y --no-install-recommends nodejs && \\
    rm -rf /var/lib/apt/lists/*

# Install agent CLI tools globally via npm
RUN npm install -g --ignore-scripts \\
        @github/copilot \\
        @anthropic-ai/claude-code && \\
    npm cache clean --force

# Install uv package manager
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Install Python 3.11 via uv — the base images ship Python 3.10 but
# github-copilot-sdk and claude-code-sdk require Python >= 3.11.
# uv downloads a standalone CPython build; no PPA or OS packages needed.
RUN uv python install 3.11

# Install Python packages for basic execution and agent SDKs into the
# system Python 3.10 (requests) and a Python 3.11 venv (agent SDKs).
# The venv's site-packages is added to PYTHONPATH so `import copilot`
# works from any script.
RUN uv pip install --system --no-cache requests
RUN uv venv /opt/saber-agent --python 3.11 \\
    && uv pip install --python /opt/saber-agent/bin/python --no-cache \\
        github-copilot-sdk==0.1.32 \\
        claude-code-sdk \\
        requests
ENV PYTHONPATH="/opt/saber-agent/lib/python3.11/site-packages:${PYTHONPATH:-}"
ENV PATH="/opt/saber-agent/bin:${PATH}"

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

# Workaround: snappy-java's Makefile runs ``cmake`` on snappy which
# pulls in Google Benchmark as a submodule.  Google Benchmark's
# CXXFeatureCheck.cmake uses ``try_run()`` to test std::regex support;
# when CXXFLAGS contains ``-fsanitize=address`` (injected by the
# Makefile for ASan), the compiled test binary hangs indefinitely.
# Disabling benchmark/test subdirectories via SNAPPY_CMAKE_OPTS
# prevents cmake from ever reaching the problematic ``try_run()``.
# This variable is only consumed by snappy-java's Makefile and is
# harmless for all other benchmarks.
ENV SNAPPY_CMAKE_OPTS="-DSNAPPY_BUILD_TESTS=OFF -DSNAPPY_BUILD_BENCHMARKS=OFF"

# Attempt to compile the project and harness binaries into $OUT
# (/workspace/build).  This is best-effort: some benchmark build
# scripts have missing link flags (e.g. -lpthread) or other issues
# that cause them to fail in this environment.  We use ``|| true``
# so the image is still created — the agent can fix and recompile
# at runtime.  A non-zero exit from build.sh is recorded so the
# harness verification step can flag it.
#
# We use ``bash /workspace/build.sh`` instead of a direct invocation
# because several benchmark scripts have the shebang
# ``#!/bin/bash -euo pipefail``.  On Linux the kernel passes
# everything after the interpreter path as a *single* argument to
# bash, so ``-euo pipefail`` becomes one argv entry.  Bash then
# tries ``set -o <script_path>`` and fails with "invalid option
# name".  Running via ``bash`` avoids the kernel shebang parsing
# entirely — the ``#!`` line is treated as a comment.
RUN apt-get update -qq && bash /workspace/build.sh || echo 'SABER_BUILD_WARNING: build step exited non-zero' >&2

# ── Git init — bake a clean initial commit into the image ────
# Agents use `git diff` to generate patches.  The initial commit
# captures the pre-agent source state so diffs are clean.
RUN cd /workspace/source && \\
    find . -mindepth 2 -name .git -exec rm -rf {} + 2>/dev/null || true && \\
    printf '*.o\\n*.a\\n*.so\\n*.class\\n*.jar\\n*.pyc\\n__pycache__/\\n' > .gitignore && \\
    git init && git checkout -b main 2>/dev/null || true && \\
    git config user.email 'sandbox@saber' && \\
    git config user.name 'sandbox' && \\
    git add -A && \\
    git commit --allow-empty -m 'initial' --quiet

# Install Gradle init script to prevent dynamic version re-resolution.
# Without this, Gradle tries to refresh expired cached version ranges
# from Maven Central, which fails in the offline sandbox environment.
RUN mkdir -p /root/.gradle/init.d && \
    cat > /root/.gradle/init.d/offline-cache.gradle <<'GRADLE_INIT'
// Installed by SABER Layer 2 — dependency cache is already warm from build.sh.
allprojects {
    configurations.all {
        resolutionStrategy {
            cacheDynamicVersionsFor 365, 'days'
            cacheChangingModulesFor 365, 'days'
        }
    }
}
GRADLE_INIT

WORKDIR /workspace
"""


# ---------------------------------------------------------------------------
# .dockerignore helpers
# ---------------------------------------------------------------------------


def _write_dockerignore(benchmark_dir: Path, *, layer: Literal[1, 2]) -> None:
    """Write a ``.dockerignore`` to minimize Docker build context.

    Args:
        benchmark_dir: Path to the benchmark directory (or build context dir).
        layer: 1 for env image build, 2 for overlay image build.
    """
    content = _DOCKERIGNORE_LAYER1 if layer == 1 else _DOCKERIGNORE_LAYER2
    (benchmark_dir / ".dockerignore").write_text(content)


def _cleanup_dockerignore(benchmark_dir: Path) -> None:
    """Remove the generated ``.dockerignore`` after building."""
    ignore_path = benchmark_dir / ".dockerignore"
    if ignore_path.exists():
        ignore_path.unlink()


# ---------------------------------------------------------------------------
# Tag helpers
# ---------------------------------------------------------------------------


def image_tag_for_benchmark(benchmark_id: str) -> str:
    """Return the full Docker image tag for a benchmark.

    Args:
        benchmark_id: Benchmark directory name (e.g. ``"afc-curl-delta-01"``).

    Returns:
        Full image tag (e.g. ``"saber/crsbench/benchmark:afc-curl-delta-01"``).
    """
    return f"{BENCHMARK_IMAGE_PREFIX}:{benchmark_id}"


def env_image_tag_for_benchmark(benchmark_id: str) -> str:
    """Return the Layer 1 env image tag for a benchmark.

    Args:
        benchmark_id: Benchmark directory name.

    Returns:
        Full image tag (e.g. ``"saber/crsbench/env:afc-curl-delta-01"``).
    """
    return f"{ENV_IMAGE_PREFIX}:{benchmark_id}"


# ---------------------------------------------------------------------------
# Overlay Dockerfile generation
# ---------------------------------------------------------------------------


def generate_overlay_dockerfile(env_image_tag: str) -> str:
    """Generate the Layer 2 Dockerfile that overlays SABER tooling on the env image.

    Extends the per-benchmark env image (Layer 1) with:
    - Extra CLI tools (gdb, patch, diffutils, file)
    - Node.js 22 + Copilot CLI + Claude Code CLI
    - uv + Python 3.11 + agent SDKs
    - Workspace symlinks (``/workspace/source`` → ``/src``) and
      ``libFuzzingEngine.a``
    - ``build.sh`` execution to warm the build cache
    - Git init to bake a clean initial commit for agent diffs
    - Gradle offline cache init script

    Args:
        env_image_tag: Layer 1 env image tag to extend.

    Returns:
        Dockerfile content as a string.
    """
    return _LAYER2_TEMPLATE.replace("__ENV_IMAGE_TAG__", env_image_tag)


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
    quiet: bool = False,
    status_callback: Callable[[str], None] | None = None,
) -> str:
    """Build Layer 1: benchmark environment image.

    Args:
        benchmark_path: Path to the benchmark root directory.
        benchmark_id: Benchmark identifier for the image tag.
        timeout: Build timeout in seconds.
        status_callback: Optional callback for phase updates.

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
        if not quiet:
            display_progress(f"Layer 1 image {image_tag} already exists, reusing")
        if status_callback is not None:
            status_callback("cached ✓")
        return image_tag

    if not quiet:
        display_progress(f"Building Layer 1 image {image_tag} from {dockerfile}")
    if status_callback is not None:
        status_callback("building env image…")

    _write_dockerignore(benchmark_path, layer=1)
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker",
            "build",
            "-t",
            image_tag,
            "-f",
            str(dockerfile),
            str(benchmark_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        await _stream_build(
            proc,
            f"L1 {benchmark_id}",
            timeout=timeout,
            quiet=quiet,
            status_callback=status_callback,
        )
    finally:
        _cleanup_dockerignore(benchmark_path)

    if not quiet:
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
    quiet: bool = False,
    status_callback: Callable[[str], None] | None = None,
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
    dockerfile.write_text(generate_overlay_dockerfile(base_image))

    # Copy benchmark scripts into the build context so COPY works
    for script in ("build.sh", "test.sh"):
        src = benchmark_path / script
        if src.is_file():
            shutil.copy2(src, tmp_dir / script)
        else:
            # Create a no-op placeholder so COPY doesn't fail
            (tmp_dir / script).write_text(
                f"#!/bin/bash\necho '{script} not provided'\n"
            )

    _write_dockerignore(tmp_dir, layer=2)

    if not quiet:
        display_progress(f"Building Layer 2 image {image_tag} (base: {base_image})")
    if status_callback is not None:
        status_callback("building overlay…")

    try:
        proc = await asyncio.create_subprocess_exec(
            "docker",
            "build",
            "-t",
            image_tag,
            "-f",
            str(dockerfile),
            str(tmp_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        await _stream_build(
            proc,
            f"L2 {benchmark_id}",
            timeout=timeout,
            quiet=quiet,
            status_callback=status_callback,
        )

        if not quiet:
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
    quiet: bool = False,
    status_callback: Callable[[str], None] | None = None,
) -> ImageBuildResult:
    """Build both layers for a single benchmark.

    Skips the build if the final image already exists (unless ``force=True``).

    Args:
        benchmark_path: Path to the benchmark root directory.
        domain_root: Domain root directory.
        force: Rebuild even if the image already exists.
        timeout: Per-layer build timeout in seconds.
        status_callback: Optional callback for phase updates.

    Returns:
        Build result with success status and image tag.
    """

    def _prefixed(prefix: str) -> Callable[[str], None] | None:
        """Wrap *status_callback* to prepend a layer prefix."""
        if status_callback is None:
            return None

        def _cb(status: str) -> None:
            status_callback(f"{prefix}: {status}")

        return _cb

    benchmark_id = benchmark_path.name
    final_tag = f"{BENCHMARK_IMAGE_PREFIX}:{benchmark_id}"
    start = time.monotonic()

    # Skip if already built
    if not force and image_exists(final_tag):
        if not quiet:
            display_progress(f"Image {final_tag} already exists, skipping")
        if status_callback is not None:
            status_callback("cached ✓")
        return ImageBuildResult(
            benchmark_id=benchmark_id,
            image_tag=final_tag,
            success=True,
            duration_seconds=time.monotonic() - start,
        )

    try:
        # Layer 1: Build benchmark environment
        layer1_tag = await _build_layer1(
            benchmark_path,
            benchmark_id,
            timeout=timeout,
            quiet=quiet,
            status_callback=_prefixed("L1"),
        )

        # Layer 2: Overlay SABER tooling
        layer2_tag = await _build_layer2(
            layer1_tag,
            benchmark_id,
            benchmark_path,
            domain_root,
            timeout=timeout,
            quiet=quiet,
            status_callback=_prefixed("L2"),
        )

        elapsed = time.monotonic() - start
        if not quiet:
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
            benchmark_id,
            elapsed,
            exc,
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
    benchmark_names: frozenset[str] | None = None,
    verbose: bool = False,
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
        benchmark_names: When provided, only build benchmarks whose directory
            name is in this set.  Applied after *prefix_filter*.

    Returns:
        Summary of all build results.
    """
    start = time.monotonic()
    benchmarks = _discover_benchmarks(benchmarks_dir)

    if prefix_filter:
        benchmarks = [b for b in benchmarks if b.name.startswith(prefix_filter)]

    if benchmark_names is not None:
        benchmarks = [b for b in benchmarks if b.name in benchmark_names]

    if not benchmarks:
        logger.warning("No benchmarks with Dockerfiles found in %s", benchmarks_dir)
        return ImageBuildSummary(total_duration_seconds=time.monotonic() - start)

    use_progress_bar = not verbose and _HAS_RICH

    if use_progress_bar:
        console = Console(stderr=True)
        failed_results: list[ImageBuildResult] = []
        active_builds: dict[str, str] = {}

        bar = Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TextColumn("•"),
            TimeElapsedColumn(),
        )
        overall_task = bar.add_task(
            "Building images",
            total=len(benchmarks),
        )

        def _render() -> Group:
            parts: list[RichText | Progress] = [bar]
            for name, status in list(active_builds.items()):
                parts.append(
                    RichText.from_markup(f"  [dim]{name}[/dim]  {status}"),
                )
            return Group(*parts)

        with Live(_render(), console=console, refresh_per_second=4) as live:
            semaphore = asyncio.Semaphore(max_concurrent)

            async def _bounded_build(benchmark_path: Path) -> ImageBuildResult:
                benchmark_name = benchmark_path.name

                async with semaphore:
                    active_builds[benchmark_name] = "starting…"
                    live.update(_render())

                    def _status_cb(status: str) -> None:
                        active_builds[benchmark_name] = status
                        live.update(_render())

                    result = await build_benchmark_image(
                        benchmark_path,
                        domain_root,
                        force=force,
                        timeout=timeout,
                        quiet=True,
                        status_callback=_status_cb,
                    )

                active_builds.pop(benchmark_name, None)

                if not result.success:
                    failed_results.append(result)
                    console.print(
                        f"  [red]✗[/red] {result.benchmark_id} "
                        f"({result.duration_seconds:.0f}s)",
                    )

                n_failed = len(failed_results)
                desc = "Building images"
                if n_failed:
                    desc += f" [red]({n_failed} failed)[/red]"
                bar.update(overall_task, advance=1, description=desc)
                live.update(_render())
                return result

            results = await asyncio.gather(
                *[_bounded_build(b) for b in benchmarks],
                return_exceptions=False,
            )

        elapsed = time.monotonic() - start
        summary = ImageBuildSummary(
            results=list(results),
            total_duration_seconds=elapsed,
        )

        # Print summary
        console.print(
            f"\n[bold]Build complete:[/bold] "
            f"[green]{len(summary.succeeded)} succeeded[/green], "
            f"[red]{len(summary.failed)} failed[/red] "
            f"in {elapsed:.1f}s",
        )

        # Dump detailed failure output
        if failed_results:
            console.print(f"\n[bold red]{'━' * 60}[/bold red]")
            console.print("[bold red]Failed builds:[/bold red]\n")
            for r in failed_results:
                console.print(
                    f"[bold]{r.benchmark_id}[/bold] "
                    f"(failed in {r.duration_seconds:.1f}s)",
                )
                console.print(f"[dim]{r.error}[/dim]\n")

        return summary

    # --- Verbose mode: original behavior ---
    display_progress(
        f"Building images for {len(benchmarks)} benchmarks "
        f"(max_concurrent={max_concurrent}, timeout={timeout}s)",
    )

    semaphore = asyncio.Semaphore(max_concurrent)

    async def _bounded_build(benchmark_path: Path) -> ImageBuildResult:
        async with semaphore:
            return await build_benchmark_image(
                benchmark_path,
                domain_root,
                force=force,
                timeout=timeout,
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
    benchmark_names: frozenset[str] | None = None,
    verbose: bool = False,
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
        benchmark_names: When provided, only build benchmarks whose directory
            name is in this set.  Applied after *prefix_filter*.

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
        benchmark_names=benchmark_names,
        verbose=verbose,
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
