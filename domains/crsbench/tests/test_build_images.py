"""Tests for crsbench.scripts.build_images — Docker image build primitives."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from crsbench.scripts.build_images import (
    ImageBuildResult,
    ImageBuildSummary,
    _cleanup_dockerignore,
    _read_saber_tooling,
    _write_dockerignore,
    build_all_benchmark_images,
    build_benchmark_image,
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


# ---------------------------------------------------------------------------
# 1.1 — Models
# ---------------------------------------------------------------------------


class TestImageBuildResult:
    """Tests for the ImageBuildResult Pydantic model."""

    def test_frozen(self) -> None:
        result = ImageBuildResult(
            benchmark_id="afc-curl-delta-01",
            image_tag="saber/crsbench/benchmark:afc-curl-delta-01",
            success=True,
            skipped=False,
        )
        with pytest.raises(ValidationError):
            result.benchmark_id = "other"  # type: ignore[misc]

    def test_success_result(self) -> None:
        result = ImageBuildResult(
            benchmark_id="afc-curl-delta-01",
            image_tag="saber/crsbench/benchmark:afc-curl-delta-01",
            success=True,
            skipped=False,
            duration_seconds=12.5,
        )
        assert result.success is True
        assert result.error_message is None

    def test_failed_result(self) -> None:
        result = ImageBuildResult(
            benchmark_id="afc-curl-delta-01",
            image_tag="saber/crsbench/benchmark:afc-curl-delta-01",
            success=False,
            skipped=False,
            error_message="build.sh failed with exit code 1",
        )
        assert result.success is False
        assert result.error_message is not None

    def test_skipped_result(self) -> None:
        result = ImageBuildResult(
            benchmark_id="afc-curl-delta-01",
            image_tag="saber/crsbench/benchmark:afc-curl-delta-01",
            success=True,
            skipped=True,
        )
        assert result.skipped is True


class TestImageBuildSummary:
    """Tests for the ImageBuildSummary aggregate model."""

    def test_counts_consistent(self) -> None:
        results = (
            ImageBuildResult(
                benchmark_id="a",
                image_tag="t:a",
                success=True,
                skipped=False,
            ),
            ImageBuildResult(
                benchmark_id="b",
                image_tag="t:b",
                success=True,
                skipped=True,
            ),
            ImageBuildResult(
                benchmark_id="c",
                image_tag="t:c",
                success=False,
                skipped=False,
                error_message="err",
            ),
        )
        summary = ImageBuildSummary(
            total=3,
            built=1,
            skipped=1,
            failed=1,
            results=results,
        )
        assert summary.total == summary.built + summary.skipped + summary.failed

    def test_frozen(self) -> None:
        summary = ImageBuildSummary(
            total=0,
            built=0,
            skipped=0,
            failed=0,
            results=(),
        )
        with pytest.raises(ValidationError):
            summary.total = 5  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 1.2 — Tag helpers
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
# 1.3 — generate_overlay_dockerfile
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
# 1.4 — image_exists
# ---------------------------------------------------------------------------


class TestImageExists:
    @pytest.mark.asyncio
    async def test_returns_true_when_image_present(self) -> None:
        with patch(
            "crsbench.scripts.build_images._run_docker_cmd",
            return_value=(0, "", ""),
        ):
            assert await image_exists("saber/crsbench/benchmark:test") is True

    @pytest.mark.asyncio
    async def test_returns_false_when_image_absent(self) -> None:
        with patch(
            "crsbench.scripts.build_images._run_docker_cmd",
            return_value=(1, "", "No such image"),
        ):
            assert await image_exists("saber/crsbench/benchmark:test") is False


# ---------------------------------------------------------------------------
# 1.4b — .dockerignore helpers
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
# 1.5 — build_benchmark_image
# ---------------------------------------------------------------------------


class TestBuildBenchmarkImage:
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
            result = await build_benchmark_image(bench)
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
            result = await build_benchmark_image(bench, force=False)
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
            result = await build_benchmark_image(bench, force=True)
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
            await build_benchmark_image(bench)
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
            await build_benchmark_image(bench)
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
            result = await build_benchmark_image(bench)
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
            result = await build_benchmark_image(bench)
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
            result = await build_benchmark_image(bench)
        # Should only have one docker build call (Layer 2), not two
        build_calls = [c for c in calls if "build" in c]
        assert len(build_calls) == 1
        assert result.success is True

    @pytest.mark.asyncio
    async def test_missing_staged_dir_returns_error(self, tmp_path: Path) -> None:
        bench = tmp_path / "empty-bench-delta-01"
        bench.mkdir()
        result = await build_benchmark_image(bench)
        assert result.success is False
        assert "staged" in (result.error_message or "").lower()

    @pytest.mark.asyncio
    async def test_empty_staged_dir_returns_error(self, tmp_path: Path) -> None:
        bench = tmp_path / "empty-staged-delta-01"
        bench.mkdir()
        (bench / "staged").mkdir()  # exists but empty
        (bench / "Dockerfile").write_text("FROM ubuntu\n")
        result = await build_benchmark_image(bench)
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
            result = await build_benchmark_image(bench)
        assert result.success is False
        assert "timeout" in (result.error_message or "").lower()

    @pytest.mark.asyncio
    async def test_missing_benchmark_dockerfile_returns_error(
        self, tmp_path: Path
    ) -> None:
        bench = _create_benchmark_dir(tmp_path, "test-bench-delta-01")
        (bench / "Dockerfile").unlink()
        result = await build_benchmark_image(bench)
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
            result = await build_benchmark_image(bench)
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
            await build_benchmark_image(bench)
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
            await build_benchmark_image(bench)
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
            await build_benchmark_image(bench)
        assert not (bench / "Dockerfile.saber").exists()


# ---------------------------------------------------------------------------
# 1.6 — build_all_benchmark_images
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
# 4.3 — Integration tests (Docker required)
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
        result = await build_benchmark_image(bench_dir, force=True)
        assert result.success is True
        assert await image_exists(result.image_tag)

    @pytest.mark.asyncio
    async def test_image_has_source_at_workspace(self) -> None:
        """Built image has source code at /workspace/source/."""
        tag = "saber/crsbench/benchmark:sanity-mock-c-delta-01"
        if not await image_exists(tag):
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
        if not await image_exists(tag):
            pytest.skip("Image not built")
        from crsbench.scripts.build_images import _run_docker_cmd

        returncode, stdout, _ = await _run_docker_cmd(
            ["docker", "run", "--rm", tag, "which", "node"],
        )
        assert returncode == 0
        assert "node" in stdout


# ---------------------------------------------------------------------------
# 2.1 — Compose env-var interpolation
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
# 2.4 — Git init resilience
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
