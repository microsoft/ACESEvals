"""Tests for cti_realm.setup — domain setup hooks."""

from __future__ import annotations

import builtins
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from saber.hooks import SetupHook


def _ensure_azure_mocks() -> tuple[MagicMock, MagicMock]:
    """Insert mock ``azure.identity`` and ``azure.storage.blob`` into sys.modules.

    Returns the mock BlobServiceClient class and DefaultAzureCredential class
    so tests can assert on them.
    """
    if "azure.identity" not in sys.modules:
        mod = types.ModuleType("azure.identity")
        mod.DefaultAzureCredential = MagicMock()  # type: ignore[attr-defined]
        sys.modules["azure.identity"] = mod
        sys.modules["azure"] = types.ModuleType("azure")

    if "azure.storage" not in sys.modules:
        sys.modules["azure.storage"] = types.ModuleType("azure.storage")

    if "azure.storage.blob" not in sys.modules:
        mod = types.ModuleType("azure.storage.blob")
        mod.BlobServiceClient = MagicMock()  # type: ignore[attr-defined]
        sys.modules["azure.storage.blob"] = mod

    return (
        sys.modules["azure.storage.blob"].BlobServiceClient,  # type: ignore[union-attr]
        sys.modules["azure.identity"].DefaultAzureCredential,  # type: ignore[union-attr]
    )


_ensure_azure_mocks()

from cti_realm.setup import (  # noqa: E402
    DownloadCTIData,
    _KUSTO_FILES,
    _cli_bool,
    download_cti_data,
    get_hooks,
)


# ---------------------------------------------------------------------------
# Helpers to create fake data for should_run tests
# ---------------------------------------------------------------------------


def _create_kusto_data(domain_root: Path) -> None:
    """Create fake kusto data files."""
    data_dir = domain_root / "docker" / "kusto_init" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "deviceprocessevents.jsonl").write_text("{}")


def _create_cti_reports(domain_root: Path) -> None:
    """Create fake CTI reports file."""
    reports_dir = domain_root / "data" / "cti_reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "reports.jsonl").write_text("{}")


def _create_sigma_rules(domain_root: Path) -> None:
    """Create fake sigma rules file."""
    data_dir = domain_root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "sigma_rules.json").write_text("{}")


# ---------------------------------------------------------------------------
# TestDownloadCTIDataShouldRun
# ---------------------------------------------------------------------------


class TestDownloadCTIDataShouldRun:
    """Tests for DownloadCTIData.should_run() guard logic."""

    def test_satisfies_protocol(self) -> None:
        hook = DownloadCTIData()
        assert isinstance(hook, SetupHook)

    def test_name(self) -> None:
        assert DownloadCTIData().name == "download_cti_data"

    def test_should_run_when_no_data_exists(self, tmp_path: Path) -> None:
        """Empty domain_root → should run."""
        hook = DownloadCTIData()
        assert hook.should_run(tmp_path) is True

    def test_should_run_when_kusto_data_missing(self, tmp_path: Path) -> None:
        """CTI reports + sigma exist but kusto data doesn't → should run."""
        _create_cti_reports(tmp_path)
        _create_sigma_rules(tmp_path)
        hook = DownloadCTIData()
        assert hook.should_run(tmp_path) is True

    def test_should_run_when_cti_reports_missing(self, tmp_path: Path) -> None:
        """Kusto + sigma exist but CTI reports don't → should run."""
        _create_kusto_data(tmp_path)
        _create_sigma_rules(tmp_path)
        hook = DownloadCTIData()
        assert hook.should_run(tmp_path) is True

    def test_should_run_when_sigma_rules_missing(self, tmp_path: Path) -> None:
        """Kusto + CTI reports exist but sigma rules don't → should run."""
        _create_kusto_data(tmp_path)
        _create_cti_reports(tmp_path)
        hook = DownloadCTIData()
        assert hook.should_run(tmp_path) is True

    def test_should_not_run_when_all_data_present(self, tmp_path: Path) -> None:
        """All 3 categories exist → should not run."""
        _create_kusto_data(tmp_path)
        _create_cti_reports(tmp_path)
        _create_sigma_rules(tmp_path)
        hook = DownloadCTIData()
        assert hook.should_run(tmp_path) is False

    def test_force_download_always_runs(self, tmp_path: Path) -> None:
        """force_download=True → should run even with all data present."""
        _create_kusto_data(tmp_path)
        _create_cti_reports(tmp_path)
        _create_sigma_rules(tmp_path)
        hook = DownloadCTIData(force_download=True)
        assert hook.should_run(tmp_path) is True

    def test_should_run_when_kusto_dir_exists_but_empty(self, tmp_path: Path) -> None:
        """Kusto dir exists but has no .jsonl files → should run."""
        kusto_dir = tmp_path / "docker" / "kusto_init" / "data"
        kusto_dir.mkdir(parents=True)
        _create_cti_reports(tmp_path)
        _create_sigma_rules(tmp_path)
        hook = DownloadCTIData()
        assert hook.should_run(tmp_path) is True


# ---------------------------------------------------------------------------
# TestGetHooks
# ---------------------------------------------------------------------------


class TestGetHooks:
    """Tests for the get_hooks() auto-discovery entry point."""

    def test_returns_single_hook(self) -> None:
        """get_hooks() returns a list with one SetupHook."""
        hooks = get_hooks(Path("/unused"))
        assert len(hooks) == 1
        assert all(isinstance(h, SetupHook) for h in hooks)

    def test_first_hook_is_download_cti_data(self) -> None:
        """First hook is a DownloadCTIData instance with expected name."""
        hooks = get_hooks(Path("/unused"))
        assert isinstance(hooks[0], DownloadCTIData)
        assert hooks[0].name == "download_cti_data"

    def test_forwards_anonymized_flag(self) -> None:
        """anonymized kwarg is forwarded to the hook."""
        hooks = get_hooks(Path("/unused"), anonymized="true")
        assert hooks[0]._anonymized is True

    def test_forwards_force_download_flag(self) -> None:
        """force_download kwarg is forwarded to the hook."""
        hooks = get_hooks(Path("/unused"), force_download="true")
        assert hooks[0]._force_download is True

    def test_defaults(self) -> None:
        """Default kwargs produce False for both flags."""
        hooks = get_hooks(Path("/unused"))
        assert hooks[0]._anonymized is False
        assert hooks[0]._force_download is False

    def test_unknown_kwargs_ignored(self) -> None:
        """Extra kwargs like task_filter, agent don't cause errors."""
        hooks = get_hooks(
            Path("/unused"), task_filter="incident_*", agent="default"
        )
        assert len(hooks) == 1


# ---------------------------------------------------------------------------
# TestDownloadCTIDataRun
# ---------------------------------------------------------------------------


class TestDownloadCTIDataRun:
    """Tests for DownloadCTIData.run()."""

    def test_run_calls_download_function(self, tmp_path: Path) -> None:
        """run() delegates to download_cti_data() with correct args."""
        hook = DownloadCTIData(anonymized=True)
        with patch("cti_realm.setup.download_cti_data") as mock_dl:
            hook.run(tmp_path)
            mock_dl.assert_called_once_with(
                tmp_path,
                anonymized=True,
                force_download=False,
            )

    def test_run_forwards_force_download(self, tmp_path: Path) -> None:
        """run() forwards force_download to download_cti_data()."""
        hook = DownloadCTIData(force_download=True)
        with patch("cti_realm.setup.download_cti_data") as mock_dl:
            hook.run(tmp_path)
            mock_dl.assert_called_once_with(
                tmp_path,
                anonymized=False,
                force_download=True,
            )

    def test_run_raises_on_missing_azure_sdk(self, tmp_path: Path) -> None:
        """ImportError with helpful message when Azure SDK is missing."""
        saved_identity = sys.modules.pop("azure.identity", None)
        saved_blob = sys.modules.pop("azure.storage.blob", None)
        original_import = builtins.__import__

        def block_azure(name: str, *args: object, **kwargs: object) -> object:
            if name in ("azure.identity", "azure.storage.blob"):
                raise ImportError(f"No module named '{name}'")
            return original_import(name, *args, **kwargs)

        try:
            with patch.object(builtins, "__import__", side_effect=block_azure):
                with pytest.raises(ImportError, match="azure-identity|azure-storage-blob"):
                    download_cti_data(tmp_path)
        finally:
            if saved_identity is not None:
                sys.modules["azure.identity"] = saved_identity
            if saved_blob is not None:
                sys.modules["azure.storage.blob"] = saved_blob


# ---------------------------------------------------------------------------
# TestCliBool
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Helpers for download_cti_data internals
# ---------------------------------------------------------------------------


def _build_mock_container(
    data: bytes = b"mock-blob-content",
) -> tuple[MagicMock, MagicMock]:
    """Build a mock container_client with proper blob download chain.

    Returns the (mock_BlobServiceClient_class, mock_container_client) so
    tests can inspect calls on the container.
    """
    mock_blob_client = MagicMock()
    mock_blob_client.download_blob.return_value.readall.return_value = data

    mock_container = MagicMock()
    mock_container.get_blob_client.return_value = mock_blob_client

    MockBlobServiceClient, _ = _ensure_azure_mocks()
    MockBlobServiceClient.reset_mock()
    instance = MockBlobServiceClient.return_value
    instance.get_container_client.return_value = mock_container

    return MockBlobServiceClient, mock_container


# ---------------------------------------------------------------------------
# TestDownloadCTIDataDetails
# ---------------------------------------------------------------------------


class TestDownloadCTIDataDetails:
    """Tests for download_cti_data() internals — blob requests, paths, skips."""

    def test_kusto_blob_names_default_prefix(self, tmp_path: Path) -> None:
        """Default (non-anonymized) download requests ground_truth_telemetry_data/."""
        _, container = _build_mock_container()
        download_cti_data(tmp_path)

        blob_names: list[str] = [
            c.args[0] for c in container.get_blob_client.call_args_list
        ]
        for filename in _KUSTO_FILES:
            expected = f"ground_truth_telemetry_data/{filename}"
            assert expected in blob_names, f"Missing blob request: {expected}"

    def test_kusto_blob_names_anonymized_prefix(self, tmp_path: Path) -> None:
        """anonymized=True requests blobs from anonymized/ prefix."""
        _, container = _build_mock_container()
        download_cti_data(tmp_path, anonymized=True)

        blob_names: list[str] = [
            c.args[0] for c in container.get_blob_client.call_args_list
        ]
        for filename in _KUSTO_FILES:
            expected = f"anonymized/{filename}"
            assert expected in blob_names, f"Missing blob request: {expected}"
        # Ensure the default prefix was NOT used
        for filename in _KUSTO_FILES:
            wrong = f"ground_truth_telemetry_data/{filename}"
            assert wrong not in blob_names, f"Unexpected default-prefix blob: {wrong}"

    def test_existing_files_skipped_when_no_force(self, tmp_path: Path) -> None:
        """Files that already exist are skipped when force_download=False."""
        _, container = _build_mock_container()

        # Pre-create one kusto file and the reports file
        kusto_dir = tmp_path / "docker" / "kusto_init" / "data"
        kusto_dir.mkdir(parents=True)
        (kusto_dir / "signinlogs.jsonl").write_bytes(b"old")

        reports_dir = tmp_path / "data" / "cti_reports"
        reports_dir.mkdir(parents=True)
        (reports_dir / "reports.jsonl").write_bytes(b"old")

        download_cti_data(tmp_path, force_download=False)

        requested: list[str] = [
            c.args[0] for c in container.get_blob_client.call_args_list
        ]
        assert "ground_truth_telemetry_data/signinlogs.jsonl" not in requested
        assert "reports/reports.jsonl" not in requested
        # Other kusto files should still be downloaded
        assert "ground_truth_telemetry_data/aksaudit.jsonl" in requested

    def test_force_download_redownloads_existing(self, tmp_path: Path) -> None:
        """force_download=True re-downloads even when files exist."""
        _, container = _build_mock_container()

        # Pre-create all files
        _create_kusto_data(tmp_path)
        _create_cti_reports(tmp_path)
        _create_sigma_rules(tmp_path)

        download_cti_data(tmp_path, force_download=True)

        requested: list[str] = [
            c.args[0] for c in container.get_blob_client.call_args_list
        ]
        # All kusto + reports + sigma = len(_KUSTO_FILES) + 2
        assert len(requested) == len(_KUSTO_FILES) + 2

    def test_all_categories_create_directories(self, tmp_path: Path) -> None:
        """Directories for kusto, reports, and sigma are created."""
        _build_mock_container()
        download_cti_data(tmp_path)

        assert (tmp_path / "docker" / "kusto_init" / "data").is_dir()
        assert (tmp_path / "data" / "cti_reports").is_dir()
        assert (tmp_path / "data").is_dir()

    def test_files_written_to_expected_paths(self, tmp_path: Path) -> None:
        """Downloaded blob data is written to the correct local paths."""
        blob_content = b"test-blob-data-12345"
        _build_mock_container(data=blob_content)
        download_cti_data(tmp_path)

        # Check all kusto files
        kusto_dir = tmp_path / "docker" / "kusto_init" / "data"
        for filename in _KUSTO_FILES:
            path = kusto_dir / filename
            assert path.exists(), f"Missing kusto file: {filename}"
            assert path.read_bytes() == blob_content

        # Check reports
        reports_file = tmp_path / "data" / "cti_reports" / "reports.jsonl"
        assert reports_file.exists()
        assert reports_file.read_bytes() == blob_content

        # Check sigma rules
        sigma_file = tmp_path / "data" / "sigma_rules.json"
        assert sigma_file.exists()
        assert sigma_file.read_bytes() == blob_content

    def test_reports_blob_name(self, tmp_path: Path) -> None:
        """CTI reports requests the correct blob name."""
        _, container = _build_mock_container()
        download_cti_data(tmp_path)

        requested: list[str] = [
            c.args[0] for c in container.get_blob_client.call_args_list
        ]
        assert "reports/reports.jsonl" in requested

    def test_sigma_blob_name(self, tmp_path: Path) -> None:
        """Sigma rules requests the correct blob name."""
        _, container = _build_mock_container()
        download_cti_data(tmp_path)

        requested: list[str] = [
            c.args[0] for c in container.get_blob_client.call_args_list
        ]
        assert "ground_truth_detection_specific/sigma_rules.json" in requested


# ---------------------------------------------------------------------------
# TestDownloadCTIDataErrorHandling
# ---------------------------------------------------------------------------


class TestDownloadCTIDataErrorHandling:
    """Tests for per-blob and per-category error handling."""

    def test_single_blob_failure_continues_downloads(
        self, tmp_path: Path
    ) -> None:
        """A single blob failure doesn't prevent remaining downloads."""
        _, container = _build_mock_container()

        # Make aksaudit.jsonl fail, others succeed
        def _get_blob_client_side_effect(blob_name: str) -> MagicMock:
            client = MagicMock()
            if blob_name == "ground_truth_telemetry_data/aksaudit.jsonl":
                client.download_blob.side_effect = RuntimeError("network error")
            else:
                client.download_blob.return_value.readall.return_value = b"ok"
            return client

        container.get_blob_client.side_effect = _get_blob_client_side_effect

        with pytest.raises(RuntimeError, match="1 error"):
            download_cti_data(tmp_path)

        # Other kusto files should still have been downloaded
        kusto_dir = tmp_path / "docker" / "kusto_init" / "data"
        assert (kusto_dir / "signinlogs.jsonl").exists()
        assert not (kusto_dir / "aksaudit.jsonl").exists()

        # Reports and sigma should still have been downloaded
        assert (tmp_path / "data" / "cti_reports" / "reports.jsonl").exists()
        assert (tmp_path / "data" / "sigma_rules.json").exists()

    def test_category_failure_continues_other_categories(
        self, tmp_path: Path
    ) -> None:
        """A category-level failure doesn't prevent other categories."""
        _, container = _build_mock_container()

        # Make all kusto downloads fail with an error on get_blob_client
        def _get_blob_side_effect(blob_name: str) -> MagicMock:
            if blob_name.startswith("ground_truth_telemetry_data/"):
                raise RuntimeError("storage unavailable")
            client = MagicMock()
            client.download_blob.return_value.readall.return_value = b"ok"
            return client

        container.get_blob_client.side_effect = _get_blob_side_effect

        with pytest.raises(RuntimeError, match="error"):
            download_cti_data(tmp_path)

        # Reports and sigma should still succeed
        assert (tmp_path / "data" / "cti_reports" / "reports.jsonl").exists()
        assert (tmp_path / "data" / "sigma_rules.json").exists()

    def test_no_errors_no_exception(self, tmp_path: Path) -> None:
        """Successful download raises no exception."""
        _build_mock_container()
        # Should not raise
        download_cti_data(tmp_path)
