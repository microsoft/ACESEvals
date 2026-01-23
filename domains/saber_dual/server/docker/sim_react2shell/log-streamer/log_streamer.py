"""
LogStreamer - Real-time log streaming during attack simulation.

Polls the Azure Sentinel service and streams logs to separate files
based on source service and log schema.

This module can run as:
1. A background subprocess (started by --start, stopped by --stop)
2. Standalone via: python -m src.log_streamer <output_dir>
"""

import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

# Map services to their log schemas/categories
LOG_SCHEMAS = {
    "keyvault": "AzureKeyVaultAuditLogs",
    "azure_ad": "AADSignInLogs",
    "imds": "AzureIMDSAccessLogs",
    "arm": "AzureActivityLogs",
    "functions": "AzureFunctionLogs",
    "eventgrid": "AzureEventGridLogs",
    "app_service": "AppServiceHTTPLogs",
    "gateway": "AzureNetworkSecurityGroupLogs",
    "sql_wrapper": "SQLSecurityAuditEvents",
    "domain_controller": "WindowsSecurityEvents",
    "sysmon": "SysmonEvents",
    "sql": "SQLSecurityAuditEvents",
    "windows": "WindowsSecurityEvents",
    "blob_storage": "StorageBlobLogs",
}

# PID file location
PID_FILE = Path("/tmp/saber-sim-log-streamer.pid")


class LogStreamer:
    """Streams logs from Azure Sentinel to files organized by source."""

    def __init__(
        self,
        output_dir: Path,
        azure_sentinel_url: str = "http://localhost:5000",
        poll_interval: float = 2.0,
    ):
        """
        Initialize the log streamer.

        Args:
            output_dir: Directory to write log files
            azure_sentinel_url: URL of the Azure Sentinel service
            poll_interval: Seconds between polls
        """
        self.output_dir = Path(output_dir)
        self.azure_sentinel_url = azure_sentinel_url
        self.poll_interval = poll_interval

        self._running = False
        self._seen_logs: set[str] = set()
        self._log_counts: dict[str, int] = {}
        self._file_handles: dict[str, Any] = {}

    def _get_log_key(self, log: dict) -> str:
        """Generate a unique key for deduplication."""
        timestamp = log.get("time") or log.get("timestamp") or ""
        operation = log.get("operationName") or ""
        caller = log.get("callerIpAddress") or ""
        resource = log.get("resourceId") or ""
        # Include source for uniqueness
        source = log.get("_source") or ""
        return f"{source}:{timestamp}:{operation}:{caller}:{resource}"

    def _get_file_handle(self, source: str):
        """Get or create file handle for a source."""
        if source not in self._file_handles:
            schema = LOG_SCHEMAS.get(source, "UnknownLogs")
            file_path = self.output_dir / f"{schema}.jsonl"
            self._file_handles[source] = open(file_path, "a")
            self._log_counts[source] = 0
        return self._file_handles[source]

    def _cleanup(self):
        """Close all file handles and update metadata."""
        # Close all file handles
        for source, fh in self._file_handles.items():
            fh.close()
        self._file_handles.clear()

        # Update metadata with final counts
        meta_path = self.output_dir / "_metadata.json"
        meta_path.write_text(
            json.dumps(
                {
                    "stream_ended": datetime.utcnow().isoformat() + "Z",
                    "schemas": LOG_SCHEMAS,
                    "log_counts": self._log_counts,
                    "total_logs": sum(self._log_counts.values()),
                },
                indent=2,
            )
        )

        print(f"[LogStreamer] Stopped. Total logs: {sum(self._log_counts.values())}")
        for source, count in sorted(self._log_counts.items()):
            schema = LOG_SCHEMAS.get(source, source)
            print(f"   {schema}: {count}")

    def run(self):
        """Run the log streamer (blocking). Use for subprocess mode."""
        self._running = True
        print(f"[LogStreamer] Starting log stream to {self.output_dir}")

        # Create output directory
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Write metadata file
        meta_path = self.output_dir / "_metadata.json"
        meta_path.write_text(
            json.dumps(
                {
                    "stream_started": datetime.utcnow().isoformat() + "Z",
                    "schemas": LOG_SCHEMAS,
                    "pid": os.getpid(),
                },
                indent=2,
            )
        )

        # Handle shutdown signals
        def handle_signal(signum, frame):
            print(f"\n[LogStreamer] Received signal {signum}, stopping...")
            self._running = False

        signal.signal(signal.SIGTERM, handle_signal)
        signal.signal(signal.SIGINT, handle_signal)

        while self._running:
            try:
                response = httpx.get(
                    f"{self.azure_sentinel_url}/logs",
                    params={"limit": 1000},
                    timeout=5.0,
                )

                if response.status_code == 200:
                    data = response.json()
                    logs = data.get("value", [])

                    new_by_source: dict[str, int] = {}

                    for log in logs:
                        log_key = self._get_log_key(log)

                        if log_key not in self._seen_logs:
                            self._seen_logs.add(log_key)

                            # Determine source
                            source = log.get("_source", "unknown")

                            # Get file handle and write
                            fh = self._get_file_handle(source)
                            fh.write(json.dumps(log) + "\n")

                            self._log_counts[source] = self._log_counts.get(source, 0) + 1
                            new_by_source[source] = new_by_source.get(source, 0) + 1

                    # Flush all files if we wrote anything
                    if new_by_source:
                        for fh in self._file_handles.values():
                            fh.flush()

            except httpx.RequestError:
                # Log collector might not be up yet
                pass
            except Exception as e:
                print(f"[LogStreamer] Error: {e}")

            time.sleep(self.poll_interval)

        self._cleanup()
        return {
            "log_counts": self._log_counts.copy(),
            "total_logs": sum(self._log_counts.values()),
        }

    def stop(self):
        """Signal the streamer to stop."""
        self._running = False


def start_log_streaming(output_dir: Path) -> bool:
    """
    Start log streaming as a background subprocess.

    Args:
        output_dir: Directory to write log files

    Returns:
        True if started successfully
    """
    # Check if already running
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            # Check if process is still running
            os.kill(pid, 0)
            print(f"[LogStreamer] Already running (PID {pid})")
            return True
        except (ProcessLookupError, ValueError):
            # Process not running, clean up stale PID file
            PID_FILE.unlink()

    # Start subprocess
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Use current Python interpreter
    python = sys.executable

    # Start the streamer as a detached subprocess
    log_file = output_dir / "_streamer.log"
    with open(log_file, "w") as log_fh:
        proc = subprocess.Popen(
            [python, "-m", "src.log_streamer", str(output_dir)],
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            cwd=Path(__file__).parent.parent,  # saber-sim directory
            start_new_session=True,  # Detach from parent
        )

    # Write PID file
    PID_FILE.write_text(str(proc.pid))

    print(f"[LogStreamer] Started (PID {proc.pid})")
    print(f"   Output: {output_dir}")
    print(f"   Log: {log_file}")
    return True


def stop_log_streaming() -> dict[str, Any]:
    """
    Stop the log streaming subprocess.

    Returns:
        dict with status and any available stats
    """
    if not PID_FILE.exists():
        return {"status": "not_running"}

    try:
        pid = int(PID_FILE.read_text().strip())

        # Send SIGTERM
        os.kill(pid, signal.SIGTERM)

        # Wait a moment for cleanup
        time.sleep(1)

        # Check if still running
        try:
            os.kill(pid, 0)
            # Still running, try SIGKILL
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass  # Already stopped

        PID_FILE.unlink()

        return {"status": "stopped", "pid": pid}

    except (ProcessLookupError, ValueError) as e:
        # Process already gone
        if PID_FILE.exists():
            PID_FILE.unlink()
        return {"status": "not_running", "error": str(e)}


def is_streaming() -> bool:
    """Check if log streaming is currently running."""
    if not PID_FILE.exists():
        return False
    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, ValueError):
        return False


def get_streaming_stats(output_dir: Path) -> dict[str, Any]:
    """
    Get stats from a log streaming session by reading metadata.

    Args:
        output_dir: The logs output directory

    Returns:
        dict with log counts and stats
    """
    meta_path = Path(output_dir) / "_metadata.json"
    if meta_path.exists():
        return json.loads(meta_path.read_text())
    return {"error": "No metadata found"}


# Main entry point for subprocess/container mode
if __name__ == "__main__":
    # Container mode: read from environment variables
    output_dir = os.getenv("OUTPUT_DIR")
    sentinel_url = os.getenv("AZURE_SENTINEL_URL", "http://azure-sentinel:5000")
    poll_interval = float(os.getenv("POLL_INTERVAL", "5"))

    # CLI mode: read from arguments (fallback)
    if not output_dir and len(sys.argv) >= 2:
        output_dir = sys.argv[1]
        sentinel_url = "http://localhost:5000"

    if not output_dir:
        print("Usage: python -m src.log_streamer <output_dir>")
        print("   Or set OUTPUT_DIR environment variable")
        sys.exit(1)

    streamer = LogStreamer(Path(output_dir), sentinel_url, poll_interval)
    streamer.run()
