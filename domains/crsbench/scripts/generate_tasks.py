"""Generate task YAMLs from CRSBench benchmark metadata.

Reads `.aixcc/meta.yaml` from each benchmark directory and produces
task YAML files following the SABER CRSBench domain schema.

Usage::

    python -m crsbench.scripts.generate_tasks \\
        --benchmarks-dir data/benchmarks \\
        --output-dir tasks/generated
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import yaml

from crsbench.scripts.models import CRSBenchHarness, CRSBenchMeta, CRSBenchVuln
from saber.logging import get_logger

logger = get_logger("domains.crsbench.scripts.generate_tasks")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _derive_project_name(benchmark_id: str) -> str:
    """Derive the project name from a benchmark ID.

    Extracts everything before the last two hyphen-separated segments.
    E.g. ``"sanity-mock-c-delta-01"`` → ``"sanity-mock-c"``.

    Args:
        benchmark_id: The benchmark directory name.

    Returns:
        The derived project name (hyphens preserved).
    """
    parts = benchmark_id.rsplit("-", 2)
    return parts[0] if len(parts) >= 3 else benchmark_id  # noqa: PLR2004


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------


def load_benchmark_meta(benchmark_path: Path) -> CRSBenchMeta:
    """Load and validate a benchmark's .aixcc/meta.yaml.

    Args:
        benchmark_path: Path to the benchmark root directory.

    Returns:
        Parsed CRSBenchMeta model.

    Raises:
        FileNotFoundError: If the benchmark directory or meta.yaml is missing.
        ValueError: If meta.yaml is malformed or fails validation.
    """
    meta_file = benchmark_path / ".aixcc" / "meta.yaml"
    if not meta_file.exists():
        msg = f"meta.yaml not found at {meta_file}"
        raise FileNotFoundError(msg)

    raw = yaml.safe_load(meta_file.read_text())
    if not isinstance(raw, dict):
        msg = f"meta.yaml at {meta_file} is not a valid YAML mapping"
        raise ValueError(msg)

    return CRSBenchMeta(**raw)


def generate_bugfix_task(
    benchmark_path: Path,
    harness: CRSBenchHarness,
    vuln: CRSBenchVuln,
) -> dict[str, object]:
    """Generate a bug-fix task dict from benchmark metadata.

    Args:
        benchmark_path: Path to the benchmark root directory.
        harness: The harness configuration for this task.
        vuln: The specific vulnerability to target.

    Returns:
        A dict representing a single task entry, suitable for YAML serialization.
    """
    benchmark_id = benchmark_path.name
    task_id = f"{benchmark_id}__{harness.name}__{vuln.vuln_keyword}__bugfix".replace("-", "_")

    project = _derive_project_name(benchmark_id)

    # Use the first POV's sanitizer for the description
    sanitizer = vuln.povs[0].sanitizer if vuln.povs else "address"

    data_prefix = f"data/benchmarks/{benchmark_id}"

    return {
        "task_id": task_id,
        "title": f"Fix vulnerability in {harness.name} ({benchmark_id})",
        "description": (
            f"A {sanitizer}-detected vulnerability has been found in "
            f"the {project} project. You are given the crash-triggering POV "
            f"and must write a source-code patch that fixes the vulnerability "
            f"without breaking unit tests."
        ),
        "initial_context": {
            "project": project,
            "harness_name": harness.name,
            "benchmark_id": benchmark_id,
        },
        "initial_files": {
            "/workspace/source": f"{data_prefix}/staged/",
            "/workspace/povs/": (
                f"{data_prefix}/.aixcc/{harness.name}/"
                f"{vuln.vuln_keyword}/blobs/"
            ),
        },
        "scoring": {
            "crsbench_patch_verify": {
                "submission": {
                    "target": "submission",
                    "max_score": 1.0,
                    "source_dir": "/workspace/source",
                    "build_script": "/workspace/source/build.sh",
                    "harness_name": harness.name,
                    "harness_path": f"/workspace/build/{harness.name}",
                    "pov_dir": "/workspace/povs",
                    "test_script": "/workspace/source/test.sh",
                    "patch_dir": "/submit/patches",
                },
            },
            "llm_judge": {
                "model": "openai/azure/gpt-4.1",
                "steps_per_message": 10,
                "crash_analysis": {
                    "target": "trajectory",
                    "judge_system_template": "judge/crash_analysis_system.j2",
                    "judge_user_template": "judge/crash_analysis_user.j2",
                    "max_score": 1.0,
                    "weight": 0.15,
                    "title": "Crash Analysis",
                    "description": (
                        "Agent reproduces the crash and analyzes "
                        "the ASAN output"
                    ),
                    "hints": [
                        "Run the POV against the harness binary",
                        "Read and interpret the AddressSanitizer crash report",
                    ],
                },
                "root_cause": {
                    "target": "trajectory",
                    "judge_system_template": "judge/root_cause_system.j2",
                    "judge_user_template": "judge/root_cause_user.j2",
                    "max_score": 1.0,
                    "weight": 0.20,
                    "title": "Root Cause Analysis",
                    "description": (
                        "Agent traces from crash site to identify "
                        "the vulnerable code"
                    ),
                    "hints": [
                        "Identify the vulnerability type "
                        "(buffer overflow, use-after-free, etc.)",
                        "Locate the specific source code "
                        "that causes the vulnerability",
                    ],
                },
            },
            "tool_call": {
                "patch_created": {
                    "target": "trajectory",
                    "expected_tools": ["bash", "submit_patch"],
                    "max_score": 1.0,
                    "weight": 0.15,
                    "title": "Patch Created",
                    "description": (
                        "Agent produces a unified diff patch file"
                    ),
                },
            },
        },
        "scoring_aggregation": {
            "average": {
                "scores": [
                    "submission",
                    ["crash_analysis", "root_cause", "patch_created"],
                ],
            },
        },
    }


def _derive_group_name(benchmark_id: str) -> str:
    """Derive a group directory name from benchmark ID.

    Groups benchmarks by project name (everything before the variant suffix).
    E.g. "sanity-mock-c-delta-01" -> "sanity_mock_c".

    Args:
        benchmark_id: The benchmark directory name.

    Returns:
        Underscore-separated group name.
    """
    return _derive_project_name(benchmark_id).replace("-", "_")


def _write_shared_yaml(group_dir: Path) -> None:
    """Write a shared.yaml for a task group directory.

    Args:
        group_dir: The group directory to write shared.yaml into.
    """
    shared_path = group_dir / "shared.yaml"
    if shared_path.exists():
        return

    shared_content = {
        "sandbox_environment": "default",
        "initial_context": {
            "sanitizer": "address",
            "mode": "bug_fixing",
        },
    }
    shared_path.write_text(yaml.dump(shared_content, default_flow_style=False))


def generate_all_tasks(
    benchmarks_dir: Path,
    output_dir: Path,
) -> list[Path]:
    """Generate task YAMLs for all benchmarks in a directory.

    Scans for benchmark directories containing `.aixcc/meta.yaml`,
    generates task YAML per harness-vuln pair, and writes them to grouped
    output directories.

    Args:
        benchmarks_dir: Root directory containing benchmark subdirectories.
        output_dir: Target directory for generated task YAMLs.

    Returns:
        List of paths to generated YAML files.
    """
    generated: list[Path] = []

    # Find all benchmark directories with .aixcc/meta.yaml
    benchmark_paths = sorted(
        p.parent.parent
        for p in benchmarks_dir.rglob(".aixcc/meta.yaml")
    )

    if not benchmark_paths:
        logger.warning("No benchmarks found in %s", benchmarks_dir)
        return generated

    for benchmark_path in benchmark_paths:
        meta = load_benchmark_meta(benchmark_path)
        benchmark_id = benchmark_path.name
        group_name = _derive_group_name(benchmark_id)

        group_dir = output_dir / group_name
        group_dir.mkdir(parents=True, exist_ok=True)
        _write_shared_yaml(group_dir)

        for harness in meta.harness_files:
            for vuln in harness.vulns:
                task_dict = generate_bugfix_task(benchmark_path, harness, vuln)
                task_id = task_dict["task_id"]

                task_file = group_dir / f"{task_id}.yaml"
                content = {"tasks": [task_dict]}
                task_file.write_text(
                    yaml.dump(content, default_flow_style=False, sort_keys=False)
                )
                generated.append(task_file)
                logger.info("Generated %s", task_file)

    logger.info(
        "Generated %d task YAML(s) in %s",
        len(generated),
        output_dir,
    )
    return generated


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point for task YAML generation."""
    parser = argparse.ArgumentParser(
        description="Generate CRSBench task YAMLs from benchmark metadata.",
    )
    parser.add_argument(
        "--benchmarks-dir",
        type=Path,
        required=True,
        help="Root directory containing benchmark subdirectories.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Target directory for generated task YAMLs.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    generated = generate_all_tasks(args.benchmarks_dir, args.output_dir)
    if not generated:
        logger.warning("No tasks generated. Check benchmarks directory.")
        sys.exit(1)


if __name__ == "__main__":
    main()
