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
        hook = DownloadCTIData()

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
