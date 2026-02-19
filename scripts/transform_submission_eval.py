#!/usr/bin/env python3
"""Transform submission_evaluation_config from static to llm_judge strategy.

This script updates all excytin task YAML files to:
1. Change strategy from "static" to "llm_judge"  
2. Update criteria from expected_answers to llm_judge config
3. Add comments showing how to switch back to static
"""

import re
from pathlib import Path

TASKS_DIR = Path(__file__).parent.parent / "domains/excytin/server/config/tasks"


def yaml_escape_for_single_quotes(value: str) -> str:
    """Escape a string value for use in YAML single quotes.
    
    In YAML single-quoted strings, single quotes are escaped by doubling them.
    """
    return value.replace("'", "''")


def transform_file(file_path: Path) -> bool:
    """Transform a single task YAML file.
    
    Returns True if file was modified, False otherwise.
    """
    lines = file_path.read_text().splitlines(keepends=True)
    output_lines = []
    i = 0
    modified = False
    
    while i < len(lines):
        line = lines[i]
        
        # Skip old comment blocks about "uses static matching by default"
        if '# Main task submission evaluation - uses static matching by default' in line:
            # Skip the entire old comment block (7 lines)
            skip_count = 0
            while i < len(lines) and skip_count < 7:
                if lines[i].strip().startswith('#'):
                    i += 1
                    skip_count += 1
                else:
                    break
            modified = True
            continue
        
        # Check for submission_evaluation_config with static strategy
        if line.strip() == 'submission_evaluation_config:':
            # Capture the indent
            indent = line[:len(line) - len(line.lstrip())]
            
            # Look ahead to check if this is a static config
            if i + 1 < len(lines) and 'strategy: static' in lines[i + 1]:
                # Parse the static config block
                config_start = i
                i += 1  # Move past submission_evaluation_config:
                
                # Skip strategy: static
                i += 1
                
                # Skip criteria:
                i += 1
                
                # Skip expected_answers:
                i += 1
                
                # Get the expected answer value - may span multiple lines  
                answer_line = lines[i].strip()
                if answer_line.startswith('- '):
                    raw_answer = answer_line[2:]
                    # Check if it's a multi-line value (ends with line continuation or is quoted but not closed)
                    # For now, just take the single line value
                    expected_answer = raw_answer.strip()
                    
                    # Handle YAML quoting - remove outer quotes if present
                    if expected_answer.startswith("'") and expected_answer.endswith("'"):
                        # Single-quoted: unescape '' to '
                        expected_answer = expected_answer[1:-1].replace("''", "'")
                    elif expected_answer.startswith('"') and expected_answer.endswith('"'):
                        # Double-quoted: basic unescaping
                        expected_answer = expected_answer[1:-1].replace('\\"', '"')
                i += 1
                
                # Skip scoring:
                i += 1
                
                # Get max_score
                max_score_line = lines[i].strip()
                max_score = "1.0"
                if max_score_line.startswith('max_score:'):
                    max_score = max_score_line.split(':')[1].strip()
                i += 1
                
                # Format the expected answer for comment - use single quotes to be safe
                escaped_for_comment = yaml_escape_for_single_quotes(expected_answer)
                comment_answer = f"'{escaped_for_comment}'"
                
                # Format golden_answer - use single quotes to safely handle internal double quotes
                escaped_for_golden = yaml_escape_for_single_quotes(expected_answer)
                
                # Write new config block with comments
                output_lines.append(f"{indent}# Main task submission evaluation - uses LLM-as-a-judge by default\n")
                output_lines.append(f"{indent}# To use static matching instead, change strategy to \"static\" and set:\n")
                output_lines.append(f"{indent}#   criteria:\n")
                output_lines.append(f"{indent}#     expected_answers:\n")
                output_lines.append(f"{indent}#       - {comment_answer}\n")
                output_lines.append(f"{indent}submission_evaluation_config:\n")
                output_lines.append(f"{indent}  strategy: llm_judge\n")
                output_lines.append(f"{indent}  criteria:\n")
                output_lines.append(f"{indent}    model: openai/azure/gpt-4.1\n")
                output_lines.append(f"{indent}    judge_system_template: judge/submission_judge_system.md\n")
                output_lines.append(f"{indent}    judge_user_template: judge/submission_judge_user.md\n")
                output_lines.append(f"{indent}    golden_answer: '{escaped_for_golden}'\n")
                output_lines.append(f"{indent}  scoring:\n")
                output_lines.append(f"{indent}    max_score: {max_score}\n")
                
                modified = True
                continue
        
        output_lines.append(line)
        i += 1
    
    if modified:
        file_path.write_text(''.join(output_lines))
    return modified


def main():
    """Transform all task YAML files."""
    task_files = []
    
    # Find all task YAML files (excluding shared.yaml and global.yaml)
    for yaml_file in TASKS_DIR.rglob("*.yaml"):
        if yaml_file.name not in ("shared.yaml", "global.yaml"):
            task_files.append(yaml_file)
    
    print(f"Found {len(task_files)} task files")
    
    modified_count = 0
    for task_file in sorted(task_files):
        try:
            if transform_file(task_file):
                modified_count += 1
                print(f"  Modified: {task_file.relative_to(TASKS_DIR)}")
        except Exception as e:
            print(f"  ERROR in {task_file}: {e}")
    
    print(f"\nTotal: {modified_count} files modified")


if __name__ == "__main__":
    main()
