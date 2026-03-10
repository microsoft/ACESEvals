"""Docker image build primitives for CRSBench benchmarks.

Builds two-layer Docker images for each benchmark:
- **Layer 1 (env):** The benchmark's own Dockerfile (AIxCC base + per-project deps + source)
- **Layer 2 (final):** Generated overlay with SABER agent tooling + build cache warming

Usage::

    from crsbench.scripts.build_images import build_all_benchmark_images

    summary = await build_all_benchmark_images(benchmarks_dir)
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

logger = logging.getLogger("crsbench.scripts.build_images")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_IMAGE_REPO = "saber/crsbench/benchmark"
_ENV_IMAGE_REPO = "saber/crsbench/env"

# Path to the canonical SABER tooling Dockerfile (single source of truth)
_SABER_DOCKERFILE = (
    Path(__file__).resolve().parents[3]
    / "external"
    / "saber"
    / "docker"
    / "Dockerfile.saber_sandbox"
)

# Hardcoded fallback in case the Dockerfile is unavailable at build time
_SABER_TOOLING_FALLBACK = """\
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

# Install Python packages for basic execution and agent SDKs
RUN uv pip install --system --no-cache \\
    requests \\
    github-copilot-sdk==0.1.32 \\
    claude-code-sdk
"""

# Layer 1 ignores: staged/ is only used by Layer 2, .aixcc/ is metadata
_DOCKERIGNORE_LAYER1 = """\
staged/
.aixcc/
Dockerfile.saber
"""

# Layer 2 ignores: pkgs/ and tarballs are only used by Layer 1
_DOCKERIGNORE_LAYER2 = """\
pkgs/
.aixcc/
*.tar.gz
*.tar.bz2
*.tar.xz
Dockerfile
"""


# ---------------------------------------------------------------------------
# 1.1 — Models
# ---------------------------------------------------------------------------


class ImageBuildResult(BaseModel):
    """Result of a single Docker image build attempt."""

    model_config = ConfigDict(frozen=True)

    benchmark_id: str
    image_tag: str
    success: bool
    skipped: bool
    error_message: str | None = None
    duration_seconds: float = 0.0


class ImageBuildSummary(BaseModel):
    """Aggregate results from building all benchmark images."""

    model_config = ConfigDict(frozen=True)

    total: int
    built: int
    skipped: int
    failed: int
    results: tuple[ImageBuildResult, ...]


# ---------------------------------------------------------------------------
# 1.2 — Tag helpers
# ---------------------------------------------------------------------------


def image_tag_for_benchmark(benchmark_id: str) -> str:
    """Return the Docker image tag for a benchmark.

    Args:
        benchmark_id: Benchmark directory name (e.g. ``"afc-curl-delta-01"``).

    Returns:
        Full image tag (e.g. ``"saber/crsbench/benchmark:afc-curl-delta-01"``).
    """
    return f"{_IMAGE_REPO}:{benchmark_id}"


def env_image_tag_for_benchmark(benchmark_id: str) -> str:
    """Return the Layer 1 env image tag for a benchmark.

    Args:
        benchmark_id: Benchmark directory name.

    Returns:
        Full image tag (e.g. ``"saber/crsbench/env:afc-curl-delta-01"``).
    """
    return f"{_ENV_IMAGE_REPO}:{benchmark_id}"


# ---------------------------------------------------------------------------
# 1.3 — SABER tooling & overlay Dockerfile
# ---------------------------------------------------------------------------


def _read_saber_tooling() -> str:
    """Read the SABER agent tooling section from Dockerfile.saber_sandbox.

    Extracts lines 13–31 (the tooling RUN/COPY commands) from the
    canonical Dockerfile.  Falls back to a hardcoded copy if the file
    is unavailable (e.g. in CI without the full repo checkout).

    Note: The hardcoded line range (12:31) covers the same content as
    ``_SABER_TOOLING_FALLBACK``, so if the range becomes stale the
    function degrades gracefully to the fallback string.

    Returns:
        Dockerfile fragment with the SABER tooling instructions.
    """
    if not _SABER_DOCKERFILE.exists():
        logger.warning(
            "Cannot read %s — using hardcoded fallback",
            _SABER_DOCKERFILE,
        )
        return _SABER_TOOLING_FALLBACK

    lines = _SABER_DOCKERFILE.read_text().splitlines()
    # Extract lines 13–31 (0-indexed 12–30) — the tooling section
    tooling_lines = lines[12:31]
    return (
        "# ── SABER agent tooling ──────────────────────────────────────────────\n"
        + "\n".join(tooling_lines)
        + "\n"
    )


def generate_overlay_dockerfile(env_image_tag: str) -> str:
    """Generate the Layer 2 Dockerfile that adds SABER tooling and runs build.sh.

    Extends the per-benchmark env image (Layer 1) with:
    - Node.js 22 + Copilot CLI + Claude Code CLI
    - uv + Python agent SDKs
    - Staged source copied to ``/workspace/source/``
    - Layer 1 ``/src/`` removed to avoid duplicate source in image layers
    - ``build.sh`` executed (non-fatal) to warm the build cache

    Args:
        env_image_tag: Layer 1 env image tag to extend.

    Returns:
        Dockerfile content as a string.
    """
    tooling = _read_saber_tooling()
    return (
        f"FROM {env_image_tag}\n"
        f"{tooling}"
        "# ── Workspace setup + build cache warming ────────────────────────\n"
        "# Remove Layer 1 source copy at /src/ to avoid duplicate data\n"
        "RUN rm -rf /src/* 2>/dev/null || true\n"
        "COPY staged/ /workspace/source/\n"
        "ENV SRC=/workspace/source OUT=/workspace/build PYTHONUNBUFFERED=1\n"
        "RUN mkdir -p /workspace/build /workspace/povs /submit/patches && \\\n"
        "    cd /workspace/source && chmod +x build.sh test.sh 2>/dev/null; \\\n"
        "    bash build.sh || true\n"
        "WORKDIR /workspace\n"
    )


# ---------------------------------------------------------------------------
# 1.4 — Docker command helpers
# ---------------------------------------------------------------------------


async def _run_docker_cmd(
    args: list[str],
    *,
    cwd: Path | None = None,
    timeout: float = 900.0,
) -> tuple[int, str, str]:
    """Run a docker command and return (returncode, stdout, stderr).

    Args:
        args: Command arguments (e.g. ``["docker", "image", "inspect", tag]``).
        cwd: Working directory for the subprocess.
        timeout: Timeout in seconds (default: 15 minutes).

    Returns:
        Tuple of (return code, stdout, stderr).
    """
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return 1, "", f"Timeout after {timeout}s"
    assert proc.returncode is not None  # guaranteed after communicate()
    return proc.returncode, stdout.decode(), stderr.decode()


async def image_exists(image_tag: str) -> bool:
    """Check if a Docker image exists locally.

    Args:
        image_tag: Full image tag to check.

    Returns:
        True if the image exists locally.
    """
    returncode, _, _ = await _run_docker_cmd(
        ["docker", "image", "inspect", image_tag],
    )
    return returncode == 0


# ---------------------------------------------------------------------------
# 1.4b — .dockerignore helpers
# ---------------------------------------------------------------------------


def _write_dockerignore(benchmark_dir: Path, *, layer: Literal[1, 2]) -> None:
    """Write a ``.dockerignore`` to minimize Docker build context for the given layer.

    Args:
        benchmark_dir: Path to the benchmark directory.
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
# 1.5 — build_benchmark_image
# ---------------------------------------------------------------------------


async def build_benchmark_image(
    benchmark_dir: Path,
    *,
    force: bool = False,
) -> ImageBuildResult:
    """Build a two-layer Docker image for a single benchmark.

    Layer 1 (env): Builds the benchmark's own Dockerfile (AIxCC base +
    per-project deps + source).  Skipped if the env image already exists.

    Layer 2 (final): Generated overlay Dockerfile that adds SABER agent
    tooling, copies staged source to ``/workspace/source/``, and runs
    ``build.sh`` to warm the cache.

    Args:
        benchmark_dir: Path to the benchmark directory (must contain
            ``Dockerfile``, ``staged/``, ``build.sh``).
        force: When True, rebuild both layers even if images exist.

    Returns:
        Build result with success/failure status.
    """
    benchmark_id = benchmark_dir.name
    final_tag = image_tag_for_benchmark(benchmark_id)
    env_tag = env_image_tag_for_benchmark(benchmark_id)
    start = time.monotonic()

    # ── Validate prerequisites ────────────────────────────────────
    staged = benchmark_dir / "staged"
    if not staged.exists() or not staged.is_dir() or not any(staged.iterdir()):
        return ImageBuildResult(
            benchmark_id=benchmark_id,
            image_tag=final_tag,
            success=False,
            skipped=False,
            error_message=f"No staged/ directory in {benchmark_dir}",
        )

    benchmark_dockerfile = benchmark_dir / "Dockerfile"
    if not benchmark_dockerfile.exists():
        return ImageBuildResult(
            benchmark_id=benchmark_id,
            image_tag=final_tag,
            success=False,
            skipped=False,
            error_message=f"No Dockerfile in {benchmark_dir}",
        )

    # ── Skip if final image already exists ────────────────────────
    if not force and await image_exists(final_tag):
        return ImageBuildResult(
            benchmark_id=benchmark_id,
            image_tag=final_tag,
            success=True,
            skipped=True,
        )

    # ── Layer 1: Build env image (benchmark's own Dockerfile) ─────
    if force or not await image_exists(env_tag):
        _write_dockerignore(benchmark_dir, layer=1)
        try:
            returncode, _, stderr = await _run_docker_cmd(
                [
                    "docker",
                    "build",
                    "-t",
                    env_tag,
                    "-f",
                    str(benchmark_dockerfile),
                    str(benchmark_dir),
                ],
                cwd=benchmark_dir,
                timeout=900.0,
            )
        except asyncio.TimeoutError:
            elapsed = time.monotonic() - start
            return ImageBuildResult(
                benchmark_id=benchmark_id,
                image_tag=final_tag,
                success=False,
                skipped=False,
                error_message=f"Timeout building Layer 1 (env) for {benchmark_id}",
                duration_seconds=elapsed,
            )
        finally:
            _cleanup_dockerignore(benchmark_dir)

        if returncode != 0:
            elapsed = time.monotonic() - start
            logger.warning(
                "Layer 1 (env) build failed for %s (%.1fs): %s",
                benchmark_id,
                elapsed,
                stderr[:500],
            )
            return ImageBuildResult(
                benchmark_id=benchmark_id,
                image_tag=final_tag,
                success=False,
                skipped=False,
                error_message=f"Layer 1 (env) failed: {stderr[:1000]}",
                duration_seconds=elapsed,
            )

    # ── Ensure build.sh exists in staged/ for the overlay Dockerfile ──
    # Some benchmarks may not ship a build.sh; create a no-op to prevent
    # warnings during the Layer 2 ``bash build.sh || true`` step.
    staged_build_sh = staged / "build.sh"
    if not staged_build_sh.exists():
        staged_build_sh.write_text("#!/bin/bash\n# No build script provided\nexit 0\n")
        staged_build_sh.chmod(0o755)

    # ── Layer 2: Build final image (SABER tooling + build cache) ──
    overlay_path = benchmark_dir / "Dockerfile.saber"
    overlay_path.write_text(generate_overlay_dockerfile(env_tag))
    _write_dockerignore(benchmark_dir, layer=2)

    try:
        returncode, _, stderr = await _run_docker_cmd(
            [
                "docker",
                "build",
                "-t",
                final_tag,
                "-f",
                str(overlay_path),
                str(benchmark_dir),
            ],
            cwd=benchmark_dir,
            timeout=900.0,
        )
    except asyncio.TimeoutError:
        elapsed = time.monotonic() - start
        return ImageBuildResult(
            benchmark_id=benchmark_id,
            image_tag=final_tag,
            success=False,
            skipped=False,
            error_message=f"Timeout building Layer 2 (final) for {benchmark_id}",
            duration_seconds=elapsed,
        )
    finally:
        if overlay_path.exists():
            overlay_path.unlink()
        _cleanup_dockerignore(benchmark_dir)

    elapsed = time.monotonic() - start

    if returncode != 0:
        logger.warning(
            "Layer 2 (final) build failed for %s (%.1fs): %s",
            benchmark_id,
            elapsed,
            stderr[:500],
        )
        return ImageBuildResult(
            benchmark_id=benchmark_id,
            image_tag=final_tag,
            success=False,
            skipped=False,
            error_message=f"Layer 2 (final) failed: {stderr[:1000]}",
            duration_seconds=elapsed,
        )

    return ImageBuildResult(
        benchmark_id=benchmark_id,
        image_tag=final_tag,
        success=True,
        skipped=False,
        duration_seconds=elapsed,
    )


# ---------------------------------------------------------------------------
# 1.6 — build_all_benchmark_images
# ---------------------------------------------------------------------------


async def build_all_benchmark_images(
    benchmarks_dir: Path,
    *,
    datasets: list[str] | None = None,
    force: bool = False,
    rebuild_prefix: str | None = None,
    max_concurrency: int = 4,
) -> ImageBuildSummary:
    """Build two-layer Docker images for all benchmarks in a directory.

    Args:
        benchmarks_dir: Root directory containing benchmark subdirectories.
        datasets: Optional list of benchmark names to build. ``None`` = all.
        force: When True, rebuild all images regardless of existence.
        rebuild_prefix: When set, force-rebuild only benchmarks whose
            ID starts with this prefix.
        max_concurrency: Maximum number of concurrent builds.

    Returns:
        Summary of build results.
    """
    from crsbench.setup import _list_benchmark_dirs

    dirs = _list_benchmark_dirs(benchmarks_dir, datasets)
    if not dirs:
        return ImageBuildSummary(
            total=0,
            built=0,
            skipped=0,
            failed=0,
            results=(),
        )

    semaphore = asyncio.Semaphore(max_concurrency)
    total = len(dirs)

    async def _build_one(idx: int, bench_dir: Path) -> ImageBuildResult:
        benchmark_id = bench_dir.name
        should_force = force or (
            rebuild_prefix is not None and benchmark_id.startswith(rebuild_prefix)
        )
        logger.info(
            "[crsbench] building %s (%d/%d)...",
            benchmark_id,
            idx + 1,
            total,
        )
        t0 = time.monotonic()
        try:
            async with semaphore:
                return await build_benchmark_image(
                    bench_dir,
                    force=should_force,
                )
        except Exception as exc:
            elapsed = time.monotonic() - t0
            logger.error(
                "Build crashed for %s: %s",
                benchmark_id,
                exc,
            )
            return ImageBuildResult(
                benchmark_id=benchmark_id,
                image_tag=image_tag_for_benchmark(benchmark_id),
                success=False,
                skipped=False,
                error_message=f"Build crashed: {exc}",
                duration_seconds=elapsed,
            )

    tasks = [_build_one(i, d) for i, d in enumerate(dirs)]
    results = await asyncio.gather(*tasks)

    built = sum(1 for r in results if r.success and not r.skipped)
    skipped = sum(1 for r in results if r.skipped)
    failed = sum(1 for r in results if not r.success)

    return ImageBuildSummary(
        total=total,
        built=built,
        skipped=skipped,
        failed=failed,
        results=tuple(results),
    )
