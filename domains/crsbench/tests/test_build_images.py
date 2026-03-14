"""Tests for crsbench.build_images (consolidated module)."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from crsbench.build_images import (
    BENCHMARK_IMAGE_PREFIX,
    DEFAULT_BUILD_TIMEOUT_SECONDS,
    DEFAULT_MAX_CONCURRENT_BUILDS,
    ENV_IMAGE_PREFIX,
    ImageBuildResult,
    ImageBuildSummary,
    _DOCKERIGNORE_LAYER1,
    _DOCKERIGNORE_LAYER2,
    _cleanup_dockerignore,
    _discover_benchmarks,
    _find_benchmark_dockerfile,
    _write_dockerignore,
    build_all_images,
    build_benchmark_image,
    build_images_sync,
    cleanup_build_artifacts,
    env_image_tag_for_benchmark,
    generate_overlay_dockerfile,
    image_exists,
    image_tag_for_benchmark,
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
# ImageBuildResult tests
# ===========================================================================


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


# ===========================================================================
# ImageBuildSummary tests
# ===========================================================================


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


# ===========================================================================
# image_exists tests
# ===========================================================================


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


# ===========================================================================
# _find_benchmark_dockerfile tests
# ===========================================================================


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


# ===========================================================================
# _discover_benchmarks tests
# ===========================================================================


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


# ===========================================================================
# build_benchmark_image tests
# ===========================================================================


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


# ===========================================================================
# build_all_images tests
# ===========================================================================


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
            summary = await build_all_images(benchmarks_dir, domain_root, verbose=True)

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
                benchmarks_dir, domain_root, prefix_filter="bench-a", verbose=True,
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
            summary = await build_all_images(benchmarks_dir, domain_root, verbose=True)

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
                benchmarks_dir, domain_root, max_concurrent=2, verbose=True,
            )

        assert max_active <= 2


# ===========================================================================
# build_images_sync tests
# ===========================================================================


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
                benchmark_names=None,
                verbose=False,
            )


# ===========================================================================
# cleanup_build_artifacts tests
# ===========================================================================


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


# ===========================================================================
# Constants tests
# ===========================================================================


class TestConstants:
    def test_image_prefixes(self) -> None:
        assert ENV_IMAGE_PREFIX == "saber/crsbench/env"
        assert BENCHMARK_IMAGE_PREFIX == "saber/crsbench/benchmark"

    def test_default_concurrent(self) -> None:
        assert DEFAULT_MAX_CONCURRENT_BUILDS == 4

    def test_default_timeout(self) -> None:
        assert DEFAULT_BUILD_TIMEOUT_SECONDS == 3600


# ===========================================================================
# Tag helpers
# ===========================================================================


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


# ===========================================================================
# generate_overlay_dockerfile tests
# ===========================================================================


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

    def test_creates_workspace_symlinks(self) -> None:
        content = generate_overlay_dockerfile("saber/crsbench/env:test")
        assert "ln -sfn /src /workspace/source" in content
        assert "ln -sfn /out /workspace/build" in content

    def test_copies_build_scripts(self) -> None:
        content = generate_overlay_dockerfile("saber/crsbench/env:test")
        assert "COPY build.sh test.sh /workspace/" in content

    def test_runs_build_non_fatal(self) -> None:
        content = generate_overlay_dockerfile("saber/crsbench/env:test")
        assert "bash /workspace/build.sh" in content
        # build.sh is best-effort (non-fatal)
        assert "SABER_BUILD_WARNING" in content

    def test_builds_libfuzzing_engine(self) -> None:
        content = generate_overlay_dockerfile("saber/crsbench/env:test")
        assert "libFuzzingEngine.a" in content
        assert "StandaloneFuzzTargetMain" in content

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

    def test_no_build_arg_required(self) -> None:
        """The generated Dockerfile should not use ARG BASE_IMAGE."""
        content = generate_overlay_dockerfile("saber/crsbench/env:test")
        assert "ARG BASE_IMAGE" not in content
        assert "${BASE_IMAGE}" not in content


# ===========================================================================
# .dockerignore helpers tests
# ===========================================================================


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

    def test_dockerignore_constants_content(self) -> None:
        assert "staged/" in _DOCKERIGNORE_LAYER1
        assert "Dockerfile.saber" in _DOCKERIGNORE_LAYER1
        assert "pkgs/" in _DOCKERIGNORE_LAYER2
        assert "*.tar.gz" in _DOCKERIGNORE_LAYER2


# ===========================================================================
# Compose env-var interpolation
# ===========================================================================


class TestComposeEnvVarInterpolation:
    """Tests for compose file env-var interpolation."""

    def test_compose_uses_benchmark_image_var(self) -> None:
        compose_path = (
            Path(__file__).resolve().parents[1] / "compose" / "default.compose.yml"
        )
        content = compose_path.read_text()
        assert "SAMPLE_METADATA_BENCHMARK_IMAGE" in content

    def test_compose_has_no_fallback(self) -> None:
        compose_path = (
            Path(__file__).resolve().parents[1] / "compose" / "default.compose.yml"
        )
        content = compose_path.read_text()
        assert ":-" not in content, "Compose should not have a fallback default"


# ===========================================================================
# Gradle offline init tests
# ===========================================================================


class TestGradleOfflineInit:
    """Tests for Gradle offline init script in Docker images."""

    def test_overlay_dockerfile_contains_gradle_init(self) -> None:
        """generate_overlay_dockerfile() output must include the gradle init script."""
        dockerfile = generate_overlay_dockerfile("saber/crsbench/env:test")
        assert "offline-cache.gradle" in dockerfile
        assert "cacheDynamicVersionsFor" in dockerfile
        assert "cacheChangingModulesFor" in dockerfile

    def test_gradle_init_runs_after_build_sh(self) -> None:
        """The Gradle init script must appear AFTER build.sh in the overlay dockerfile."""
        dockerfile = generate_overlay_dockerfile("saber/crsbench/env:test")
        build_sh_pos = dockerfile.index("build.sh")
        gradle_init_pos = dockerfile.index("offline-cache.gradle")
        assert gradle_init_pos > build_sh_pos


# ===========================================================================
# Git init resilience tests
# ===========================================================================


class TestGitInitResilience:
    """Tests for git-init in the L2 overlay Dockerfile."""

    @staticmethod
    def _overlay_dockerfile() -> str:
        """Return the generated L2 overlay Dockerfile content."""
        return generate_overlay_dockerfile("test-env:latest")

    def test_dockerfile_uses_allow_empty_commit(self) -> None:
        assert "--allow-empty" in self._overlay_dockerfile()

    def test_dockerfile_removes_nested_git(self) -> None:
        assert ".git" in self._overlay_dockerfile()
        assert "find . -mindepth 2 -name .git" in self._overlay_dockerfile()

    def test_dockerfile_creates_gitignore(self) -> None:
        assert ".gitignore" in self._overlay_dockerfile()

    def test_gitignore_contains_build_artifact_patterns(self) -> None:
        df = self._overlay_dockerfile()
        for pattern in ("*.o", "*.a", "*.so", "*.class", "*.jar", "*.pyc"):
            assert pattern in df, f"Missing gitignore pattern: {pattern}"

    def test_git_init_present(self) -> None:
        assert "git init" in self._overlay_dockerfile()

    def test_git_init_runs_after_build_sh(self) -> None:
        df = self._overlay_dockerfile()
        build_pos = df.index("bash /workspace/build.sh")
        git_pos = df.index("git init")
        assert git_pos > build_pos

    def test_git_init_runs_before_gradle_init(self) -> None:
        df = self._overlay_dockerfile()
        git_pos = df.index("git init")
        gradle_pos = df.index("offline-cache.gradle")
        assert git_pos < gradle_pos

    def test_git_config_user(self) -> None:
        df = self._overlay_dockerfile()
        assert "sandbox@saber" in df
        assert "sandbox" in df

    def test_git_add_and_commit(self) -> None:
        df = self._overlay_dockerfile()
        assert "git add -A" in df
        assert "git commit" in df

    def test_no_vulnerability_info(self) -> None:
        """Git-init RUN commands must not leak any fix / patch / CVE info."""
        df = self._overlay_dockerfile()
        git_section = df[df.index("Git init"):]
        # Only check actual RUN lines, not Dockerfile comments
        run_lines = [
            line for line in git_section.splitlines()
            if not line.lstrip().startswith("#")
        ]
        lowered = "\n".join(run_lines).lower()
        for keyword in ("cve-", "vuln", "exploit"):
            assert keyword not in lowered, (
                f"Git-init commands should not contain '{keyword}'"
            )


# ===========================================================================
# Apt-get update before build.sh tests (Fix 2)
# ===========================================================================


class TestAptGetUpdateBeforeBuildSh:
    """Layer 2 Dockerfile must run apt-get update before build.sh.

    After ``rm -rf /var/lib/apt/lists/*``, the apt cache is empty.
    ``build.sh`` scripts that call ``apt-get install`` will fail unless
    ``apt-get update`` is run first.
    """

    def test_apt_get_update_before_build_sh(self) -> None:
        content = generate_overlay_dockerfile("saber/crsbench/env:test")
        # apt-get update must appear before build.sh in the RUN instruction
        update_pos = content.index("apt-get update")
        build_sh_pos = content.index("bash /workspace/build.sh")
        assert update_pos < build_sh_pos

    def test_build_sh_run_contains_apt_update(self) -> None:
        """The RUN line that invokes build.sh should contain apt-get update."""
        content = generate_overlay_dockerfile("saber/crsbench/env:test")
        # Find the RUN line that contains build.sh
        for line in content.splitlines():
            stripped = line.strip()
            if "bash /workspace/build.sh" in stripped and stripped.startswith("RUN"):
                assert "apt-get update" in stripped
                break
        else:
            pytest.fail("No RUN line containing build.sh found in Dockerfile")
