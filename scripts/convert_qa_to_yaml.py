#!/usr/bin/env python3
"""Convert Q/A JSON dataset to SABER YAML task format.

This script reads Q/A pairs from the new_dataset JSON files and converts them
to SABER-compatible YAML task definitions with checkpoints.

Usage:
    python scripts/convert_qa_to_yaml.py
"""

import json
import os
import re
from pathlib import Path
from typing import Any


def yaml_escape(value: str) -> str:
    """Escape a string value for YAML single quotes and clean control characters."""
    if value is None:
        return ""
    # Remove control characters (0x00-0x1F except newline, tab)
    import re
    value = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', value)
    # Escape single quotes by doubling them
    return value.replace("'", "''")


def extract_incident_number(filename: str) -> str:
    """Extract incident number from filename like 'incident_5_qa_...json'."""
    match = re.search(r'incident_(\d+)_', filename)
    return match.group(1) if match else "0"


def create_task_yaml(
    task_id: str,
    question: str,
    context: str,
    answer: str,
    solution: list[str],
    incident_num: str,
) -> str:
    """Create a YAML task definition from Q/A data."""
    
    # Escape values for YAML
    escaped_question = yaml_escape(question)
    escaped_context = yaml_escape(context)
    escaped_answer = yaml_escape(answer)
    
    # Build subtasks from solution steps (these are the checkpoints)
    subtasks_yaml = ""
    for i, step in enumerate(solution, 1):
        escaped_step = yaml_escape(step)
        subtasks_yaml += f"""      - subtask_id: checkpoint_{i}
        title: Checkpoint {i}
        description: '{escaped_step}'
        objective: Identify key details related to the potential compromise that might
          help in solving the main task.
        step_evaluation_config:
          strategy: llm_judge
          criteria:
            model: openai/azure/gpt-4.1
            judge_system_template: judge/checkpoint_judge_system.md
            judge_user_template: judge/checkpoint_judge_user.md
            steps_per_message: 50
          scoring:
            max_score: {round(1.0 / len(solution), 3) if solution else 1.0}
            weight: 1.0
"""
    
    yaml_content = f"""tasks:
  - task_id: {task_id}
    title: {task_id}
    description: '{escaped_question}'
    inherit_shared: true
    initial_context:
      incident_context: '{escaped_context}'
      question: '{escaped_question}'
    # Main task submission evaluation - uses LLM-as-a-judge by default
    # To use static matching instead, change strategy to "static" and set:
    #   criteria:
    #     expected_answers:
    #       - '{escaped_answer}'
    submission_evaluation_config:
      strategy: llm_judge
      criteria:
        model: openai/azure/gpt-4.1
        judge_system_template: judge/submission_judge_system.md
        judge_user_template: judge/submission_judge_user.md
        golden_answer: '{escaped_answer}'
      scoring:
        max_score: 1.0
    subtasks:
{subtasks_yaml}"""
    
    return yaml_content


def copy_shared_yaml(incident_num: str, output_dir: Path, task_set: str, tasks_dir: Path) -> None:
    """Copy shared.yaml from legacy_test_set to a new task set folder."""
    legacy_shared = tasks_dir / "legacy_test_set" / f"incident_{incident_num}" / "shared.yaml"
    target_shared = output_dir / task_set / f"incident_{incident_num}" / "shared.yaml"
    
    if legacy_shared.exists():
        import shutil
        shutil.copy(legacy_shared, target_shared)
    else:
        # Fallback: create minimal shared.yaml if legacy doesn't exist
        target_shared.write_text(f"""# Shared configuration for incident_{incident_num} {task_set} tasks
# WARNING: Copied from fallback, may need to be updated with proper database_connection

initial_context:
  database_connection:
    hostname: incident-{incident_num}-db
    port: 3306
    username: admin
    password: admin
    database: env_monitor_db
    ssl_mode: disabled
    connection_example: mysql -h incident-{incident_num}-db --skip-ssl -u admin -padmin env_monitor_db

prompt_template_file: excytin_demo.md
sandbox_environment: excytin_sandbox
""")


def convert_json_to_yaml(
    json_file: Path,
    output_dir: Path,
    task_set: str,  # 'latest_test_set' or 'latest_train_set'
) -> int:
    """Convert a JSON Q/A file to YAML task files.
    
    Returns the number of tasks created.
    """
    incident_num = extract_incident_number(json_file.name)
    
    # Create output directory
    incident_dir = output_dir / task_set / f"incident_{incident_num}"
    incident_dir.mkdir(parents=True, exist_ok=True)
    
    # Load JSON data
    with open(json_file) as f:
        questions = json.load(f)
    
    # Filter to only questions with actual content
    valid_questions = [q for q in questions if q.get('question') and q.get('answer')]
    
    # Create individual task YAML files
    task_count = 0
    for i, qa in enumerate(valid_questions, 1):
        task_id = f"incident_{incident_num}_{task_set}_task_{i}"
        
        yaml_content = create_task_yaml(
            task_id=task_id,
            question=qa.get('question', ''),
            context=qa.get('context', ''),
            answer=qa.get('answer', ''),
            solution=qa.get('solution', []),
            incident_num=incident_num,
        )
        
        # Write task file
        task_file = incident_dir / f"incident_{incident_num}_{i}.yaml"
        task_file.write_text(yaml_content)
        task_count += 1
    
    # Create shared.yaml for this incident (copy from legacy_test_set)
    copy_shared_yaml(incident_num, output_dir, task_set, output_dir)
    
    return task_count


def move_legacy_tasks(tasks_dir: Path) -> None:
    """Move existing incident_* folders to legacy_test_set/."""
    legacy_dir = tasks_dir / "legacy_test_set"
    legacy_dir.mkdir(exist_ok=True)
    
    # Find all incident_* folders (not in new_dataset or other task sets)
    for item in tasks_dir.iterdir():
        if item.is_dir() and item.name.startswith("incident_") and item.name not in ["new_dataset"]:
            # Move to legacy_test_set
            dest = legacy_dir / item.name
            if not dest.exists():
                item.rename(dest)
                print(f"  Moved {item.name} -> legacy_test_set/{item.name}")
            else:
                print(f"  Skipped {item.name} (already exists in legacy_test_set)")


def create_global_yaml_for_set(tasks_dir: Path, task_set: str, permanent_env: str) -> None:
    """Create a global.yaml for a specific task set."""
    set_dir = tasks_dir / task_set
    if not set_dir.exists():
        return
    
    global_content = f"""domain: excytin
# Permanent environment with all 8 incident databases
permanent_environment: {permanent_env}

global_defaults:
  prompts:
    instruction: "instructions/excytin_demo.md"
    assistant: "assistants/inspect_assistant.md"
    submit: "submits/inspect_submit.md"
    continue: "continues/inspect_continue.md"

  execution_config:
    executors:
      bash:
        timeout: 180
      python:
        timeout: 180

  episode_config:
    max_steps: 25

    # Transcript coordination configuration
    transcript_config:
      websocket:
        push:
          enabled: true
        pull:
          enabled: false

  benchmark_config:
    episode_attempts: 1

  # Dependency resolution configuration
  dependency_config:
    wait_seconds: 10.0
    retry_interval: 0.5
    max_retry_interval: 2.0
"""
    
    global_file = set_dir / "global.yaml"
    global_file.write_text(global_content)
    print(f"  Created {task_set}/global.yaml")


def main():
    """Convert all Q/A JSON files to YAML task format."""
    script_dir = Path(__file__).parent.parent
    tasks_dir = script_dir / "domains/excytin/server/config/tasks"
    new_dataset_dir = tasks_dir / "new_dataset"
    
    print("=" * 60)
    print("Converting Q/A Dataset to SABER YAML Task Format")
    print("=" * 60)
    
    # Step 1: Move existing tasks to legacy_test_set
    print("\n1. Moving legacy tasks to legacy_test_set/...")
    move_legacy_tasks(tasks_dir)
    
    # Step 2: Convert test JSON files to latest_test_set
    print("\n2. Converting test set JSON files...")
    test_dir = new_dataset_dir / "test"
    total_test = 0
    for json_file in sorted(test_dir.glob("*.json")):
        if ":sec" in json_file.name:
            continue
        count = convert_json_to_yaml(json_file, tasks_dir, "latest_test_set")
        print(f"  {json_file.name}: {count} tasks")
        total_test += count
    print(f"  Total test tasks: {total_test}")
    
    # Step 3: Convert train JSON files to latest_train_set
    print("\n3. Converting train set JSON files...")
    train_dir = new_dataset_dir / "train"
    total_train = 0
    for json_file in sorted(train_dir.glob("*.json")):
        if ":sec" in json_file.name:
            continue
        count = convert_json_to_yaml(json_file, tasks_dir, "latest_train_set")
        print(f"  {json_file.name}: {count} tasks")
        total_train += count
    print(f"  Total train tasks: {total_train}")
    
    # Step 4: Create global.yaml for each task set
    print("\n4. Creating global.yaml files for each task set...")
    create_global_yaml_for_set(tasks_dir, "legacy_test_set", "all_incidents")
    create_global_yaml_for_set(tasks_dir, "latest_test_set", "all_incidents")
    create_global_yaml_for_set(tasks_dir, "latest_train_set", "all_incidents")
    
    print("\n" + "=" * 60)
    print("Conversion complete!")
    print(f"  Legacy test set: existing tasks in legacy_test_set/")
    print(f"  Latest test set: {total_test} tasks in latest_test_set/")
    print(f"  Latest train set: {total_train} tasks in latest_train_set/")
    print("=" * 60)


if __name__ == "__main__":
    main()
