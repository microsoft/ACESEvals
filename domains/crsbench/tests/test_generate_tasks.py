"""Tests for CRSBench benchmark data pipeline.

Covers:
- Pydantic models for meta.yaml parsing (CRSBenchVuln, CRSBenchHarness, CRSBenchMeta)
- Task YAML generation from benchmark metadata
- Output file naming and directory structure
"""

from __future__ import annotations

from pathlib import Path
import pytest
import yaml


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_META_YAML: dict[str, object] = {
    "patch_exclude_list": ["build.sh", "Makefile"],
    "delta_mode": {
        "base_commit": "aaa111",
        "ref_commit": "bbb222",
    },
    "full_mode": {
        "base_commit": "bbb222",
    },
    "harness_files": [
        {
            "name": "fuzz_target",
            "path": "$PROJECT/fuzz/fuzz_target.c",
            "vulns": [
                {
                    "vuln_keyword": "cpv_0",
                    "povs": [
                        {
                            "id": "pov_0",
                            "sanitizer": "address",
                            "error_token": "ERROR: AddressSanitizer: stack-buffer-overflow",
                        },
                    ],
                },
            ],
        },
    ],
    "patch_exclude_list": ["build.sh", "Makefile"],
    "project": "sanity-mock-c",
    "language": "c",
}


SAMPLE_META_MULTI_HARNESS: dict[str, object] = {
    "patch_exclude_list": ["build.sh"],
    "delta_mode": {
        "base_commit": "aaa111",
        "ref_commit": "bbb222",
    },
    "full_mode": {
        "base_commit": "bbb222",
    },
    "harness_files": [
        {
            "name": "fuzz_target",
            "path": "$PROJECT/fuzz/fuzz_target.c",
            "vulns": [
                {
                    "vuln_keyword": "cpv_0",
                    "povs": [
                        {
                            "id": "pov_0",
                            "sanitizer": "address",
                            "error_token": "ERROR: AddressSanitizer: stack-buffer-overflow",
                        },
                    ],
                },
            ],
        },
        {
            "name": "fuzz_parser",
            "path": "$PROJECT/fuzz/fuzz_parser.c",
            "vulns": [
                {
                    "vuln_keyword": "cpv_1",
                    "povs": [
                        {
                            "id": "pov_0",
                            "sanitizer": "address",
                            "error_token": "ERROR: AddressSanitizer: heap-buffer-overflow",
                        },
                    ],
                },
                {
                    "vuln_keyword": "cpv_2",
                    "povs": [
                        {
                            "id": "pov_0",
                            "sanitizer": "memory",
                            "error_token": "ERROR: MemorySanitizer: use-of-uninitialized-value",
                        },
                    ],
                },
            ],
        },
    ],
    "patch_exclude_list": ["build.sh"],
    "project": "sanity-mock-c",
    "language": "c",
}


@pytest.fixture()
def benchmark_dir(tmp_path: Path) -> Path:
    """Create a minimal benchmark directory with meta.yaml."""
    bench = tmp_path / "sanity-mock-c-delta-01"
    aixcc = bench / ".aixcc"
    aixcc.mkdir(parents=True)

    # Write meta.yaml
    meta_path = aixcc / "meta.yaml"
    meta_path.write_text(yaml.dump(SAMPLE_META_YAML))

    # Create POV blobs directory
    pov_dir = aixcc / "fuzz_target" / "cpv_0" / "blobs"
    pov_dir.mkdir(parents=True)
    (pov_dir / "pov_0.bin").write_bytes(b"\x00\x01\x02")

    # Create staged source directory
    staged = bench / "staged"
    staged.mkdir()
    (staged / "main.c").write_text("int main() { return 0; }")

    return bench


@pytest.fixture()
def multi_harness_dir(tmp_path: Path) -> Path:
    """Create a benchmark directory with multiple harnesses."""
    bench = tmp_path / "sanity-mock-c-delta-02"
    aixcc = bench / ".aixcc"
    aixcc.mkdir(parents=True)

    meta_path = aixcc / "meta.yaml"
    meta_path.write_text(yaml.dump(SAMPLE_META_MULTI_HARNESS))

    # POV blobs for both harnesses
    for harness_name, vuln_keywords in [
        ("fuzz_target", ["cpv_0"]),
        ("fuzz_parser", ["cpv_1", "cpv_2"]),
    ]:
        for vk in vuln_keywords:
            pov_dir = aixcc / harness_name / vk / "blobs"
            pov_dir.mkdir(parents=True)
            (pov_dir / "pov_0.bin").write_bytes(b"\x00")

    return bench


@pytest.fixture()
def benchmarks_root(
    tmp_path: Path,
    benchmark_dir: Path,
    multi_harness_dir: Path,
) -> Path:
    """Return the parent directory containing all benchmarks."""
    return tmp_path


# ---------------------------------------------------------------------------
# Model Tests
# ---------------------------------------------------------------------------


class TestCRSBenchModels:
    """Tests for Pydantic models parsing meta.yaml data."""

    def test_pov_model_valid(self) -> None:
        """CRSBenchPOV accepts valid POV data."""
        from crsbench.scripts.models import CRSBenchPOV

        pov = CRSBenchPOV(
            id="pov_0",
            sanitizer="address",
            error_token="ERROR: AddressSanitizer: stack-buffer-overflow",
        )
        assert pov.id == "pov_0"
        assert pov.sanitizer == "address"

    def test_vuln_model_valid(self) -> None:
        """CRSBenchVuln accepts valid vulnerability data."""
        from crsbench.scripts.models import CRSBenchPOV, CRSBenchVuln

        vuln = CRSBenchVuln(
            vuln_keyword="cpv_0",
            povs=(
                CRSBenchPOV(
                    id="pov_0",
                    sanitizer="address",
                    error_token="ERROR: AddressSanitizer: stack-buffer-overflow",
                ),
            ),
        )
        assert vuln.vuln_keyword == "cpv_0"
        assert vuln.povs[0].sanitizer == "address"
        assert vuln.sanitizer == "address"
        assert len(vuln.povs) == 1

    def test_vuln_model_frozen(self) -> None:
        """CRSBenchVuln is immutable."""
        from crsbench.scripts.models import CRSBenchPOV, CRSBenchVuln

        vuln = CRSBenchVuln(
            vuln_keyword="cpv_0",
            povs=(
                CRSBenchPOV(
                    id="pov_0",
                    sanitizer="address",
                    error_token="ERROR: AddressSanitizer: stack-buffer-overflow",
                ),
            ),
        )
        with pytest.raises(Exception):  # ValidationError for frozen model
            vuln.vuln_keyword = "cpv_1"  # type: ignore[misc]

    def test_harness_model_valid(self) -> None:
        """CRSBenchHarness accepts valid harness data."""
        from crsbench.scripts.models import CRSBenchHarness, CRSBenchPOV, CRSBenchVuln

        harness = CRSBenchHarness(
            name="fuzz_target",
            path="$PROJECT/fuzz/fuzz_target.c",
            vulns=(
                CRSBenchVuln(
                    vuln_keyword="cpv_0",
                    povs=(
                        CRSBenchPOV(
                            id="pov_0",
                            sanitizer="address",
                            error_token="ERROR: AddressSanitizer: stack-buffer-overflow",
                        ),
                    ),
                ),
            ),
        )
        assert harness.name == "fuzz_target"
        assert len(harness.vulns) == 1

    def test_meta_model_valid(self) -> None:
        """CRSBenchMeta accepts valid top-level meta.yaml data."""
        from crsbench.scripts.models import CRSBenchMeta

        meta = CRSBenchMeta(**SAMPLE_META_YAML)
        assert meta.patch_exclude_list == ("build.sh", "Makefile")
        assert meta.delta_mode is not None
        assert meta.delta_mode.base_commit == "aaa111"
        assert len(meta.harness_files) == 1
        assert meta.harness_files[0].name == "fuzz_target"
        assert len(meta.harnesses_with_vulns) == 1

    def test_meta_model_multi_harness(self) -> None:
        """CRSBenchMeta handles multiple harnesses."""
        from crsbench.scripts.models import CRSBenchMeta

        meta = CRSBenchMeta(**SAMPLE_META_MULTI_HARNESS)
        assert len(meta.harness_files) == 2
        assert meta.harness_files[1].name == "fuzz_parser"
        assert len(meta.harness_files[1].vulns) == 2

    def test_meta_model_frozen(self) -> None:
        """CRSBenchMeta is immutable."""
        from crsbench.scripts.models import CRSBenchMeta

        meta = CRSBenchMeta(**SAMPLE_META_YAML)
        with pytest.raises(Exception):
            meta.patch_exclude_list = ()  # type: ignore[misc]

    def test_meta_from_yaml_file(self, benchmark_dir: Path) -> None:
        """CRSBenchMeta can be loaded from a real meta.yaml file."""
        from crsbench.scripts.models import CRSBenchMeta

        meta_path = benchmark_dir / ".aixcc" / "meta.yaml"
        raw = yaml.safe_load(meta_path.read_text())
        meta = CRSBenchMeta(**raw)
        assert meta.patch_exclude_list == ("build.sh", "Makefile")
        assert len(meta.harnesses_with_vulns) >= 1


# ---------------------------------------------------------------------------
# generate_bugfix_task Tests
# ---------------------------------------------------------------------------


class TestGenerateBugfixTask:
    """Tests for the generate_bugfix_task function."""

    def _make_harness_and_vuln(self):
        """Helper to create a harness + vuln with new model schema."""
        from crsbench.scripts.models import CRSBenchHarness, CRSBenchPOV, CRSBenchVuln

        harness = CRSBenchHarness(
            name="fuzz_target",
            path="$PROJECT/fuzz/fuzz_target.c",
            vulns=(
                CRSBenchVuln(
                    vuln_keyword="cpv_0",
                    povs=(
                        CRSBenchPOV(
                            id="pov_0",
                            sanitizer="address",
                            error_token="ERROR: AddressSanitizer: stack-buffer-overflow",
                        ),
                    ),
                ),
            ),
        )
        return harness, harness.vulns[0]

    def test_task_id_format(self, benchmark_dir: Path) -> None:
        """Task ID uses benchmark_id__harness_name__bugfix with underscores."""
        from crsbench.scripts.generate_tasks import generate_bugfix_task

        harness, vuln = self._make_harness_and_vuln()
        task = generate_bugfix_task(benchmark_dir, harness, vuln)
        assert task["task_id"] == "sanity_mock_c_delta_01__fuzz_target__cpv_0__bugfix"

    def test_initial_context(self, benchmark_dir: Path) -> None:
        """Initial context contains project, harness_name, benchmark_id."""
        from crsbench.scripts.generate_tasks import generate_bugfix_task

        harness, vuln = self._make_harness_and_vuln()
        task = generate_bugfix_task(benchmark_dir, harness, vuln)
        ctx = task["initial_context"]
        assert ctx["project"] == "sanity-mock-c"
        assert ctx["harness_name"] == "fuzz_target"
        assert ctx["benchmark_id"] == "sanity-mock-c-delta-01"

    def test_initial_files(self, benchmark_dir: Path) -> None:
        """Initial files reference correct POV blob paths."""
        from crsbench.scripts.generate_tasks import generate_bugfix_task

        harness, vuln = self._make_harness_and_vuln()
        task = generate_bugfix_task(benchmark_dir, harness, vuln)
        files = task["initial_files"]
        assert "/workspace/povs/" in files
        assert "cpv_0/blobs/" in files["/workspace/povs/"]
        assert not any("build" in key for key in files), (
            f"No build/ entries expected in initial_files, got: {list(files.keys())}"
        )

    def test_no_build_directory_in_initial_files(self, benchmark_dir: Path) -> None:
        """initial_files must not contain any build/ keys or values."""
        from crsbench.scripts.generate_tasks import generate_bugfix_task

        harness, vuln = self._make_harness_and_vuln()
        task = generate_bugfix_task(benchmark_dir, harness, vuln)
        files = task["initial_files"]
        assert not any("build/" in key for key in files), (
            f"No build/ key expected in initial_files, got: {list(files.keys())}"
        )
        assert not any("/build/" in str(v) for v in files.values()), (
            f"No /build/ value expected in initial_files, got: {list(files.values())}"
        )

    def test_scoring_structure(self, benchmark_dir: Path) -> None:
        """Scoring includes crsbench_patch_verify, llm_judge, tool_call."""
        from crsbench.scripts.generate_tasks import generate_bugfix_task

        harness, vuln = self._make_harness_and_vuln()
        task = generate_bugfix_task(benchmark_dir, harness, vuln)
        scoring = task["scoring"]
        assert "crsbench_patch_verify" in scoring
        assert "llm_judge" in scoring
        assert "tool_call" in scoring

        # Verify submission scorer details
        sub = scoring["crsbench_patch_verify"]["submission"]
        assert sub["target"] == "submission"
        assert sub["harness_name"] == "fuzz_target"
        assert sub["max_score"] == 1.0

    def test_scoring_aggregation(self, benchmark_dir: Path) -> None:
        """Scoring aggregation uses average."""
        from crsbench.scripts.generate_tasks import generate_bugfix_task

        harness, vuln = self._make_harness_and_vuln()
        task = generate_bugfix_task(benchmark_dir, harness, vuln)
        agg = task["scoring_aggregation"]
        assert "average" in agg

    def test_title_and_description(self, benchmark_dir: Path) -> None:
        """Task has a meaningful title and description."""
        from crsbench.scripts.generate_tasks import generate_bugfix_task

        harness, vuln = self._make_harness_and_vuln()
        task = generate_bugfix_task(benchmark_dir, harness, vuln)
        assert "title" in task
        assert "description" in task
        assert "fuzz_target" in task["title"]


# ---------------------------------------------------------------------------
# generate_all_tasks Tests
# ---------------------------------------------------------------------------


class TestGenerateAllTasks:
    """Tests for the full pipeline: reading benchmarks and writing YAMLs."""

    def test_generates_task_files(
        self,
        benchmarks_root: Path,
        tmp_path: Path,
    ) -> None:
        """Task YAML files are created for each benchmark-harness pair."""
        from crsbench.scripts.generate_tasks import generate_all_tasks

        output_dir = tmp_path / "output_tasks"
        generate_all_tasks(benchmarks_root, output_dir)

        # Should have generated task YAMLs
        yaml_files = list(output_dir.rglob("*.yaml"))
        assert len(yaml_files) >= 1

    def test_task_yaml_is_valid(
        self,
        benchmarks_root: Path,
        tmp_path: Path,
    ) -> None:
        """Generated YAML files are valid and parseable."""
        from crsbench.scripts.generate_tasks import generate_all_tasks

        output_dir = tmp_path / "output_tasks"
        generate_all_tasks(benchmarks_root, output_dir)

        for yaml_file in output_dir.rglob("*.yaml"):
            if yaml_file.name == "shared.yaml":
                continue
            content = yaml.safe_load(yaml_file.read_text())
            assert "tasks" in content
            for task in content["tasks"]:
                assert "task_id" in task
                assert "scoring" in task
                assert "initial_context" in task

    def test_output_directory_structure(
        self,
        benchmarks_root: Path,
        tmp_path: Path,
    ) -> None:
        """Tasks are grouped into project directories."""
        from crsbench.scripts.generate_tasks import generate_all_tasks

        output_dir = tmp_path / "output_tasks"
        generate_all_tasks(benchmarks_root, output_dir)

        # Should have at least one group directory
        subdirs = [d for d in output_dir.iterdir() if d.is_dir()]
        assert len(subdirs) >= 1

    def test_shared_yaml_created(
        self,
        benchmarks_root: Path,
        tmp_path: Path,
    ) -> None:
        """A shared.yaml is created per group directory."""
        from crsbench.scripts.generate_tasks import generate_all_tasks

        output_dir = tmp_path / "output_tasks"
        generate_all_tasks(benchmarks_root, output_dir)

        for subdir in output_dir.iterdir():
            if subdir.is_dir():
                shared = subdir / "shared.yaml"
                assert shared.exists(), f"Missing shared.yaml in {subdir}"
                content = yaml.safe_load(shared.read_text())
                assert "sandbox_environment" in content

    def test_multi_harness_generates_multiple_tasks(
        self,
        multi_harness_dir: Path,
        tmp_path: Path,
    ) -> None:
        """A benchmark with multiple harnesses generates multiple task files."""
        from crsbench.scripts.generate_tasks import generate_all_tasks

        # Use parent directory that contains only the multi-harness benchmark
        output_dir = tmp_path / "output_multi"
        generate_all_tasks(multi_harness_dir.parent, output_dir)

        yaml_files = [f for f in output_dir.rglob("*.yaml") if f.name != "shared.yaml"]
        # multi_harness has 2 harnesses with 1+2 vulns = 3 task files
        assert len(yaml_files) == 3

    def test_task_id_is_unique(
        self,
        benchmarks_root: Path,
        tmp_path: Path,
    ) -> None:
        """All generated task IDs are unique across all files."""
        from crsbench.scripts.generate_tasks import generate_all_tasks

        output_dir = tmp_path / "output_unique"
        generate_all_tasks(benchmarks_root, output_dir)

        task_ids: list[str] = []
        for yaml_file in output_dir.rglob("*.yaml"):
            if yaml_file.name == "shared.yaml":
                continue
            content = yaml.safe_load(yaml_file.read_text())
            for task in content["tasks"]:
                task_ids.append(task["task_id"])

        assert len(task_ids) == len(set(task_ids)), f"Duplicate task IDs: {task_ids}"

    def test_empty_benchmarks_dir(self, tmp_path: Path) -> None:
        """An empty benchmarks directory produces no tasks."""
        from crsbench.scripts.generate_tasks import generate_all_tasks

        benchmarks_dir = tmp_path / "empty_benchmarks"
        benchmarks_dir.mkdir()
        output_dir = tmp_path / "output_empty"

        result = generate_all_tasks(benchmarks_dir, output_dir)
        assert result == []


# ---------------------------------------------------------------------------
# load_benchmark_meta Tests
# ---------------------------------------------------------------------------


class TestLoadBenchmarkMeta:
    """Tests for loading meta.yaml from a benchmark directory."""

    def test_loads_valid_meta(self, benchmark_dir: Path) -> None:
        """Loads and parses a valid meta.yaml."""
        from crsbench.scripts.generate_tasks import load_benchmark_meta

        meta = load_benchmark_meta(benchmark_dir)
        assert meta.patch_exclude_list == ("build.sh", "Makefile")
        assert len(meta.harness_files) == 1
        assert len(meta.harnesses_with_vulns) >= 1

    def test_raises_on_missing_meta(self, tmp_path: Path) -> None:
        """Raises FileNotFoundError when meta.yaml is missing."""
        from crsbench.scripts.generate_tasks import load_benchmark_meta

        with pytest.raises(FileNotFoundError):
            load_benchmark_meta(tmp_path / "nonexistent")

    def test_raises_on_invalid_yaml(self, tmp_path: Path) -> None:
        """Raises ValueError on malformed meta.yaml."""
        from crsbench.scripts.generate_tasks import load_benchmark_meta

        bench = tmp_path / "bad-benchmark"
        aixcc = bench / ".aixcc"
        aixcc.mkdir(parents=True)
        (aixcc / "meta.yaml").write_text("not: valid: yaml: [")

        with pytest.raises(yaml.scanner.ScannerError):
            load_benchmark_meta(bench)


# ---------------------------------------------------------------------------
# generate_all_tasks with datasets filter
# ---------------------------------------------------------------------------


class TestGenerateAllTasksDatasetFilter:
    """Tests for generate_all_tasks() with the datasets filter parameter."""

    def test_datasets_none_processes_all(
        self,
        benchmarks_root: Path,
        tmp_path: Path,
    ) -> None:
        """datasets=None processes all benchmarks (current default behavior)."""
        from crsbench.scripts.generate_tasks import generate_all_tasks

        output_dir = tmp_path / "out_all"
        result = generate_all_tasks(benchmarks_root, output_dir, datasets=None)
        # Should find tasks for both benchmark fixtures
        task_files = [f for f in result if f.name != "shared.yaml"]
        assert len(task_files) >= 2

    def test_datasets_filters_to_matching(
        self,
        benchmarks_root: Path,
        tmp_path: Path,
    ) -> None:
        """Only benchmarks whose names are in datasets list are processed."""
        from crsbench.scripts.generate_tasks import generate_all_tasks

        output_dir = tmp_path / "out_filtered"
        result = generate_all_tasks(
            benchmarks_root,
            output_dir,
            datasets=["sanity-mock-c-delta-01"],
        )
        # Only benchmarks matching sanity-mock-c-delta-01 processed
        task_files = [f for f in result if f.name != "shared.yaml"]
        assert len(task_files) == 1
        assert "sanity_mock_c" in task_files[0].parent.name

    def test_datasets_empty_list_generates_nothing(
        self,
        benchmarks_root: Path,
        tmp_path: Path,
    ) -> None:
        """An empty datasets list generates no tasks."""
        from crsbench.scripts.generate_tasks import generate_all_tasks

        output_dir = tmp_path / "out_empty"
        result = generate_all_tasks(benchmarks_root, output_dir, datasets=[])
        assert result == []

    def test_datasets_nonexistent_name_generates_nothing(
        self,
        benchmarks_root: Path,
        tmp_path: Path,
    ) -> None:
        """A datasets list with no matching benchmarks generates nothing."""
        from crsbench.scripts.generate_tasks import generate_all_tasks

        output_dir = tmp_path / "out_no_match"
        result = generate_all_tasks(
            benchmarks_root, output_dir, datasets=["nonexistent-benchmark"]
        )
        assert result == []


# ---------------------------------------------------------------------------
# _write_shared_yaml Tests
# ---------------------------------------------------------------------------


class TestWriteSharedYaml:
    """Tests for the _write_shared_yaml helper function."""

    def test_write_shared_yaml_includes_dataset(self, tmp_path: Path) -> None:
        """Generated shared.yaml contains the full expected structure."""
        from crsbench.scripts.generate_tasks import _write_shared_yaml

        group_dir = tmp_path / "sanity_mock_c"
        group_dir.mkdir()
        _write_shared_yaml(group_dir, dataset="sanity_mock_c")

        shared_path = group_dir / "shared.yaml"
        assert shared_path.exists()
        content = yaml.safe_load(shared_path.read_text())
        assert content == {
            "dataset": "sanity_mock_c",
            "sandbox_environment": "default",
            "initial_context": {
                "sanitizer": "address",
                "mode": "bug_fixing",
            },
        }

    def test_write_shared_yaml_overwrites_existing(self, tmp_path: Path) -> None:
        """Calling _write_shared_yaml when shared.yaml exists overwrites it."""
        from crsbench.scripts.generate_tasks import _write_shared_yaml

        group_dir = tmp_path / "my_group"
        group_dir.mkdir()

        # Write initial shared.yaml without dataset
        shared_path = group_dir / "shared.yaml"
        shared_path.write_text(yaml.dump({"sandbox_environment": "old"}))

        # Overwrite with new content
        _write_shared_yaml(group_dir, dataset="my_group")

        content = yaml.safe_load(shared_path.read_text())
        assert content["dataset"] == "my_group"
        assert content["sandbox_environment"] == "default"


# ---------------------------------------------------------------------------
# 2.2 — generate_bugfix_task pre-built image support
# ---------------------------------------------------------------------------


class TestGenerateBugfixTaskPrebuilt:
    """Tests for generate_bugfix_task with pre-built image support."""

    def test_initial_files_includes_source_for_fallback(
        self, benchmark_dir: Path
    ) -> None:
        from crsbench.scripts.generate_tasks import (
            generate_bugfix_task,
            load_benchmark_meta,
        )

        meta = load_benchmark_meta(benchmark_dir)
        harness = meta.harness_files[0]
        vuln = harness.vulns[0]
        task = generate_bugfix_task(benchmark_dir, harness, vuln)
        initial_files = task["initial_files"]
        assert "/workspace/source" in initial_files
        assert "/workspace/povs/" in initial_files

    def test_initial_context_has_benchmark_image(self, benchmark_dir: Path) -> None:
        from crsbench.scripts.generate_tasks import (
            generate_bugfix_task,
            load_benchmark_meta,
        )

        meta = load_benchmark_meta(benchmark_dir)
        harness = meta.harness_files[0]
        vuln = harness.vulns[0]
        task = generate_bugfix_task(benchmark_dir, harness, vuln)
        ctx = task["initial_context"]
        expected_tag = f"saber/crsbench/benchmark:{benchmark_dir.name}"
        assert ctx["benchmark_image"] == expected_tag

    def test_initial_context_preserves_existing_keys(self, benchmark_dir: Path) -> None:
        from crsbench.scripts.generate_tasks import (
            generate_bugfix_task,
            load_benchmark_meta,
        )

        meta = load_benchmark_meta(benchmark_dir)
        harness = meta.harness_files[0]
        vuln = harness.vulns[0]
        task = generate_bugfix_task(benchmark_dir, harness, vuln)
        ctx = task["initial_context"]
        assert "project" in ctx
        assert "harness_name" in ctx
        assert "benchmark_id" in ctx
        assert "benchmark_image" in ctx
