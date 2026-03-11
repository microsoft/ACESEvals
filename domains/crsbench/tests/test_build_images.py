"""Tests for crsbench.build_images and crsbench.scripts.build_images."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from crsbench.scripts.build_images import (
    ImageBuildResult as ScriptsImageBuildResult,
    ImageBuildSummary as ScriptsImageBuildSummary,
    _cleanup_dockerignore,
    _read_saber_tooling,
    _write_dockerignore,
    build_all_benchmark_images,
    build_benchmark_image as scripts_build_benchmark_image,
    env_image_tag_for_benchmark,
    generate_overlay_dockerfile,
    image_exists as scripts_image_exists,
    image_tag_for_benchmark,
)

from crsbench.build_images import (
    BENCHMARK_IMAGE_PREFIX,
    DEFAULT_BUILD_TIMEOUT_SECONDS,
    DEFAULT_MAX_CONCURRENT_BUILDS,
    ENV_IMAGE_PREFIX,
    ImageBuildResult,
    ImageBuildSummary,
    _discover_benchmarks,
    _find_benchmark_dockerfile,
    build_all_images,
    build_benchmark_image,
    build_images_sync,
    cleanup_build_artifacts,
    image_exists,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_benchmark_dir(parent: Path, name: str) -> Path:
    """Create a minimal benchmark directory for testing.

    Creates ``staged/``, ``build.sh``, ``test.sh``, ``Dockerfile``, and
    ``.aixcc/`` (required by ``_is_benchmark_dir``).
    """
    bench = parent / name
    staged = bench / "staged"
    staged.mkdir(parents=True)
    (staged / "main.c").write_text("int main() { return 0; }")
    (bench / "build.sh").write_text("#!/bin/bash\necho build")
    (bench / "test.sh").write_text("#!/bin/bash\necho test")
    # .aixcc/ is required for _is_benchmark_dir() to recognize this dir
    (bench / ".aixcc").mkdir()
    # Minimal per-benchmark Dockerfile (like the real AIxCC ones)
    (bench / "Dockerfile").write_text(
        "FROM ghcr.io/aixcc-finals/base-builder:v1.3.0\nCOPY build.sh $SRC/\n"
    )
    return bench


def _mock_stream(data: bytes = b"") -> AsyncMock:
    """Create a mock async stream reader that yields *data* then EOF."""
    lines = data.split(b"\n") if data else []
    # readline() returns each line with \n, then b"" for EOF
    payloads = [line + b"\n" for line in lines if line] + [b""]
    stream = AsyncMock()
    stream.readline = AsyncMock(side_effect=payloads)
    return stream


def _mock_docker_proc(
    *,
    returncode: int = 0,
    stdout: bytes = b"ok\n",
    stderr: bytes = b"",
) -> AsyncMock:
    """Create a mock async subprocess with streaming stdout/stderr."""
    proc = AsyncMock()
    proc.returncode = returncode
    proc.stdout = _mock_stream(stdout)
    proc.stderr = _mock_stream(stderr)
    proc.wait = AsyncMock(return_value=returncode)
    proc.kill = MagicMock()
    return proc


# ===========================================================================
# Tests for crsbench.build_images (cherry-pick — dataclass-based pipeline)
# ===========================================================================


# ---------------------------------------------------------------------------
# ImageBuildResult tests
# ---------------------------------------------------------------------------


class TestImageBuildResult:
    def test_success_result(self) -> None:
        result = ImageBuildResult(
            benchmark_id="test-bench",
            image_tag="saber/crsbench/benchmark:test-bench",
            success=True,
            duration_seconds=10.5,
        )
        assert result.benchmark_id == "test-bench"
        assert result.image_tag == "saber/crsbench/benchmark:test-bench"
        assert result.success is True
        assert result.duration_seconds == 10.5
        assert result.error == ""

    def test_failure_result(self) -> None:
        result = ImageBuildResult(
            benchmark_id="bad-bench",
            success=False,
            error="Build exploded",
        )
        assert result.success is False
        assert result.image_tag == ""
        assert result.error == "Build exploded"

    def test_frozen(self) -> None:
        result = ImageBuildResult(benchmark_id="test", success=True)
        with pytest.raises(AttributeError):
            result.success = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ImageBuildSummary tests
# ---------------------------------------------------------------------------


class TestImageBuildSummary:
    def test_empty_summary(self) -> None:
        summary = ImageBuildSummary()
        assert summary.succeeded == []
        assert summary.failed == []
        assert summary.built_benchmark_ids == set()
        assert summary.image_map == {}

    def test_mixed_results(self) -> None:
        ok = ImageBuildResult(
            benchmark_id="good",
            image_tag="saber/crsbench/benchmark:good",
            success=True,
        )
        bad = ImageBuildResult(
            benchmark_id="bad",
            success=False,
            error="fail",
        )
        summary = ImageBuildSummary(results=[ok, bad])
        assert len(summary.succeeded) == 1
        assert len(summary.failed) == 1
        assert summary.built_benchmark_ids == {"good"}
        assert summary.image_map == {"good": "saber/crsbench/benchmark:good"}

    def test_all_succeeded(self) -> None:
        results = [
            ImageBuildResult(
                benchmark_id=f"bench-{i}",
                image_tag=f"saber/crsbench/benchmark:bench-{i}",
                success=True,
            )
            for i in range(3)
        ]
        summary = ImageBuildSummary(results=results)
        assert len(summary.succeeded) == 3
        assert len(summary.failed) == 0

    def test_all_failed(self) -> None:
        results = [
            ImageBuildResult(benchmark_id=f"bench-{i}", success=False, error="boom")
            for i in range(2)
        ]
        summary = ImageBuildSummary(results=results)
        assert len(summary.succeeded) == 0
        assert len(summary.failed) == 2


# ---------------------------------------------------------------------------
# image_exists tests
# ---------------------------------------------------------------------------


class TestImageExists:
    def test_image_exists_true(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            assert image_exists("some:tag") is True
            mock_run.assert_called_once_with(
                ["docker", "image", "inspect", "some:tag"],
                capture_output=True,
                timeout=30,
            )

    def test_image_exists_false(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            assert image_exists("missing:tag") is False

    def test_image_exists_timeout(self) -> None:
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("docker", 30)):
            assert image_exists("slow:tag") is False

    def test_image_exists_no_docker(self) -> None:
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert image_exists("nodocker:tag") is False


# ---------------------------------------------------------------------------
# _find_benchmark_dockerfile tests
# ---------------------------------------------------------------------------


class TestFindBenchmarkDockerfile:
    def test_finds_root_dockerfile(self, tmp_path: Path) -> None:
        (tmp_path / "Dockerfile").write_text("FROM ubuntu")
        assert _find_benchmark_dockerfile(tmp_path) == tmp_path / "Dockerfile"

    def test_finds_docker_subdir_dockerfile(self, tmp_path: Path) -> None:
        docker_dir = tmp_path / "docker"
        docker_dir.mkdir()
        (docker_dir / "Dockerfile").write_text("FROM ubuntu")
        assert _find_benchmark_dockerfile(tmp_path) == docker_dir / "Dockerfile"

    def test_finds_dockerfile_builder(self, tmp_path: Path) -> None:
        (tmp_path / "Dockerfile.builder").write_text("FROM ubuntu")
        assert _find_benchmark_dockerfile(tmp_path) == tmp_path / "Dockerfile.builder"

    def test_prefers_root_over_subdir(self, tmp_path: Path) -> None:
        (tmp_path / "Dockerfile").write_text("FROM ubuntu")
        docker_dir = tmp_path / "docker"
        docker_dir.mkdir()
        (docker_dir / "Dockerfile").write_text("FROM ubuntu")
        assert _find_benchmark_dockerfile(tmp_path) == tmp_path / "Dockerfile"

    def test_returns_none_when_no_dockerfile(self, tmp_path: Path) -> None:
        assert _find_benchmark_dockerfile(tmp_path) is None


# ---------------------------------------------------------------------------
# _discover_benchmarks tests
# ---------------------------------------------------------------------------


class TestDiscoverBenchmarks:
    def test_empty_dir(self, tmp_path: Path) -> None:
        assert _discover_benchmarks(tmp_path) == []

    def test_nonexistent_dir(self, tmp_path: Path) -> None:
        assert _discover_benchmarks(tmp_path / "nope") == []

    def test_finds_benchmarks_with_dockerfiles(self, tmp_path: Path) -> None:
        # Create two benchmarks with Dockerfiles
        for name in ["bench-a", "bench-b"]:
            d = tmp_path / name
            d.mkdir()
            (d / "Dockerfile").write_text("FROM ubuntu")

        # Create one without
        (tmp_path / "no-docker").mkdir()

        result = _discover_benchmarks(tmp_path)
        assert len(result) == 2
        assert result[0].name == "bench-a"
        assert result[1].name == "bench-b"

    def test_sorted_output(self, tmp_path: Path) -> None:
        for name in ["zzz", "aaa", "mmm"]:
            d = tmp_path / name
            d.mkdir()
            (d / "Dockerfile").write_text("FROM ubuntu")

        result = _discover_benchmarks(tmp_path)
        assert [r.name for r in result] == ["aaa", "mmm", "zzz"]

    def test_skips_files(self, tmp_path: Path) -> None:
        (tmp_path / "not-a-dir.txt").write_text("hello")
        assert _discover_benchmarks(tmp_path) == []


# ---------------------------------------------------------------------------
# build_benchmark_image tests
# ---------------------------------------------------------------------------


class TestBuildBenchmarkImage:
    @pytest.fixture()
    def benchmark_dir(self, tmp_path: Path) -> Path:
        bench = tmp_path / "data" / "benchmarks" / "test-bench"
        bench.mkdir(parents=True)
        (bench / "Dockerfile").write_text("FROM ubuntu:22.04")
        return bench

    @pytest.fixture()
    def domain_root(self, tmp_path: Path) -> Path:
        return tmp_path

    @pytest.mark.asyncio()
    async def test_skips_when_image_exists(
        self, benchmark_dir: Path, domain_root: Path
    ) -> None:
        with patch("crsbench.build_images.image_exists", return_value=True):
            result = await build_benchmark_image(benchmark_dir, domain_root)
        assert result.success is True
        assert result.image_tag == f"{BENCHMARK_IMAGE_PREFIX}:test-bench"

    @pytest.mark.asyncio()
    async def test_force_rebuild_ignores_existing(
        self, benchmark_dir: Path, domain_root: Path
    ) -> None:
        """force=True should build even when image exists."""
        with (
            patch("crsbench.build_images.image_exists", return_value=True),
            patch(
                "asyncio.create_subprocess_exec",
                side_effect=lambda *a, **kw: _mock_docker_proc(),
            ),
        ):
            result = await build_benchmark_image(
                benchmark_dir, domain_root, force=True
            )
        assert result.success is True

    @pytest.mark.asyncio()
    async def test_successful_two_layer_build(
        self, benchmark_dir: Path, domain_root: Path
    ) -> None:
        with (
            patch("crsbench.build_images.image_exists", return_value=False),
            patch(
                "asyncio.create_subprocess_exec",
                side_effect=lambda *a, **kw: _mock_docker_proc(),
            ),
        ):
            result = await build_benchmark_image(benchmark_dir, domain_root)

        assert result.success is True
        assert result.benchmark_id == "test-bench"
        assert result.image_tag == f"{BENCHMARK_IMAGE_PREFIX}:test-bench"
        assert result.error == ""

    @pytest.mark.asyncio()
    async def test_layer1_failure_returns_error(
        self, benchmark_dir: Path, domain_root: Path
    ) -> None:
        with (
            patch("crsbench.build_images.image_exists", return_value=False),
            patch(
                "asyncio.create_subprocess_exec",
                side_effect=lambda *a, **kw: _mock_docker_proc(
                    returncode=1, stderr=b"error building\n"
                ),
            ),
        ):
            result = await build_benchmark_image(benchmark_dir, domain_root)

        assert result.success is False
        assert "build failed" in result.error

    @pytest.mark.asyncio()
    async def test_no_dockerfile_returns_error(
        self, tmp_path: Path, domain_root: Path
    ) -> None:
        bench = tmp_path / "no-docker-bench"
        bench.mkdir()
        # No Dockerfile

        with patch("crsbench.build_images.image_exists", return_value=False):
            result = await build_benchmark_image(bench, domain_root)

        assert result.success is False
        assert "No Dockerfile found" in result.error

    @pytest.mark.asyncio()
    async def test_timeout_returns_error(
        self, benchmark_dir: Path, domain_root: Path
    ) -> None:
        # Create a proc whose streams never end, triggering timeout
        async def hang_readline() -> bytes:
            await asyncio.sleep(100)
            return b""

        mock_proc = AsyncMock()
        mock_proc.stdout = AsyncMock()
        mock_proc.stdout.readline = hang_readline
        mock_proc.stderr = AsyncMock()
        mock_proc.stderr.readline = hang_readline
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock(return_value=1)
        mock_proc.returncode = 1

        with (
            patch("crsbench.build_images.image_exists", return_value=False),
            patch("asyncio.create_subprocess_exec", return_value=mock_proc),
        ):
            result = await build_benchmark_image(
                benchmark_dir, domain_root, timeout=0.1
            )

        assert result.success is False
        assert "timed out" in result.error


# ---------------------------------------------------------------------------
# build_all_images tests
# ---------------------------------------------------------------------------


class TestBuildAllImages:
    @pytest.fixture()
    def benchmarks_dir(self, tmp_path: Path) -> Path:
        benchmarks = tmp_path / "data" / "benchmarks"
        benchmarks.mkdir(parents=True)
        for name in ["bench-a", "bench-b", "bench-c"]:
            d = benchmarks / name
            d.mkdir()
            (d / "Dockerfile").write_text("FROM ubuntu")
        return benchmarks

    @pytest.fixture()
    def domain_root(self, tmp_path: Path) -> Path:
        return tmp_path

    @pytest.mark.asyncio()
    async def test_builds_all_benchmarks(
        self, benchmarks_dir: Path, domain_root: Path
    ) -> None:
        with (
            patch("crsbench.build_images.image_exists", return_value=False),
            patch(
                "asyncio.create_subprocess_exec",
                side_effect=lambda *a, **kw: _mock_docker_proc(),
            ),
        ):
            summary = await build_all_images(benchmarks_dir, domain_root)

        assert len(summary.succeeded) == 3
        assert len(summary.failed) == 0

    @pytest.mark.asyncio()
    async def test_empty_dir_returns_empty_summary(
        self, tmp_path: Path
    ) -> None:
        summary = await build_all_images(tmp_path / "empty", tmp_path)
        assert summary.results == []

    @pytest.mark.asyncio()
    async def test_prefix_filter(
        self, benchmarks_dir: Path, domain_root: Path
    ) -> None:
        with (
            patch("crsbench.build_images.image_exists", return_value=False),
            patch(
                "asyncio.create_subprocess_exec",
                side_effect=lambda *a, **kw: _mock_docker_proc(),
            ),
        ):
            summary = await build_all_images(
                benchmarks_dir, domain_root, prefix_filter="bench-a"
            )

        assert len(summary.results) == 1
        assert summary.results[0].benchmark_id == "bench-a"

    @pytest.mark.asyncio()
    async def test_partial_failures(
        self, benchmarks_dir: Path, domain_root: Path
    ) -> None:
        """Some benchmarks fail, others succeed."""
        call_count = 0

        async def mock_exec(*args, **kwargs):  # noqa: ANN002, ANN003
            nonlocal call_count
            call_count += 1
            # Fail every other call (layer 1 of bench-b)
            if call_count in (3, 4):
                return _mock_docker_proc(returncode=1, stderr=b"error\n")
            return _mock_docker_proc()

        with (
            patch("crsbench.build_images.image_exists", return_value=False),
            patch("asyncio.create_subprocess_exec", side_effect=mock_exec),
        ):
            summary = await build_all_images(benchmarks_dir, domain_root)

        assert len(summary.failed) >= 1
        assert len(summary.succeeded) >= 1

    @pytest.mark.asyncio()
    async def test_respects_max_concurrent(
        self, benchmarks_dir: Path, domain_root: Path
    ) -> None:
        """Verifies semaphore limits concurrent builds."""
        active = 0
        max_active = 0

        async def tracking_build(
            benchmark_path: Path,
            domain_root: Path,
            **kwargs,  # noqa: ANN003
        ) -> ImageBuildResult:
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0.01)
            active -= 1
            return ImageBuildResult(
                benchmark_id=benchmark_path.name,
                image_tag=f"{BENCHMARK_IMAGE_PREFIX}:{benchmark_path.name}",
                success=True,
            )

        with patch("crsbench.build_images.build_benchmark_image", side_effect=tracking_build):
            await build_all_images(
                benchmarks_dir, domain_root, max_concurrent=2
            )

        assert max_active <= 2


# ---------------------------------------------------------------------------
# build_images_sync tests
# ---------------------------------------------------------------------------


class TestBuildImagesSync:
    def test_sync_wrapper_returns_summary(self, tmp_path: Path) -> None:
        """Sync wrapper should produce an ImageBuildSummary."""
        mock_summary = ImageBuildSummary(
            results=[
                ImageBuildResult(benchmark_id="test", success=True, image_tag="t:t"),
            ],
            total_duration_seconds=1.0,
        )

        with patch(
            "crsbench.build_images.build_all_images",
            return_value=mock_summary,
        ):
            result = build_images_sync(tmp_path, tmp_path)

        assert isinstance(result, ImageBuildSummary)
        assert len(result.succeeded) == 1

    def test_sync_wrapper_passes_kwargs(self, tmp_path: Path) -> None:
        """Verify all kwargs are forwarded correctly."""
        mock_summary = ImageBuildSummary()

        with patch(
            "crsbench.build_images.build_all_images",
            return_value=mock_summary,
        ) as mock_build:
            build_images_sync(
                tmp_path,
                tmp_path,
                force=True,
                max_concurrent=2,
                timeout=600,
                prefix_filter="abc",
            )

            mock_build.assert_called_once_with(
                tmp_path,
                tmp_path,
                force=True,
                max_concurrent=2,
                timeout=600,
                prefix_filter="abc",
            )


# ---------------------------------------------------------------------------
# cleanup_build_artifacts tests
# ---------------------------------------------------------------------------


class TestCleanupBuildArtifacts:
    def test_cleanup_removes_build_tmp(self, tmp_path: Path) -> None:
        build_tmp = tmp_path / ".build_tmp"
        build_tmp.mkdir()
        (build_tmp / "test-bench").mkdir()
        (build_tmp / "test-bench" / "Dockerfile").write_text("FROM ubuntu")

        cleanup_build_artifacts(tmp_path)
        assert not build_tmp.exists()

    def test_cleanup_noop_when_no_dir(self, tmp_path: Path) -> None:
        # Should not raise
        cleanup_build_artifacts(tmp_path)


# ---------------------------------------------------------------------------
# Constants tests
# ---------------------------------------------------------------------------


class TestConstants:
    def test_image_prefixes(self) -> None:
        assert ENV_IMAGE_PREFIX == "saber/crsbench/env"
        assert BENCHMARK_IMAGE_PREFIX == "saber/crsbench/benchmark"

    def test_default_concurrent(self) -> None:
        assert DEFAULT_MAX_CONCURRENT_BUILDS == 4

    def test_default_timeout(self) -> None:
        assert DEFAULT_BUILD_TIMEOUT_SECONDS == 3600


# ===========================================================================
# Tests for crsbench.scripts.build_images (aces — Pydantic-based pipeline)
# ===========================================================================


# ---------------------------------------------------------------------------
# ScriptsImageBuildResult (Pydantic model) tests
# ---------------------------------------------------------------------------


class TestScriptsImageBuildResult:
    """Tests for the ImageBuildResult Pydantic model."""

    def test_frozen(self) -> None:
        result = ScriptsImageBuildResult(
            benchmark_id="afc-curl-delta-01",
            image_tag="saber/crsbench/benchmark:afc-curl-delta-01",
            success=True,
            skipped=False,
        )
        with pytest.raises(ValidationError):
            result.benchmark_id = "other"  # type: ignore[misc]

    def test_success_result(self) -> None:
        result = ScriptsImageBuildResult(
            benchmark_id="afc-curl-delta-01",
            image_tag="saber/crsbench/benchmark:afc-curl-delta-01",
            success=True,
            skipped=False,
            duration_seconds=12.5,
        )
        assert result.success is True
        assert result.error_message is None

    def test_failed_result(self) -> None:
        result = ScriptsImageBuildResult(
            benchmark_id="afc-curl-delta-01",
            image_tag="saber/crsbench/benchmark:afc-curl-delta-01",
            success=False,
            skipped=False,
            error_message="build.sh failed with exit code 1",
        )
        assert result.success is False
        assert result.error_message is not None

    def test_skipped_result(self) -> None:
        result = ScriptsImageBuildResult(
            benchmark_id="afc-curl-delta-01",
            image_tag="saber/crsbench/benchmark:afc-curl-delta-01",
            success=True,
            skipped=True,
        )
        assert result.skipped is True


# ---------------------------------------------------------------------------
# ScriptsImageBuildSummary (Pydantic model) tests
# ---------------------------------------------------------------------------


class TestScriptsImageBuildSummary:
    """Tests for the ImageBuildSummary aggregate model."""

    def test_counts_consistent(self) -> None:
        results = (
            ScriptsImageBuildResult(
                benchmark_id="a",
                image_tag="t:a",
                success=True,
                skipped=False,
            ),
            ScriptsImageBuildResult(
                benchmark_id="b",
                image_tag="t:b",
                success=True,
                skipped=True,
            ),
            ScriptsImageBuildResult(
                benchmark_id="c",
                image_tag="t:c",
                success=False,
                skipped=False,
                error_message="err",
            ),
        )
        summary = ScriptsImageBuildSummary(
            total=3,
            built=1,
            skipped=1,
            failed=1,
            results=results,
        )
        assert summary.total == summary.built + summary.skipped + summary.failed

    def test_frozen(self) -> None:
        summary = ScriptsImageBuildSummary(
            total=0,
            built=0,
            skipped=0,
            failed=0,
            results=(),
        )
        with pytest.raises(ValidationError):
            summary.total = 5  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Tag helpers
# ---------------------------------------------------------------------------


class TestImageTagForBenchmark:
    def test_standard_benchmark(self) -> None:
        assert (
            image_tag_for_benchmark("afc-curl-delta-01")
            == "saber/crsbench/benchmark:afc-curl-delta-01"
        )

    def test_sanity_benchmark(self) -> None:
        assert (
            image_tag_for_benchmark("sanity-mock-c-delta-01")
            == "saber/crsbench/benchmark:sanity-mock-c-delta-01"
        )


class TestEnvImageTagForBenchmark:
    def test_standard_benchmark(self) -> None:
        assert (
            env_image_tag_for_benchmark("afc-curl-delta-01")
            == "saber/crsbench/env:afc-curl-delta-01"
        )

    def test_sanity_benchmark(self) -> None:
        assert (
            env_image_tag_for_benchmark("sanity-mock-c-delta-01")
            == "saber/crsbench/env:sanity-mock-c-delta-01"
        )


# ---------------------------------------------------------------------------
# generate_overlay_dockerfile
# ---------------------------------------------------------------------------


class TestReadSaberTooling:
    """Tests for _read_saber_tooling helper."""

    def test_reads_from_dockerfile(self) -> None:
        tooling = _read_saber_tooling()
        assert "nodesource" in tooling
        assert "nodejs" in tooling
        assert "@github/copilot" in tooling

    def test_fallback_when_file_missing(self, tmp_path: Path) -> None:
        with patch(
            "crsbench.scripts.build_images._SABER_DOCKERFILE",
            tmp_path / "nonexistent",
        ):
            tooling = _read_saber_tooling()
        assert "nodesource" in tooling
        assert "@github/copilot" in tooling


class TestGenerateOverlayDockerfile:
    def test_extends_env_image(self) -> None:
        content = generate_overlay_dockerfile("saber/crsbench/env:afc-curl-delta-01")
        assert content.startswith("FROM saber/crsbench/env:afc-curl-delta-01\n")

    def test_installs_nodejs(self) -> None:
        content = generate_overlay_dockerfile("saber/crsbench/env:test")
        assert "nodesource" in content
        assert "nodejs" in content

    def test_installs_copilot_and_claude(self) -> None:
        content = generate_overlay_dockerfile("saber/crsbench/env:test")
        assert "@github/copilot" in content
        assert "@anthropic-ai/claude-code" in content

    def test_installs_uv(self) -> None:
        content = generate_overlay_dockerfile("saber/crsbench/env:test")
        assert "ghcr.io/astral-sh/uv:latest" in content

    def test_installs_python_sdks(self) -> None:
        content = generate_overlay_dockerfile("saber/crsbench/env:test")
        assert "claude-code-sdk" in content
        assert "github-copilot-sdk" in content

    def test_copies_staged_to_workspace(self) -> None:
        content = generate_overlay_dockerfile("saber/crsbench/env:test")
        assert "COPY staged/ /workspace/source/" in content

    def test_removes_layer1_source_duplicate(self) -> None:
        content = generate_overlay_dockerfile("saber/crsbench/env:test")
        assert "rm -rf /src/*" in content

    def test_runs_build_non_fatal(self) -> None:
        content = generate_overlay_dockerfile("saber/crsbench/env:test")
        assert "bash build.sh || true" in content

    def test_sets_workspace_env(self) -> None:
        content = generate_overlay_dockerfile("saber/crsbench/env:test")
        assert "SRC=/workspace/source" in content
        assert "OUT=/workspace/build" in content

    def test_sets_workdir(self) -> None:
        content = generate_overlay_dockerfile("saber/crsbench/env:test")
        assert "WORKDIR /workspace" in content

    def test_is_valid_dockerfile(self) -> None:
        content = generate_overlay_dockerfile("saber/crsbench/env:test")
        lines = [
            line
            for line in content.strip().splitlines()
            if line and not line.startswith("#")
        ]
        assert lines[0].startswith("FROM ")


# ---------------------------------------------------------------------------
# Scripts image_exists (async)
# ---------------------------------------------------------------------------


class TestScriptsImageExists:
    @pytest.mark.asyncio
    async def test_returns_true_when_image_present(self) -> None:
        with patch(
            "crsbench.scripts.build_images._run_docker_cmd",
            return_value=(0, "", ""),
        ):
            assert await scripts_image_exists("saber/crsbench/benchmark:test") is True

    @pytest.mark.asyncio
    async def test_returns_false_when_image_absent(self) -> None:
        with patch(
            "crsbench.scripts.build_images._run_docker_cmd",
            return_value=(1, "", "No such image"),
        ):
            assert await scripts_image_exists("saber/crsbench/benchmark:test") is False


# ---------------------------------------------------------------------------
# .dockerignore helpers
# ---------------------------------------------------------------------------


class TestDockerignoreHelpers:
    def test_layer1_excludes_staged(self, tmp_path: Path) -> None:
        _write_dockerignore(tmp_path, layer=1)
        content = (tmp_path / ".dockerignore").read_text()
        assert "staged/" in content
        assert "pkgs/" not in content  # Layer 1 needs pkgs/

    def test_layer2_excludes_pkgs(self, tmp_path: Path) -> None:
        _write_dockerignore(tmp_path, layer=2)
        content = (tmp_path / ".dockerignore").read_text()
        assert "pkgs/" in content
        assert ".aixcc/" in content
        assert "staged/" not in content  # Layer 2 needs staged/

    def test_cleanup_removes_dockerignore(self, tmp_path: Path) -> None:
        _write_dockerignore(tmp_path, layer=1)
        assert (tmp_path / ".dockerignore").exists()
        _cleanup_dockerignore(tmp_path)
        assert not (tmp_path / ".dockerignore").exists()

    def test_cleanup_noop_when_missing(self, tmp_path: Path) -> None:
        _cleanup_dockerignore(tmp_path)  # should not raise


# ---------------------------------------------------------------------------
# Scripts build_benchmark_image (aces version)
# ---------------------------------------------------------------------------


class TestScriptsBuildBenchmarkImage:
    @pytest.mark.asyncio
    async def test_builds_image_successfully(self, tmp_path: Path) -> None:
        """Successful two-layer build returns success=True with correct tag."""
        bench = _create_benchmark_dir(tmp_path, "test-bench-delta-01")
        with (
            patch(
                "crsbench.scripts.build_images.image_exists",
                return_value=False,
            ),
            patch(
                "crsbench.scripts.build_images._run_docker_cmd",
                return_value=(0, "", ""),
            ),
        ):
            result = await scripts_build_benchmark_image(bench)
        assert result.success is True
        assert result.benchmark_id == "test-bench-delta-01"
        assert result.image_tag == "saber/crsbench/benchmark:test-bench-delta-01"
        assert result.skipped is False

    @pytest.mark.asyncio
    async def test_skips_when_final_image_exists(self, tmp_path: Path) -> None:
        bench = _create_benchmark_dir(tmp_path, "test-bench-delta-01")
        with patch(
            "crsbench.scripts.build_images.image_exists",
            return_value=True,
        ):
            result = await scripts_build_benchmark_image(bench, force=False)
        assert result.skipped is True
        assert result.success is True

    @pytest.mark.asyncio
    async def test_rebuilds_when_force_true(self, tmp_path: Path) -> None:
        bench = _create_benchmark_dir(tmp_path, "test-bench-delta-01")
        with (
            patch(
                "crsbench.scripts.build_images.image_exists",
                return_value=True,
            ),
            patch(
                "crsbench.scripts.build_images._run_docker_cmd",
                return_value=(0, "", ""),
            ),
        ):
            result = await scripts_build_benchmark_image(bench, force=True)
        assert result.skipped is False
        assert result.success is True

    @pytest.mark.asyncio
    async def test_layer1_uses_benchmark_dockerfile(self, tmp_path: Path) -> None:
        """Layer 1 builds using the benchmark's own Dockerfile."""
        bench = _create_benchmark_dir(tmp_path, "test-bench-delta-01")
        calls: list[list[str]] = []

        async def capture_cmd(args: list[str], **kw: object) -> tuple[int, str, str]:
            calls.append(args)
            return (0, "", "")

        with (
            patch(
                "crsbench.scripts.build_images.image_exists",
                return_value=False,
            ),
            patch(
                "crsbench.scripts.build_images._run_docker_cmd",
                side_effect=capture_cmd,
            ),
        ):
            await scripts_build_benchmark_image(bench)
        # First docker build call should use the benchmark's Dockerfile
        layer1_call = [c for c in calls if "docker" in c and "build" in c][0]
        assert "-t" in layer1_call
        assert "saber/crsbench/env:test-bench-delta-01" in layer1_call

    @pytest.mark.asyncio
    async def test_layer2_generates_overlay_dockerfile(self, tmp_path: Path) -> None:
        """Layer 2 generates an overlay Dockerfile with SABER tooling."""
        bench = _create_benchmark_dir(tmp_path, "test-bench-delta-01")
        captured_content: list[str] = []
        original_write = Path.write_text

        def capture_write(
            self_path: Path, content: str, *a: object, **kw: object
        ) -> None:
            if self_path.name == "Dockerfile.saber":
                captured_content.append(content)
            original_write(self_path, content, *a, **kw)  # type: ignore[arg-type]

        with (
            patch(
                "crsbench.scripts.build_images.image_exists",
                return_value=False,
            ),
            patch(
                "crsbench.scripts.build_images._run_docker_cmd",
                return_value=(0, "", ""),
            ),
            patch.object(Path, "write_text", capture_write),
        ):
            await scripts_build_benchmark_image(bench)
        assert len(captured_content) == 1
        content = captured_content[0]
        assert "FROM saber/crsbench/env:test-bench-delta-01" in content
        assert "@github/copilot" in content
        assert "bash build.sh || true" in content

    @pytest.mark.asyncio
    async def test_layer1_failure_returns_error(self, tmp_path: Path) -> None:
        bench = _create_benchmark_dir(tmp_path, "test-bench-delta-01")
        with (
            patch(
                "crsbench.scripts.build_images.image_exists",
                return_value=False,
            ),
            patch(
                "crsbench.scripts.build_images._run_docker_cmd",
                return_value=(1, "", "error: layer 1 failed"),
            ),
        ):
            result = await scripts_build_benchmark_image(bench)
        assert result.success is False
        assert "layer 1" in (result.error_message or "").lower()

    @pytest.mark.asyncio
    async def test_layer2_failure_after_layer1_success(self, tmp_path: Path) -> None:
        """Layer 2 failure preserves env image and reports Layer 2 error."""
        bench = _create_benchmark_dir(tmp_path, "test-bench-delta-01")
        call_count = 0

        async def fail_on_second(args: list[str], **kw: object) -> tuple[int, str, str]:
            nonlocal call_count
            call_count += 1
            if call_count == 2:  # Layer 2 build
                return (1, "", "error: layer 2 failed")
            return (0, "", "")

        with (
            patch(
                "crsbench.scripts.build_images.image_exists",
                return_value=False,
            ),
            patch(
                "crsbench.scripts.build_images._run_docker_cmd",
                side_effect=fail_on_second,
            ),
        ):
            result = await scripts_build_benchmark_image(bench)
        assert result.success is False
        assert "layer 2" in (result.error_message or "").lower()

    @pytest.mark.asyncio
    async def test_reuses_existing_env_image(self, tmp_path: Path) -> None:
        """If env image exists, skip Layer 1 and only rebuild Layer 2."""
        bench = _create_benchmark_dir(tmp_path, "test-bench-delta-01")

        async def exists_check(tag: str) -> bool:
            # env image exists, final image doesn't
            return "env:" in tag

        calls: list[list[str]] = []

        async def capture_cmd(args: list[str], **kw: object) -> tuple[int, str, str]:
            calls.append(args)
            return (0, "", "")

        with (
            patch(
                "crsbench.scripts.build_images.image_exists",
                side_effect=exists_check,
            ),
            patch(
                "crsbench.scripts.build_images._run_docker_cmd",
                side_effect=capture_cmd,
            ),
        ):
            result = await scripts_build_benchmark_image(bench)
        # Should only have one docker build call (Layer 2), not two
        build_calls = [c for c in calls if "build" in c]
        assert len(build_calls) == 1
        assert result.success is True

    @pytest.mark.asyncio
    async def test_missing_staged_dir_returns_error(self, tmp_path: Path) -> None:
        bench = tmp_path / "empty-bench-delta-01"
        bench.mkdir()
        result = await scripts_build_benchmark_image(bench)
        assert result.success is False
        assert "staged" in (result.error_message or "").lower()

    @pytest.mark.asyncio
    async def test_empty_staged_dir_returns_error(self, tmp_path: Path) -> None:
        bench = tmp_path / "empty-staged-delta-01"
        bench.mkdir()
        (bench / "staged").mkdir()  # exists but empty
        (bench / "Dockerfile").write_text("FROM ubuntu\n")
        result = await scripts_build_benchmark_image(bench)
        assert result.success is False
        assert "staged" in (result.error_message or "").lower()

    @pytest.mark.asyncio
    async def test_timeout_returns_error_result(self, tmp_path: Path) -> None:
        """Timeout during build returns a failed result."""
        bench = _create_benchmark_dir(tmp_path, "timeout-bench-delta-01")
        with (
            patch("crsbench.scripts.build_images.image_exists", return_value=False),
            patch(
                "crsbench.scripts.build_images._run_docker_cmd",
                side_effect=asyncio.TimeoutError("timed out"),
            ),
        ):
            result = await scripts_build_benchmark_image(bench)
        assert result.success is False
        assert "timeout" in (result.error_message or "").lower()

    @pytest.mark.asyncio
    async def test_missing_benchmark_dockerfile_returns_error(
        self, tmp_path: Path
    ) -> None:
        bench = _create_benchmark_dir(tmp_path, "test-bench-delta-01")
        (bench / "Dockerfile").unlink()
        result = await scripts_build_benchmark_image(bench)
        assert result.success is False
        assert "dockerfile" in (result.error_message or "").lower()

    @pytest.mark.asyncio
    async def test_missing_build_sh_creates_noop(self, tmp_path: Path) -> None:
        """Missing build.sh in staged/ creates a no-op script."""
        bench = tmp_path / "test-bench-delta-01"
        staged = bench / "staged"
        staged.mkdir(parents=True)
        (staged / "main.c").write_text("int main(){}")
        (bench / ".aixcc").mkdir()
        # Create benchmark Dockerfile but no build.sh in staged/
        (bench / "Dockerfile").write_text(
            "FROM ghcr.io/aixcc-finals/base-builder:v1.3.0\n"
        )
        with (
            patch("crsbench.scripts.build_images.image_exists", return_value=False),
            patch(
                "crsbench.scripts.build_images._run_docker_cmd",
                return_value=(0, "", ""),
            ),
        ):
            result = await scripts_build_benchmark_image(bench)
        assert result.success is True
        # Should have created no-op build.sh in staged/
        assert (staged / "build.sh").exists()
        content = (staged / "build.sh").read_text()
        assert "exit 0" in content

    @pytest.mark.asyncio
    async def test_existing_build_sh_not_overwritten(self, tmp_path: Path) -> None:
        """Existing build.sh in staged/ is preserved."""
        bench = _create_benchmark_dir(tmp_path, "test-bench-delta-01")
        staged = bench / "staged"
        original_content = "#!/bin/bash\necho custom build\n"
        (staged / "build.sh").write_text(original_content)
        with (
            patch("crsbench.scripts.build_images.image_exists", return_value=False),
            patch(
                "crsbench.scripts.build_images._run_docker_cmd",
                return_value=(0, "", ""),
            ),
        ):
            await scripts_build_benchmark_image(bench)
        assert (staged / "build.sh").read_text() == original_content

    @pytest.mark.asyncio
    async def test_cleanup_overlay_on_success(self, tmp_path: Path) -> None:
        """Overlay Dockerfile.saber is cleaned up after successful build."""
        bench = _create_benchmark_dir(tmp_path, "test-bench-delta-01")
        with (
            patch(
                "crsbench.scripts.build_images.image_exists",
                return_value=False,
            ),
            patch(
                "crsbench.scripts.build_images._run_docker_cmd",
                return_value=(0, "", ""),
            ),
        ):
            await scripts_build_benchmark_image(bench)
        assert not (bench / "Dockerfile.saber").exists()

    @pytest.mark.asyncio
    async def test_cleanup_overlay_on_failure(self, tmp_path: Path) -> None:
        """Overlay Dockerfile.saber is cleaned up even after Layer 2 failure."""
        bench = _create_benchmark_dir(tmp_path, "test-bench-delta-01")
        call_count = 0

        async def fail_on_second(args: list[str], **kw: object) -> tuple[int, str, str]:
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                return (1, "", "error")
            return (0, "", "")

        with (
            patch(
                "crsbench.scripts.build_images.image_exists",
                return_value=False,
            ),
            patch(
                "crsbench.scripts.build_images._run_docker_cmd",
                side_effect=fail_on_second,
            ),
        ):
            await scripts_build_benchmark_image(bench)
        assert not (bench / "Dockerfile.saber").exists()


# ---------------------------------------------------------------------------
# Scripts build_all_benchmark_images
# ---------------------------------------------------------------------------


class TestBuildAllBenchmarkImages:
    @pytest.mark.asyncio
    async def test_builds_multiple_benchmarks(self, tmp_path: Path) -> None:
        for name in ["bench-a-delta-01", "bench-b-delta-01"]:
            _create_benchmark_dir(tmp_path, name)
        with (
            patch(
                "crsbench.scripts.build_images.image_exists",
                return_value=False,
            ),
            patch(
                "crsbench.scripts.build_images._run_docker_cmd",
                return_value=(0, "", ""),
            ),
        ):
            summary = await build_all_benchmark_images(tmp_path)
        assert summary.total == 2
        assert summary.built == 2
        assert summary.failed == 0

    @pytest.mark.asyncio
    async def test_filters_by_dataset(self, tmp_path: Path) -> None:
        for name in ["bench-a-delta-01", "bench-b-delta-01"]:
            _create_benchmark_dir(tmp_path, name)
        with (
            patch(
                "crsbench.scripts.build_images.image_exists",
                return_value=False,
            ),
            patch(
                "crsbench.scripts.build_images._run_docker_cmd",
                return_value=(0, "", ""),
            ),
        ):
            summary = await build_all_benchmark_images(
                tmp_path,
                datasets=["bench-a-delta-01"],
            )
        assert summary.total == 1
        assert summary.built == 1

    @pytest.mark.asyncio
    async def test_skips_existing_images(self, tmp_path: Path) -> None:
        _create_benchmark_dir(tmp_path, "bench-a-delta-01")
        with patch(
            "crsbench.scripts.build_images.image_exists",
            return_value=True,
        ):
            summary = await build_all_benchmark_images(tmp_path)
        assert summary.skipped == 1
        assert summary.built == 0

    @pytest.mark.asyncio
    async def test_force_rebuilds_existing(self, tmp_path: Path) -> None:
        _create_benchmark_dir(tmp_path, "bench-a-delta-01")
        with (
            patch(
                "crsbench.scripts.build_images.image_exists",
                return_value=True,
            ),
            patch(
                "crsbench.scripts.build_images._run_docker_cmd",
                return_value=(0, "", ""),
            ),
        ):
            summary = await build_all_benchmark_images(tmp_path, force=True)
        assert summary.built == 1
        assert summary.skipped == 0

    @pytest.mark.asyncio
    async def test_rebuild_prefix_filter(self, tmp_path: Path) -> None:
        for name in ["bench-a-delta-01", "bench-b-delta-01"]:
            _create_benchmark_dir(tmp_path, name)
        with (
            patch(
                "crsbench.scripts.build_images.image_exists",
                return_value=True,
            ),
            patch(
                "crsbench.scripts.build_images._run_docker_cmd",
                return_value=(0, "", ""),
            ),
        ):
            summary = await build_all_benchmark_images(
                tmp_path,
                rebuild_prefix="bench-a",
            )
        # bench-a is force-rebuilt, bench-b is skipped (exists)
        assert summary.built == 1
        assert summary.skipped == 1

    @pytest.mark.asyncio
    async def test_continues_after_failure(self, tmp_path: Path) -> None:
        for name in ["bench-a-delta-01", "bench-b-delta-01"]:
            _create_benchmark_dir(tmp_path, name)

        async def mock_cmd(args: list[str], **kw: object) -> tuple[int, str, str]:
            if "bench-a" in str(args):
                return (1, "", "error")
            return (0, "", "")

        with (
            patch(
                "crsbench.scripts.build_images.image_exists",
                return_value=False,
            ),
            patch(
                "crsbench.scripts.build_images._run_docker_cmd",
                side_effect=mock_cmd,
            ),
        ):
            summary = await build_all_benchmark_images(tmp_path)
        assert summary.failed == 1
        assert summary.built == 1
        assert summary.total == 2

    @pytest.mark.asyncio
    async def test_timeout_does_not_crash_batch(self, tmp_path: Path) -> None:
        """A timeout in one build should not crash the entire batch."""
        for name in ["bench-a-delta-01", "bench-b-delta-01"]:
            _create_benchmark_dir(tmp_path, name)

        async def timeout_on_a(args: list[str], **kw: object) -> tuple[int, str, str]:
            if "bench-a" in str(args):
                raise asyncio.TimeoutError("build timed out")
            return (0, "", "")

        with (
            patch("crsbench.scripts.build_images.image_exists", return_value=False),
            patch(
                "crsbench.scripts.build_images._run_docker_cmd",
                side_effect=timeout_on_a,
            ),
        ):
            summary = await build_all_benchmark_images(tmp_path)
        assert summary.failed == 1
        assert summary.built == 1
        assert summary.total == 2

    @pytest.mark.asyncio
    async def test_empty_directory(self, tmp_path: Path) -> None:
        summary = await build_all_benchmark_images(tmp_path)
        assert summary.total == 0


# ---------------------------------------------------------------------------
# Integration tests (Docker required)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestBuildImageIntegration:
    """Integration tests requiring Docker daemon."""

    @pytest.mark.asyncio
    async def test_builds_real_image_from_sanity_benchmark(self) -> None:
        """Build a real image from a sanity benchmark."""
        bench_dir = (
            Path(__file__).resolve().parents[1]
            / "data"
            / "_benchmarks"
            / "sanity-mock-c-delta-01"
        )
        if not bench_dir.exists() or not (bench_dir / "staged").exists():
            pytest.skip("Benchmark data not staged — run setup first")
        result = await scripts_build_benchmark_image(bench_dir, force=True)
        assert result.success is True
        assert await scripts_image_exists(result.image_tag)

    @pytest.mark.asyncio
    async def test_image_has_source_at_workspace(self) -> None:
        """Built image has source code at /workspace/source/."""
        tag = "saber/crsbench/benchmark:sanity-mock-c-delta-01"
        if not await scripts_image_exists(tag):
            pytest.skip("Image not built")
        from crsbench.scripts.build_images import _run_docker_cmd

        returncode, stdout, _ = await _run_docker_cmd(
            ["docker", "run", "--rm", tag, "ls", "/workspace/source/"],
        )
        assert returncode == 0
        assert "main.c" in stdout or "build.sh" in stdout

    @pytest.mark.asyncio
    async def test_image_has_saber_tooling(self) -> None:
        """Built image has SABER agent tooling installed."""
        tag = "saber/crsbench/benchmark:sanity-mock-c-delta-01"
        if not await scripts_image_exists(tag):
            pytest.skip("Image not built")
        from crsbench.scripts.build_images import _run_docker_cmd

        returncode, stdout, _ = await _run_docker_cmd(
            ["docker", "run", "--rm", tag, "which", "node"],
        )
        assert returncode == 0
        assert "node" in stdout


# ---------------------------------------------------------------------------
# Compose env-var interpolation
# ---------------------------------------------------------------------------


class TestComposeEnvVarInterpolation:
    """Tests for compose file env-var interpolation."""

    def test_compose_uses_benchmark_image_var(self) -> None:
        compose_path = (
            Path(__file__).resolve().parents[1] / "compose" / "sandbox.compose.yml"
        )
        content = compose_path.read_text()
        assert "SAMPLE_METADATA_BENCHMARK_IMAGE" in content

    def test_compose_has_no_fallback(self) -> None:
        compose_path = (
            Path(__file__).resolve().parents[1] / "compose" / "sandbox.compose.yml"
        )
        content = compose_path.read_text()
        assert ":-" not in content, "Compose should not have a fallback default"


# ---------------------------------------------------------------------------
# Git init resilience
# ---------------------------------------------------------------------------


class TestGitInitResilience:
    """Tests for _GIT_INIT_SETUP script robustness."""

    def test_script_uses_allow_empty_commit(self) -> None:
        from crsbench.crsbench import _GIT_INIT_SETUP

        assert "--allow-empty" in _GIT_INIT_SETUP

    def test_script_creates_directory(self) -> None:
        from crsbench.crsbench import _GIT_INIT_SETUP

        assert "mkdir -p /workspace/source" in _GIT_INIT_SETUP

    def test_script_uses_strict_mode(self) -> None:
        from crsbench.crsbench import _GIT_INIT_SETUP

        assert "set -euo pipefail" in _GIT_INIT_SETUP
