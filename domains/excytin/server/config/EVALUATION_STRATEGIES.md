# Excytin Domain Evaluation Strategy Guide

This document describes the evaluation strategies used in the Excytin incident response domain.

## Overview

Excytin uses a **two-tier evaluation system**:

1. **Main Task (Submission) Evaluation**: Evaluates the agent's final answer
2. **Subtask (Checkpoint) Evaluation**: Evaluates whether the agent discovered key information during investigation

**Score Calculation:**
```
total_score = submission_score + sum(weighted_subtask_scores)
normalized_score = total_score / max_possible  # Returns 0.0 to 1.0
```

Typical weight ratio: **1.0 (task) : 0.5 (total subtasks)**

---

## Main Task Evaluation Strategies

### 1. `static` Strategy (Default)

Simple pattern-matching evaluation against predefined expected answers.

#### Configuration Format
```yaml
submission_evaluation_config:
  strategy: static
  criteria:
    expected_answers:
      - "198.43.121.209"
      - "alternative_answer"  # Multiple acceptable answers supported
  scoring:
    max_score: 1.0
```

#### When to Use
- Simple factual questions with definitive answers
- When exact string matching is sufficient
- Quick validation of specific identifiers (IPs, hostnames, file names, etc.)

---

### 2. `llm_judge` Strategy (Optional for Main Task)

AI-powered evaluation using LLMs with custom prompt templates.

#### Configuration Format
```yaml
submission_evaluation_config:
  strategy: llm_judge
  criteria:
    model: openai/azure/gpt-4.1
    judge_system_template: judge/submission_judge_system.md
    judge_user_template: judge/submission_judge_user.md
    golden_answer: "198.43.121.209"
  scoring:
    max_score: 1.0
```

#### Required Fields
- `strategy: llm_judge`
- `criteria.model`: LLM model (e.g., `openai/azure/gpt-4.1`)
- `criteria.judge_system_template`: System prompt template path
- `criteria.judge_user_template`: User prompt template path
- `criteria.golden_answer`: Expected answer (string, not array)

#### When to Use
- Complex answers that may be phrased differently
- When semantic equivalence matters more than exact match

#### Available Templates
- `judge/submission_judge_system.md` - System prompt for submission evaluation
- `judge/submission_judge_user.md` - User prompt with question, expected answer, and submission

---

## Subtask (Checkpoint) Evaluation

Subtasks represent **key information the agent should discover** during their investigation. They are evaluated using LLM-based trajectory analysis.

### `llm_judge` Strategy for Checkpoints

All checkpoints use LLM trajectory evaluation to determine if the agent discovered the checkpoint information.

#### Configuration Format
```yaml
subtasks:
  - subtask_id: checkpoint_1
    title: Checkpoint 1
    description: The account with SID `S-1-5-21-...` was involved in C2 behavior.
    objective: Identify key details related to the potential compromise.
    step_evaluation_config:
      strategy: llm_judge
      criteria:
        model: openai/azure/gpt-4.1
        judge_system_template: judge/checkpoint_judge_system.md
        judge_user_template: judge/checkpoint_judge_user.md
        steps_per_message: 50  # Steps per LLM call (batching)
      scoring:
        max_score: 0.25  # Individual checkpoint score
        weight: 1.0      # Weight multiplier
```

#### How It Works
1. LLM reviews the agent's full investigation trajectory (tool calls, outputs, reasoning)
2. For each checkpoint, LLM determines if the agent discovered the described information
3. Output format: `[step_number: checkpoint_id]` for each discovered checkpoint
4. A checkpoint is complete if discovered in **any** step of the trajectory

#### Available Templates
- `judge/checkpoint_judge_system.md` - System prompt for trajectory checkpoint evaluation
- `judge/checkpoint_judge_user.md` - User prompt with investigation trace

#### Checkpoint Scoring
- Each checkpoint has a `max_score` (e.g., 0.25 for 2 checkpoints = 0.5 total)
- Checkpoints are binary: fully awarded or 0
- Final subtask score = sum of individual checkpoint scores

---

## Template Variables

### Submission Templates
| Variable | Description |
|----------|-------------|
| `{{ question }}` | Task question/description |
| `{{ golden_answer }}` | Expected answer |
| `{{ submission }}` | Agent's final submission |
| `{{ task_id }}` | Task identifier |
| `{{ domain }}` | Domain name |

### Checkpoint Templates
| Variable | Description |
|----------|-------------|
| `{{ question }}` | Task question/description |
| `{{ episode }}` | Episode object with investigation steps |
| `{{ episode.steps }}` | List of all steps |
| `{{ episode.get_step_count() }}` | Total number of steps |
| `{{ task }}` | Task object with subtasks |
| `{{ task.subtasks }}` | List of checkpoint definitions |

---

## Directory Structure

```
domains/excytin/server/config/
├── prompts/
│   └── judge/
│       ├── submission_judge_system.md   # Main task LLM evaluation
│       ├── submission_judge_user.md
│       ├── checkpoint_judge_system.md   # Subtask/checkpoint evaluation
│       └── checkpoint_judge_user.md
└── tasks/
    └── incident_*/
        └── incident_*_*.yaml            # Task definitions
```

---

## Complete Task Example

```yaml
tasks:
  - task_id: incident_5_task_1
    title: incident_5_task_1
    description: What is the IP address associated with the Manatee Tempest activity group?
    inherit_shared: true
    initial_context:
      incident_context: A command and control behavior was blocked...
      question: What is the IP address associated with the Manatee Tempest activity group?
    
    # Main task evaluation - static matching (default)
    # To use LLM-as-a-judge, change strategy to "llm_judge" and add:
    #   criteria:
    #     model: openai/azure/gpt-4.1
    #     judge_system_template: judge/submission_judge_system.md
    #     judge_user_template: judge/submission_judge_user.md
    #     golden_answer: "198.43.121.209"
    submission_evaluation_config:
      strategy: static
      criteria:
        expected_answers:
          - 198.43.121.209
      scoring:
        max_score: 1.0
    
    # Subtask checkpoints - LLM trajectory evaluation
    subtasks:
      - subtask_id: checkpoint_1
        title: Checkpoint 1
        description: The account with SID `S-1-5-21-...` was involved in C2 behavior.
        objective: Identify key details related to the potential compromise.
        step_evaluation_config:
          strategy: llm_judge
          criteria:
            model: openai/azure/gpt-4.1
            judge_system_template: judge/checkpoint_judge_system.md
            judge_user_template: judge/checkpoint_judge_user.md
            steps_per_message: 50
          scoring:
            max_score: 0.25
            weight: 1.0
      
      - subtask_id: checkpoint_2
        title: Checkpoint 2
        description: Manatee Tempest group associated with IP `198.43.121.209`.
        objective: Identify key details related to the potential compromise.
        step_evaluation_config:
          strategy: llm_judge
          criteria:
            model: openai/azure/gpt-4.1
            judge_system_template: judge/checkpoint_judge_system.md
            judge_user_template: judge/checkpoint_judge_user.md
            steps_per_message: 50
          scoring:
            max_score: 0.25
            weight: 1.0
```

---

## Switching Between Strategies

### To enable LLM-as-a-judge for main task:

Replace:
```yaml
submission_evaluation_config:
  strategy: static
  criteria:
    expected_answers:
      - 198.43.121.209
  scoring:
    max_score: 1.0
```

With:
```yaml
submission_evaluation_config:
  strategy: llm_judge
  criteria:
    model: openai/azure/gpt-4.1
    judge_system_template: judge/submission_judge_system.md
    judge_user_template: judge/submission_judge_user.md
    golden_answer: "198.43.121.209"
  scoring:
    max_score: 1.0
```

---

## Troubleshooting

### Common Issues

1. **"Unknown subtask strategy" error**: Ensure strategy is lowercase `llm_judge`, not `LLM_JUDGE`
2. **Template not found**: Check template path is relative to `prompts/` directory
3. **Model API errors**: Verify model name format (e.g., `openai/azure/gpt-4.1`)
4. **Empty checkpoint scores**: Review checkpoint descriptions - they should contain discoverable facts

### Debug Tips

1. Check logs for "Batch LLM subtask evaluation" entries
2. Verify template variables with `{{ episode.get_step_count() }}`
3. Test with a single task first using `-T task_filter="incident_5_task_1"`
