"""Tests for crsbench.setup — domain setup hooks."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from saber.hooks import SetupHook

from crsbench.setup import DownloadBenchmarkData, download_benchmarks


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
        with patch("crsbench.setup.download_benchmarks") as mock_dl:
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
        original_import = builtins.__import__

        def block_hf(name: str, *args: object, **kwargs: object) -> object:
            if name == "huggingface_hub":
                raise ImportError("No module named 'huggingface_hub'")
            return original_import(name, *args, **kwargs)

        import pytest

        with patch.object(builtins, "__import__", side_effect=block_hf):
            with pytest.raises(ImportError, match="oss_saber.*crsbench"):
                download_benchmarks(tmp_path)
