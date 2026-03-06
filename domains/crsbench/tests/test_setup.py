"""Tests for crsbench.setup — domain setup hooks."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

from saber.hooks import SetupHook

from crsbench.setup import DownloadBenchmarkData, download_benchmarks, get_hooks, _parse_csv, _cli_bool, _sanitize_staged_dir


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

    def test_should_not_run_when_data_present(self, tmp_path: Path) -> None:
        benchmarks = tmp_path / "data" / "benchmarks"
        benchmarks.mkdir(parents=True)
        (benchmarks / "benchmark_001").mkdir()
        hook = DownloadBenchmarkData()
        assert hook.should_run(tmp_path) is False

    def test_should_not_run_when_file_present(self, tmp_path: Path) -> None:
        """Even a file (not dir) makes the directory non-empty."""
        benchmarks = tmp_path / "data" / "benchmarks"
        benchmarks.mkdir(parents=True)
        (benchmarks / "some_file.txt").write_text("data")
        hook = DownloadBenchmarkData()
        assert hook.should_run(tmp_path) is False

    def test_run_calls_download_default(self, tmp_path: Path) -> None:
        """run() delegates to download_benchmarks() with defaults."""
        hook = DownloadBenchmarkData()
        with (
            patch("crsbench.setup.download_benchmarks") as mock_dl,
            patch("crsbench.setup.stage_all_benchmarks"),
        ):
            hook.run(tmp_path)
            mock_dl.assert_called_once_with(
                tmp_path / "data" / "benchmarks",
                include_ground_truth=True,
                benchmarks=None,
            )

    def test_run_passes_config(self, tmp_path: Path) -> None:
        """run() forwards include_ground_truth and benchmarks."""
        hook = DownloadBenchmarkData(
            include_ground_truth=False,
            benchmarks=["afc-curl-delta-01"],
        )
        with (
            patch("crsbench.setup.download_benchmarks") as mock_dl,
            patch("crsbench.setup.stage_all_benchmarks"),
        ):
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


class TestGetHooks:
    """Tests for the get_hooks() auto-discovery entry point."""

    def test_returns_list_of_setup_hooks(self) -> None:
        """get_hooks() returns a non-empty list of SetupHook instances."""
        hooks = get_hooks(Path("/unused"))
        assert len(hooks) == 1
        assert all(isinstance(h, SetupHook) for h in hooks)

    def test_first_hook_is_download_benchmark_data(self) -> None:
        """First hook is a DownloadBenchmarkData instance with expected name."""
        hooks = get_hooks(Path("/unused"))
        assert isinstance(hooks[0], DownloadBenchmarkData)
        assert hooks[0].name == "download_benchmark_data"


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
        """force_download=False (default) still checks data dir."""
        benchmarks = tmp_path / "data" / "benchmarks"
        benchmarks.mkdir(parents=True)
        (benchmarks / "some_benchmark").mkdir()

        hook = DownloadBenchmarkData(force_download=False)
        assert hook.should_run(tmp_path) is False


class TestGetHooksKwargs:
    """Tests for get_hooks() with CLI -T kwargs."""

    def test_benchmarks_csv_parsed(self) -> None:
        hooks = get_hooks(Path("/unused"), benchmarks="a,b")
        assert hooks[0]._benchmarks == ["a", "b"]

    def test_benchmarks_single_value(self) -> None:
        hooks = get_hooks(Path("/unused"), benchmarks="sanity-mock-c-delta-01")
        assert hooks[0]._benchmarks == ["sanity-mock-c-delta-01"]

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

    def test_unknown_kwargs_ignored(self) -> None:
        """Extra kwargs like task_filter, agent don't cause errors."""
        hooks = get_hooks(
            Path("/unused"), task_filter="incident_*", agent="default"
        )
        assert len(hooks) == 1

    def test_no_kwargs_uses_defaults(self) -> None:
        hooks = get_hooks(Path("/unused"))
        assert hooks[0]._benchmarks is None
        assert hooks[0]._include_ground_truth is True
        assert hooks[0]._force_download is False


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
