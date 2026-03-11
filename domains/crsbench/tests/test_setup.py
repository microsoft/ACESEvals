"""Tests for crsbench.setup — domain setup hooks."""

from __future__ import annotations

import os
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from saber.hooks import SetupHook

from crsbench.setup import (
    DownloadBenchmarkData,
    LinkDataDir,
    _cli_bool,
    _expand_group,
    _parse_csv,
    _sanitize_staged_dir,
    clean_task_dirs,
    download_benchmarks,
    extract_all_tarballs,
    extract_benchmark_tarballs,
    get_hooks,
)


def _mock_build_summary(
    built: int = 0, skipped: int = 0, failed: int = 0
) -> MagicMock:
    """Create a mock ImageBuildSummary with the given counts."""
    summary = MagicMock()
    summary.built = built
    summary.skipped = skipped
    summary.failed = failed
    summary.results = []
    return summary


def _ensure_huggingface_hub_mock() -> MagicMock:
    """Insert a mock ``huggingface_hub`` into ``sys.modules`` if missing.

    Returns the mock's ``snapshot_download`` callable so tests can assert
    on it.  The mock is only inserted when the real package is absent,
    keeping the tests runnable both with and without the optional dep.
    """
    if "huggingface_hub" not in sys.modules:
        mod = types.ModuleType("huggingface_hub")
        mod.snapshot_download = MagicMock()  # type: ignore[attr-defined]
        sys.modules["huggingface_hub"] = mod
    return sys.modules["huggingface_hub"].snapshot_download  # type: ignore[union-attr]


# Ensure huggingface_hub is importable for all tests in this module.
_ensure_huggingface_hub_mock()


# ---------------------------------------------------------------------------
# LinkDataDir tests
# ---------------------------------------------------------------------------


class TestLinkDataDir:
    def test_satisfies_protocol(self) -> None:
        hook = LinkDataDir("/tmp/data")
        assert isinstance(hook, SetupHook)

    def test_name(self) -> None:
        assert LinkDataDir("/tmp/data").name == "link_data_dir"

    def test_should_run_when_no_data_dir(self, tmp_path: Path) -> None:
        target = tmp_path / "external_data"
        hook = LinkDataDir(str(target))
        domain_root = tmp_path / "domain"
        domain_root.mkdir()
        assert hook.should_run(domain_root) is True

    def test_should_not_run_when_already_linked(self, tmp_path: Path) -> None:
        target = tmp_path / "external_data"
        target.mkdir()
        domain_root = tmp_path / "domain"
        domain_root.mkdir()
        os.symlink(str(target), str(domain_root / "data"))
        hook = LinkDataDir(str(target))
        assert hook.should_run(domain_root) is False

    def test_should_run_when_linked_to_wrong_target(self, tmp_path: Path) -> None:
        old_target = tmp_path / "old_data"
        old_target.mkdir()
        new_target = tmp_path / "new_data"
        domain_root = tmp_path / "domain"
        domain_root.mkdir()
        os.symlink(str(old_target), str(domain_root / "data"))
        hook = LinkDataDir(str(new_target))
        assert hook.should_run(domain_root) is True

    def test_should_not_run_when_real_dir_with_content(self, tmp_path: Path) -> None:
        domain_root = tmp_path / "domain"
        data_dir = domain_root / "data"
        data_dir.mkdir(parents=True)
        (data_dir / "file.txt").write_text("content")
        hook = LinkDataDir(str(tmp_path / "external"))
        assert hook.should_run(domain_root) is False

    def test_should_run_when_real_dir_empty(self, tmp_path: Path) -> None:
        domain_root = tmp_path / "domain"
        (domain_root / "data").mkdir(parents=True)
        hook = LinkDataDir(str(tmp_path / "external"))
        assert hook.should_run(domain_root) is True

    def test_run_creates_symlink(self, tmp_path: Path) -> None:
        target = tmp_path / "external_data"
        domain_root = tmp_path / "domain"
        domain_root.mkdir()
        hook = LinkDataDir(str(target))
        hook.run(domain_root)

        link = domain_root / "data"
        assert link.is_symlink()
        assert link.resolve() == target.resolve()
        assert target.is_dir()

    def test_run_creates_target_dir(self, tmp_path: Path) -> None:
        target = tmp_path / "nested" / "external_data"
        domain_root = tmp_path / "domain"
        domain_root.mkdir()
        hook = LinkDataDir(str(target))
        hook.run(domain_root)
        assert target.is_dir()

    def test_run_replaces_empty_dir(self, tmp_path: Path) -> None:
        domain_root = tmp_path / "domain"
        (domain_root / "data").mkdir(parents=True)
        target = tmp_path / "external"
        hook = LinkDataDir(str(target))
        hook.run(domain_root)
        assert (domain_root / "data").is_symlink()

    def test_run_replaces_stale_symlink(self, tmp_path: Path) -> None:
        old_target = tmp_path / "old"
        old_target.mkdir()
        domain_root = tmp_path / "domain"
        domain_root.mkdir()
        os.symlink(str(old_target), str(domain_root / "data"))

        new_target = tmp_path / "new"
        hook = LinkDataDir(str(new_target))
        hook.run(domain_root)

        link = domain_root / "data"
        assert link.is_symlink()
        assert link.resolve() == new_target.resolve()

    def test_run_skips_real_dir_with_content(self, tmp_path: Path) -> None:
        domain_root = tmp_path / "domain"
        data_dir = domain_root / "data"
        data_dir.mkdir(parents=True)
        (data_dir / "important.txt").write_text("keep me")
        hook = LinkDataDir(str(tmp_path / "external"))
        hook.run(domain_root)
        # Should NOT be a symlink — original data preserved
        assert not data_dir.is_symlink()
        assert (data_dir / "important.txt").read_text() == "keep me"


# ---------------------------------------------------------------------------
# get_hooks tests
# ---------------------------------------------------------------------------


class TestGetHooks:
    def test_default_hooks_count(self, tmp_path: Path) -> None:
        hooks = get_hooks(tmp_path)
        assert len(hooks) == 4
        assert hooks[0].name == "download_benchmark_data"

    def test_data_dir_adds_link_hook(self, tmp_path: Path) -> None:
        hooks = get_hooks(tmp_path, data_dir="/mnt/crsbench_data")
        assert len(hooks) == 5
        assert hooks[0].name == "link_data_dir"
        assert hooks[1].name == "download_benchmark_data"

    def test_no_data_dir_no_link_hook(self, tmp_path: Path) -> None:
        hooks = get_hooks(tmp_path)
        assert all(h.name != "link_data_dir" for h in hooks)


class TestDownloadBenchmarkData:
    def test_satisfies_protocol(self) -> None:
        hook = DownloadBenchmarkData()
        assert isinstance(hook, SetupHook)

    def test_name(self) -> None:
        assert DownloadBenchmarkData().name == "download_benchmark_data"

    def test_should_run_when_dir_missing(self, tmp_path: Path) -> None:
        hook = DownloadBenchmarkData()
        assert hook.should_run(tmp_path) is True

    def test_should_run_when_dir_empty(self, tmp_path: Path) -> None:
        (tmp_path / "data" / "benchmarks").mkdir(parents=True)
        hook = DownloadBenchmarkData()
        assert hook.should_run(tmp_path) is True

    def test_should_not_run_when_fully_staged(self, tmp_path: Path) -> None:
        """Returns False when benchmarks have meta.yaml, staged content, and tasks."""
        benchmarks = tmp_path / "data" / "benchmarks"
        bm = benchmarks / "benchmark_001"
        (bm / ".aixcc").mkdir(parents=True)
        (bm / ".aixcc" / "meta.yaml").write_text("id: benchmark_001")
        staged = bm / "staged"
        staged.mkdir()
        (staged / "main.c").write_text("int main(){}")
        # Task YAMLs must also exist (with benchmark_image for image-build detection)
        tasks = tmp_path / "tasks"
        tasks.mkdir()
        (tasks / "benchmark_001__bugfix.yaml").write_text(
            "tasks:\n- initial_context:\n    benchmark_image: saber/crsbench/benchmark:benchmark_001\n"
        )
        hook = DownloadBenchmarkData()
        assert hook.should_run(tmp_path) is False

    def test_should_run_when_data_present_but_not_staged(self, tmp_path: Path) -> None:
        """Returns True when benchmarks exist but are not staged."""
        benchmarks = tmp_path / "data" / "benchmarks"
        bm = benchmarks / "benchmark_001"
        (bm / ".aixcc").mkdir(parents=True)
        (bm / ".aixcc" / "meta.yaml").write_text("id: benchmark_001")
        # No staged/ directory
        hook = DownloadBenchmarkData()
        assert hook.should_run(tmp_path) is True

    def test_should_run_when_staged_dir_empty_unfiltered(self, tmp_path: Path) -> None:
        """Returns True when staged dir exists but is empty (no filter)."""
        benchmarks = tmp_path / "data" / "benchmarks"
        bm = benchmarks / "benchmark_001"
        (bm / ".aixcc").mkdir(parents=True)
        (bm / ".aixcc" / "meta.yaml").write_text("id: benchmark_001")
        (bm / "staged").mkdir()
        hook = DownloadBenchmarkData()
        assert hook.should_run(tmp_path) is True

    def test_should_run_when_only_non_benchmark_dirs(self, tmp_path: Path) -> None:
        """Returns True when dir has content but no benchmark subdirectories."""
        benchmarks = tmp_path / "data" / "benchmarks"
        benchmarks.mkdir(parents=True)
        (benchmarks / "README.md").write_text("info")
        hook = DownloadBenchmarkData()
        assert hook.should_run(tmp_path) is True

    def test_should_run_true_when_force_build(self, tmp_path: Path) -> None:
        """Returns True when force_build is set even if everything is staged."""
        benchmarks = tmp_path / "data" / "benchmarks"
        bm = benchmarks / "benchmark_001"
        (bm / ".aixcc").mkdir(parents=True)
        (bm / ".aixcc" / "meta.yaml").write_text("id: benchmark_001")
        staged = bm / "staged"
        staged.mkdir()
        (staged / "main.c").write_text("int main(){}")
        tasks = tmp_path / "tasks"
        tasks.mkdir()
        (tasks / "benchmark_001.yaml").write_text(
            "tasks:\n- initial_context:\n    benchmark_image: saber/crsbench/benchmark:benchmark_001\n"
        )
        hook = DownloadBenchmarkData(force_build=True)
        assert hook.should_run(tmp_path) is True

    def test_should_run_true_when_rebuild_images(self, tmp_path: Path) -> None:
        """Returns True when rebuild_images is set."""
        benchmarks = tmp_path / "data" / "benchmarks"
        bm = benchmarks / "benchmark_001"
        (bm / ".aixcc").mkdir(parents=True)
        (bm / ".aixcc" / "meta.yaml").write_text("id: benchmark_001")
        staged = bm / "staged"
        staged.mkdir()
        (staged / "main.c").write_text("int main(){}")
        tasks = tmp_path / "tasks"
        tasks.mkdir()
        (tasks / "benchmark_001.yaml").write_text(
            "tasks:\n- initial_context:\n    benchmark_image: saber/crsbench/benchmark:benchmark_001\n"
        )
        hook = DownloadBenchmarkData(rebuild_images="afc-curl")
        assert hook.should_run(tmp_path) is True

    def test_should_run_true_when_yamls_missing_benchmark_image(self, tmp_path: Path) -> None:
        """Returns True when task YAMLs exist but lack benchmark_image."""
        benchmarks = tmp_path / "data" / "benchmarks"
        bm = benchmarks / "benchmark_001"
        (bm / ".aixcc").mkdir(parents=True)
        (bm / ".aixcc" / "meta.yaml").write_text("id: benchmark_001")
        staged = bm / "staged"
        staged.mkdir()
        (staged / "main.c").write_text("int main(){}")
        tasks = tmp_path / "tasks"
        tasks.mkdir()
        (tasks / "benchmark_001.yaml").write_text("tasks: []")
        hook = DownloadBenchmarkData()
        assert hook.should_run(tmp_path) is True

    def test_run_calls_download_default(self, tmp_path: Path) -> None:
        """run() delegates to download_benchmarks() with defaults."""
        hook = DownloadBenchmarkData()
        with patch("crsbench.setup.download_benchmarks") as mock_dl:
            hook.run(tmp_path)
            mock_dl.assert_called_once_with(
                tmp_path / "data" / "benchmarks",
                include_ground_truth=True,
                benchmarks=None,
            )

    def test_run_passes_config(self, tmp_path: Path) -> None:
        """run() forwards include_ground_truth and datasets (as benchmarks kwarg)."""
        hook = DownloadBenchmarkData(
            include_ground_truth=False,
            datasets=["afc-curl-delta-01"],
        )
        with patch("crsbench.setup.download_benchmarks") as mock_dl:
            hook.run(tmp_path)
            mock_dl.assert_called_once_with(
                tmp_path / "data" / "benchmarks",
                include_ground_truth=False,
                benchmarks=["afc-curl-delta-01"],
            )


class TestDownloadBenchmarks:
    """Tests for the download_benchmarks function."""

    def test_calls_snapshot_download_all(self, tmp_path: Path) -> None:
        """Default: download all benchmarks with ground truth."""
        with patch("huggingface_hub.snapshot_download", return_value=str(tmp_path)) as mock_snap:
            download_benchmarks(tmp_path)
            mock_snap.assert_called_once_with(
                repo_id="sslab-gatech/crsbench-dataset",
                repo_type="dataset",
                local_dir=str(tmp_path),
                allow_patterns=None,
            )

    def test_calls_snapshot_download_no_ground_truth(self, tmp_path: Path) -> None:
        """Without ground truth: filters to benchmark.tar.gz only."""
        with patch("huggingface_hub.snapshot_download", return_value=str(tmp_path)) as mock_snap:
            download_benchmarks(tmp_path, include_ground_truth=False)
            mock_snap.assert_called_once_with(
                repo_id="sslab-gatech/crsbench-dataset",
                repo_type="dataset",
                local_dir=str(tmp_path),
                allow_patterns=["*/benchmark.tar.gz"],
            )

    def test_calls_snapshot_download_specific_benchmarks(self, tmp_path: Path) -> None:
        """Specific benchmarks: filters to those benchmark directories."""
        with patch("huggingface_hub.snapshot_download", return_value=str(tmp_path)) as mock_snap:
            download_benchmarks(
                tmp_path, benchmarks=["afc-curl-delta-01", "afc-curl-delta-02"]
            )
            mock_snap.assert_called_once_with(
                repo_id="sslab-gatech/crsbench-dataset",
                repo_type="dataset",
                local_dir=str(tmp_path),
                allow_patterns=[
                    "afc-curl-delta-01/**",
                    "afc-curl-delta-02/**",
                ],
            )

    def test_creates_output_dir(self, tmp_path: Path) -> None:
        """download_benchmarks creates the output directory if missing."""
        out = tmp_path / "nested" / "dir"
        with patch("huggingface_hub.snapshot_download", return_value=str(out)):
            download_benchmarks(out)
        assert out.exists()

    def test_returns_path(self, tmp_path: Path) -> None:
        """download_benchmarks returns a Path to the snapshot."""
        with patch("huggingface_hub.snapshot_download", return_value=str(tmp_path)):
            result = download_benchmarks(tmp_path)
        assert result == tmp_path

    def test_raises_import_error_when_hub_missing(self, tmp_path: Path) -> None:
        """Raises ImportError with install instructions when huggingface_hub absent."""
        import builtins

        import pytest

        # Temporarily hide the mock module so the lazy import fails
        saved = sys.modules.pop("huggingface_hub", None)
        original_import = builtins.__import__

        def block_hf(name: str, *args: object, **kwargs: object) -> object:
            if name == "huggingface_hub":
                raise ImportError("No module named 'huggingface_hub'")
            return original_import(name, *args, **kwargs)

        try:
            with patch.object(builtins, "__import__", side_effect=block_hf):
                with pytest.raises(ImportError, match="oss_saber.*crsbench"):
                    download_benchmarks(tmp_path)
        finally:
            # Restore mock so other tests aren't affected
            if saved is not None:
                sys.modules["huggingface_hub"] = saved


class TestDownloadBenchmarkDataForceDownload:
    """Tests for DownloadBenchmarkData.force_download behaviour."""

    def test_should_run_true_when_force_download_and_data_present(
        self, tmp_path: Path
    ) -> None:
        """force_download=True overrides the data-exists guard."""
        benchmarks = tmp_path / "data" / "benchmarks"
        benchmarks.mkdir(parents=True)
        (benchmarks / "some_benchmark").mkdir()

        hook = DownloadBenchmarkData(force_download=True)
        assert hook.should_run(tmp_path) is True

    def test_should_run_uses_guard_when_force_download_false(
        self, tmp_path: Path
    ) -> None:
        """force_download=False (default) still checks staging status."""
        benchmarks = tmp_path / "data" / "benchmarks"
        bm = benchmarks / "some_benchmark"
        (bm / ".aixcc").mkdir(parents=True)
        (bm / ".aixcc" / "meta.yaml").write_text("id: some_benchmark")
        staged = bm / "staged"
        staged.mkdir()
        (staged / "main.c").write_text("int main(){}")
        # Task YAMLs must also exist (with benchmark_image)
        tasks = tmp_path / "tasks"
        tasks.mkdir()
        (tasks / "some_benchmark__bugfix.yaml").write_text(
            "tasks:\n- initial_context:\n    benchmark_image: saber/crsbench/benchmark:some_benchmark\n"
        )

        hook = DownloadBenchmarkData(force_download=False)
        assert hook.should_run(tmp_path) is False


class TestGetHooksKwargs:
    """Tests for get_hooks() with CLI -T kwargs."""

    def test_dataset_csv_parsed(self) -> None:
        hooks = get_hooks(Path("/unused"), dataset="a,b")
        assert hooks[0]._datasets == ["a", "b"]

    def test_dataset_single_value(self) -> None:
        hooks = get_hooks(Path("/unused"), dataset="sanity-mock-c-delta-01")
        assert hooks[0]._datasets == ["sanity-mock-c-delta-01"]

    def test_include_ground_truth_false(self) -> None:
        hooks = get_hooks(Path("/unused"), include_ground_truth="false")
        assert hooks[0]._include_ground_truth is False

    def test_include_ground_truth_default_true(self) -> None:
        hooks = get_hooks(Path("/unused"))
        assert hooks[0]._include_ground_truth is True

    def test_force_download_true(self) -> None:
        hooks = get_hooks(Path("/unused"), force_download="true")
        assert hooks[0]._force_download is True

    def test_force_download_default_false(self) -> None:
        hooks = get_hooks(Path("/unused"))
        assert hooks[0]._force_download is False

    def test_unknown_kwargs_rejected(self) -> None:
        """get_hooks uses named params; unknown kwargs are rejected."""
        with pytest.raises(TypeError):
            get_hooks(
                Path("/unused"), task_filter="incident_*", agent="default"  # type: ignore[call-arg]
            )

    def test_no_kwargs_uses_defaults(self) -> None:
        hooks = get_hooks(Path("/unused"))
        assert hooks[0]._datasets is None
        assert hooks[0]._include_ground_truth is True
        assert hooks[0]._force_download is False


def _make_benchmark_dirs(benchmarks: Path, names: list[str]) -> None:
    """Create minimal benchmark subdirectories with a marker tarball."""
    for name in names:
        d = benchmarks / name
        d.mkdir(parents=True, exist_ok=True)
        # _is_benchmark_dir requires benchmark.tar.gz or .aixcc/ to exist
        if not name.startswith("."):
            (d / "benchmark.tar.gz").touch()


class TestExpandGroup:
    """Tests for _expand_group() named dataset group expansion."""

    def test_all_returns_none(self, tmp_path: Path) -> None:
        _make_benchmark_dirs(tmp_path, ["afc-curl-delta-01", "sanity-mock-c-delta-01"])
        assert _expand_group("all", tmp_path) is None

    def test_competition_excludes_sanity(self, tmp_path: Path) -> None:
        _make_benchmark_dirs(tmp_path, [
            "afc-curl-delta-01",
            "atlanta-batik-delta-01",
            "sanity-mock-c-delta-01",
            "sanity-itoa-delta-01",
        ])
        result = _expand_group("competition", tmp_path)
        assert result == ["afc-curl-delta-01", "atlanta-batik-delta-01"]

    def test_sanity_only_sanity(self, tmp_path: Path) -> None:
        _make_benchmark_dirs(tmp_path, [
            "afc-curl-delta-01",
            "sanity-mock-c-delta-01",
            "sanity-itoa-delta-01",
        ])
        result = _expand_group("sanity", tmp_path)
        assert result == ["sanity-itoa-delta-01", "sanity-mock-c-delta-01"]

    def test_skips_dot_dirs(self, tmp_path: Path) -> None:
        _make_benchmark_dirs(tmp_path, [".cache", "afc-curl-delta-01"])
        result = _expand_group("competition", tmp_path)
        assert result == ["afc-curl-delta-01"]

    def test_skips_non_benchmark_dirs(self, tmp_path: Path) -> None:
        """Directories without tarballs or .aixcc/ (like index/) are excluded."""
        _make_benchmark_dirs(tmp_path, ["afc-curl-delta-01"])
        # Create a non-benchmark directory (no tarball, no .aixcc)
        (tmp_path / "index").mkdir()
        (tmp_path / "index" / "benchmarks.jsonl").write_text("{}")
        result = _expand_group("competition", tmp_path)
        assert result == ["afc-curl-delta-01"]


class TestResolveDatasets:
    """Tests for DownloadBenchmarkData._resolve_datasets()."""

    def test_none_returns_none(self, tmp_path: Path) -> None:
        hook = DownloadBenchmarkData()
        assert hook._resolve_datasets(tmp_path) is None

    def test_explicit_names_unchanged(self, tmp_path: Path) -> None:
        hook = DownloadBenchmarkData(datasets=["afc-curl-delta-01"])
        assert hook._resolve_datasets(tmp_path) == ["afc-curl-delta-01"]

    def test_competition_group_expands(self, tmp_path: Path) -> None:
        _make_benchmark_dirs(tmp_path, [
            "afc-curl-delta-01",
            "sanity-mock-c-delta-01",
        ])
        hook = DownloadBenchmarkData(datasets=["competition"])
        result = hook._resolve_datasets(tmp_path)
        assert result == ["afc-curl-delta-01"]

    def test_multi_item_list_not_treated_as_group(self, tmp_path: Path) -> None:
        """A list with >1 item is never treated as a group name."""
        hook = DownloadBenchmarkData(datasets=["competition", "other"])
        assert hook._resolve_datasets(tmp_path) == ["competition", "other"]


class TestParseCsv:
    """Tests for the _parse_csv helper."""

    def test_none_returns_none(self) -> None:
        assert _parse_csv(None) is None

    def test_empty_string_returns_empty_list(self) -> None:
        assert _parse_csv("") == []

    def test_single_value(self) -> None:
        assert _parse_csv("abc") == ["abc"]

    def test_comma_separated(self) -> None:
        assert _parse_csv("a,b,c") == ["a", "b", "c"]

    def test_filters_empty_items(self) -> None:
        """Trailing/consecutive commas don't produce empty strings."""
        assert _parse_csv(",") == []
        assert _parse_csv("a,,b") == ["a", "b"]
        assert _parse_csv("a,b,") == ["a", "b"]

    def test_list_passthrough(self) -> None:
        original = ["x", "y"]
        assert _parse_csv(original) is original


class TestCliBool:
    """Tests for the _cli_bool helper."""

    def test_none_returns_default(self) -> None:
        assert _cli_bool(None) is False
        assert _cli_bool(None, default=True) is True

    def test_true_string(self) -> None:
        assert _cli_bool("true") is True

    def test_false_string(self) -> None:
        assert _cli_bool("false") is False

    def test_bool_passthrough(self) -> None:
        assert _cli_bool(True) is True
        assert _cli_bool(False) is False

    def test_one_and_yes(self) -> None:
        assert _cli_bool("1") is True
        assert _cli_bool("yes") is True


class TestSanitizeStagedDir:
    """Tests for _sanitize_staged_dir — removes info-leaking artifacts."""

    def test_removes_git_directory(self, tmp_path: Path) -> None:
        """Removes .git/ directories to prevent git log leakage."""
        git_dir = tmp_path / "project" / ".git"
        git_dir.mkdir(parents=True)
        (git_dir / "HEAD").write_text("ref: refs/heads/main\n")
        (tmp_path / "project" / "source.c").write_text("int main(){}")

        _sanitize_staged_dir(tmp_path)

        assert not git_dir.exists()
        assert (tmp_path / "project" / "source.c").exists()

    def test_removes_rej_files(self, tmp_path: Path) -> None:
        """Removes .rej files that contain patch fix information."""
        (tmp_path / "mock.c").write_text("source")
        (tmp_path / "mock.c.rej").write_text("--- a/mock.c\n+bounds check")

        _sanitize_staged_dir(tmp_path)

        assert not (tmp_path / "mock.c.rej").exists()
        assert (tmp_path / "mock.c").exists()

    def test_removes_orig_files(self, tmp_path: Path) -> None:
        """Removes .orig backup files from patch commands."""
        (tmp_path / "mock.c").write_text("source")
        (tmp_path / "mock.c.orig").write_text("original source")

        _sanitize_staged_dir(tmp_path)

        assert not (tmp_path / "mock.c.orig").exists()
        assert (tmp_path / "mock.c").exists()

    def test_removes_bak_files(self, tmp_path: Path) -> None:
        """Removes .bak backup files from diff commands."""
        (tmp_path / "mock.c").write_text("source")
        (tmp_path / "mock.c.bak").write_text("backup source")

        _sanitize_staged_dir(tmp_path)

        assert not (tmp_path / "mock.c.bak").exists()
        assert (tmp_path / "mock.c").exists()

    def test_removes_tilde_backups(self, tmp_path: Path) -> None:
        """Removes editor backup files ending in ~."""
        (tmp_path / "mock.c").write_text("source")
        (tmp_path / "mock.c~").write_text("editor backup")

        _sanitize_staged_dir(tmp_path)

        assert not (tmp_path / "mock.c~").exists()
        assert (tmp_path / "mock.c").exists()

    def test_removes_nested_artifacts(self, tmp_path: Path) -> None:
        """Artifacts in subdirectories are also removed."""
        nested = tmp_path / "subdir" / "deep"
        nested.mkdir(parents=True)
        (nested / "file.c.rej").write_text("reject")
        (nested / "file.c.orig").write_text("original")
        (nested / "file.c").write_text("source")

        git_dir = nested / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text("[core]")

        _sanitize_staged_dir(tmp_path)

        assert not (nested / "file.c.rej").exists()
        assert not (nested / "file.c.orig").exists()
        assert not git_dir.exists()
        assert (nested / "file.c").exists()

    def test_noop_on_clean_directory(self, tmp_path: Path) -> None:
        """No errors raised on a directory with no artifacts."""
        (tmp_path / "source.c").write_text("int main(){}")
        (tmp_path / "Makefile").write_text("all:")

        _sanitize_staged_dir(tmp_path)

        assert (tmp_path / "source.c").exists()
        assert (tmp_path / "Makefile").exists()

    def test_removes_all_artifact_types_at_once(self, tmp_path: Path) -> None:
        """Multiple artifact types in the same directory are all removed."""
        (tmp_path / "mock.c").write_text("source")
        (tmp_path / "mock.c.rej").write_text("reject")
        (tmp_path / "mock.c.orig").write_text("original")
        (tmp_path / "mock.c.bak").write_text("backup")
        (tmp_path / "mock.c~").write_text("editor backup")
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "HEAD").write_text("ref: refs/heads/main\n")

        _sanitize_staged_dir(tmp_path)

        assert (tmp_path / "mock.c").exists()
        assert not (tmp_path / "mock.c.rej").exists()
        assert not (tmp_path / "mock.c.orig").exists()
        assert not (tmp_path / "mock.c.bak").exists()
        assert not (tmp_path / "mock.c~").exists()
        assert not git_dir.exists()


def _create_tarball(tar_path: Path, files: dict[str, str]) -> None:
    """Helper: create a .tar.gz with the given filename->content mapping."""
    import io
    import tarfile

    with tarfile.open(tar_path, "w:gz") as tf:
        for name, content in files.items():
            data = content.encode()
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))


class TestExtractBenchmarkTarballs:
    """Tests for extract_benchmark_tarballs."""

    def test_extracts_benchmark_tarball(self, tmp_path: Path) -> None:
        """benchmark.tar.gz contents are extracted into benchmark_dir."""
        bm = tmp_path / "bench-01"
        bm.mkdir()
        _create_tarball(bm / "benchmark.tar.gz", {
            "project.yaml": "name: bench",
            "build.sh": "#!/bin/bash\nexit 0",
        })
        _create_tarball(bm / "ground-truth.tar.gz", {
            ".aixcc/meta.yaml": "id: bench-01",
        })

        extract_benchmark_tarballs(bm)

        assert (bm / "project.yaml").exists()
        assert (bm / "build.sh").read_text() == "#!/bin/bash\nexit 0"
        assert (bm / ".aixcc" / "meta.yaml").read_text() == "id: bench-01"

    def test_idempotent_skips_if_already_extracted(self, tmp_path: Path) -> None:
        """Skips extraction when .aixcc/meta.yaml already exists."""
        bm = tmp_path / "bench-01"
        bm.mkdir()
        (bm / ".aixcc").mkdir()
        (bm / ".aixcc" / "meta.yaml").write_text("already here")

        # Even with tarballs present, extraction is skipped
        _create_tarball(bm / "benchmark.tar.gz", {"project.yaml": "new"})
        _create_tarball(bm / "ground-truth.tar.gz", {
            ".aixcc/meta.yaml": "overwrite attempt",
        })

        extract_benchmark_tarballs(bm)

        # Original content preserved — extraction was skipped
        assert (bm / ".aixcc" / "meta.yaml").read_text() == "already here"
        assert not (bm / "project.yaml").exists()

    def test_missing_tarballs_no_error(self, tmp_path: Path) -> None:
        """Missing tarballs are logged as warnings, not errors."""
        bm = tmp_path / "bench-empty"
        bm.mkdir()

        # Should not raise
        extract_benchmark_tarballs(bm)

    def test_missing_one_tarball(self, tmp_path: Path) -> None:
        """Only benchmark.tar.gz present — extracts it, warns about missing ground-truth."""
        bm = tmp_path / "bench-partial"
        bm.mkdir()
        _create_tarball(bm / "benchmark.tar.gz", {
            "project.yaml": "name: partial",
        })

        extract_benchmark_tarballs(bm)

        assert (bm / "project.yaml").exists()
        assert not (bm / ".aixcc").exists()

    def test_extracts_nested_paths(self, tmp_path: Path) -> None:
        """Tarball entries with nested paths create subdirectories."""
        bm = tmp_path / "bench-nested"
        bm.mkdir()
        _create_tarball(bm / "benchmark.tar.gz", {
            "pkgs/lib.tar.gz": "fake-nested-tarball",
            "fuzz/harness.c": "int main(){}",
        })
        _create_tarball(bm / "ground-truth.tar.gz", {
            ".aixcc/meta.yaml": "id: nested",
            ".aixcc/ref.diff": "--- a/x\n+++ b/x",
        })

        extract_benchmark_tarballs(bm)

        assert (bm / "pkgs" / "lib.tar.gz").exists()
        assert (bm / "fuzz" / "harness.c").read_text() == "int main(){}"
        assert (bm / ".aixcc" / "ref.diff").exists()


class TestExtractAllTarballs:
    """Tests for extract_all_tarballs."""

    def test_processes_all_subdirectories(self, tmp_path: Path) -> None:
        """Iterates subdirectories and extracts tarballs in each."""
        for name in ("bench-a", "bench-b"):
            d = tmp_path / name
            d.mkdir()
            _create_tarball(d / "benchmark.tar.gz", {
                "project.yaml": f"name: {name}",
            })
            _create_tarball(d / "ground-truth.tar.gz", {
                ".aixcc/meta.yaml": f"id: {name}",
            })

        extract_all_tarballs(tmp_path)

        for name in ("bench-a", "bench-b"):
            assert (tmp_path / name / "project.yaml").exists()
            assert (tmp_path / name / ".aixcc" / "meta.yaml").exists()

    def test_skips_non_directories(self, tmp_path: Path) -> None:
        """Files at the top level are silently skipped."""
        (tmp_path / "README.md").write_text("info")
        bm = tmp_path / "bench-only"
        bm.mkdir()
        _create_tarball(bm / "benchmark.tar.gz", {"project.yaml": "ok"})
        _create_tarball(bm / "ground-truth.tar.gz", {
            ".aixcc/meta.yaml": "id: only",
        })

        extract_all_tarballs(tmp_path)

        assert (bm / "project.yaml").exists()

    def test_empty_dir_no_error(self, tmp_path: Path) -> None:
        """Empty benchmarks directory doesn't cause errors."""
        extract_all_tarballs(tmp_path)


class TestDownloadBenchmarkDataShouldRunWithDatasets:
    """Tests for should_run() with specific datasets requested."""

    def test_should_run_false_when_all_datasets_staged(
        self, tmp_path: Path
    ) -> None:
        """Returns False when all requested datasets have meta.yaml, staged content, and tasks."""
        benchmarks = tmp_path / "data" / "benchmarks"
        for name in ("ds-a", "ds-b"):
            d = benchmarks / name
            (d / ".aixcc").mkdir(parents=True)
            (d / ".aixcc" / "meta.yaml").write_text("id: " + name)
            staged = d / "staged"
            staged.mkdir()
            (staged / "main.c").write_text("int main(){}")
        # Task YAMLs must also exist (with benchmark_image)
        tasks = tmp_path / "tasks"
        tasks.mkdir()
        (tasks / "ds-a__bugfix.yaml").write_text(
            "tasks:\n- initial_context:\n    benchmark_image: saber/crsbench/benchmark:ds-a\n"
        )

        hook = DownloadBenchmarkData(datasets=["ds-a", "ds-b"])
        assert hook.should_run(tmp_path) is False

    def test_should_run_true_when_some_datasets_missing_staging(
        self, tmp_path: Path
    ) -> None:
        """Returns True when any requested dataset lacks staged content."""
        benchmarks = tmp_path / "data" / "benchmarks"
        # ds-a is fully staged
        d = benchmarks / "ds-a"
        (d / ".aixcc").mkdir(parents=True)
        (d / ".aixcc" / "meta.yaml").write_text("id: ds-a")
        staged = d / "staged"
        staged.mkdir()
        (staged / "main.c").write_text("int main(){}")
        # ds-b has no staged directory
        d2 = benchmarks / "ds-b"
        (d2 / ".aixcc").mkdir(parents=True)
        (d2 / ".aixcc" / "meta.yaml").write_text("id: ds-b")

        hook = DownloadBenchmarkData(datasets=["ds-a", "ds-b"])
        assert hook.should_run(tmp_path) is True

    def test_should_run_true_when_dataset_missing_meta(
        self, tmp_path: Path
    ) -> None:
        """Returns True when any requested dataset lacks meta.yaml."""
        benchmarks = tmp_path / "data" / "benchmarks"
        benchmarks.mkdir(parents=True)
        # ds-a directory exists but no .aixcc/meta.yaml
        (benchmarks / "ds-a").mkdir()

        hook = DownloadBenchmarkData(datasets=["ds-a"])
        assert hook.should_run(tmp_path) is True

    def test_should_run_true_when_staged_dir_empty(
        self, tmp_path: Path
    ) -> None:
        """Returns True when staged dir exists but is empty."""
        benchmarks = tmp_path / "data" / "benchmarks"
        d = benchmarks / "ds-a"
        (d / ".aixcc").mkdir(parents=True)
        (d / ".aixcc" / "meta.yaml").write_text("id: ds-a")
        (d / "staged").mkdir()  # empty staged dir

        hook = DownloadBenchmarkData(datasets=["ds-a"])
        assert hook.should_run(tmp_path) is True


class TestCleanTaskDirs:
    """Tests for the clean_task_dirs helper."""

    def test_removes_subdirectories(self, tmp_path: Path) -> None:
        """Removes generated task subdirectories."""
        (tmp_path / "sanity_mock_c").mkdir()
        (tmp_path / "afc_curl").mkdir()
        (tmp_path / "global.yaml").write_text("global: true")
        (tmp_path / ".gitignore").write_text("*.pyc")

        removed = clean_task_dirs(tmp_path)

        assert removed == 2
        assert not (tmp_path / "sanity_mock_c").exists()
        assert not (tmp_path / "afc_curl").exists()

    def test_preserves_global_yaml_and_gitignore(self, tmp_path: Path) -> None:
        """global.yaml and .gitignore are not removed."""
        (tmp_path / "global.yaml").write_text("global: true")
        (tmp_path / ".gitignore").write_text("*.pyc")
        (tmp_path / "some_dir").mkdir()

        clean_task_dirs(tmp_path)

        assert (tmp_path / "global.yaml").exists()
        assert (tmp_path / ".gitignore").exists()

    def test_handles_empty_dir(self, tmp_path: Path) -> None:
        """No error on empty directory."""
        removed = clean_task_dirs(tmp_path)
        assert removed == 0

    def test_handles_nonexistent_dir(self, tmp_path: Path) -> None:
        """No error when directory does not exist."""
        removed = clean_task_dirs(tmp_path / "nonexistent")
        assert removed == 0


class TestGetHooksImageBuildKwargs:
    """Tests for get_hooks() with image-build kwargs."""

    def test_force_build_true(self) -> None:
        hooks = get_hooks(Path("/unused"), force_build="true")
        assert hooks[0]._force_build is True

    def test_force_build_default_false(self) -> None:
        hooks = get_hooks(Path("/unused"))
        assert hooks[0]._force_build is False

    def test_rebuild_images_prefix(self) -> None:
        hooks = get_hooks(Path("/unused"), rebuild_images="afc-curl")
        assert hooks[0]._rebuild_images == "afc-curl"

    def test_rebuild_images_default_none(self) -> None:
        hooks = get_hooks(Path("/unused"))
        assert hooks[0]._rebuild_images is None
