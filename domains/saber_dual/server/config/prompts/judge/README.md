# Judge Template Guide - SABER Framework

This directory contains judge templates for evaluating agent performance using Large Language Models (LLMs). Judge templates use Jinja2 templating with access to rich episode data including step-by-step agent execution history.

## Template Types

### System Templates
Define the judge's role, evaluation criteria, and output format.
- `cybersecurity_incident_system.md` - System prompt for cybersecurity evaluations
- `default_system.md` - General-purpose system prompt

### User Templates  
Provide task-specific context and the agent's work to evaluate.
- `cybersecurity_incident_user.md` - User prompt for cybersecurity incident response
- `default_user.md` - General-purpose user prompt

### Shared Templates
Common reusable components in the `shared/` directory.
- `judge_common.md` - Common evaluation guidelines

## Available Template Variables

### Basic Task Information
```jinja2
{{ domain }}              # Task domain (e.g., "cybersecurity")
{{ task_id }}             # Unique task identifier
{{ question }}            # The question/prompt given to the agent
{{ golden_answer }}       # Expected correct answer
{{ submission }}          # Agent's final submission
{{ model }}               # LLM model being used for judging
```

### Episode Object - Rich Execution Data
The `episode` object contains complete agent execution history:

```jinja2
{{ episode.episode_id }}        # Unique episode identifier
{{ episode.duration }}          # Total execution time in seconds
{{ episode.state }}             # Episode state: "completed", "failed", "timeout"
{{ episode.completion_reason }} # Why episode ended: "success", "timeout", "error"
{{ episode.start_time }}        # When episode started
{{ episode.end_time }}          # When episode ended (if completed)
{{ episode.submission }}        # Agent's final submission
{{ episode.metadata }}          # Additional episode metadata
{{ episode.context }}           # Episode context data
{{ episode.max_steps }}         # Maximum allowed steps
```

### Step-by-Step Execution Analysis
Access individual steps from the agent's execution:

```jinja2
{% for step in episode.steps %}
**Step {{ step.step_number }}** ({{ step.timestamp }})
- Tool: {{ step.action.tool_name }}
- Parameters: {{ step.action.parameters }}
- Response: {{ step.response }}
- Episode ended: {{ step.done }}
{% endfor %}
```

### Episode Helper Methods

#### `get_last_n_steps(n)` - Recent Steps
Get the last N steps for focused analysis:
```jinja2
### Recent Activity:
{% for step in episode.get_last_n_steps(3) %}
Step {{ step.step_number }}: {{ step.action.parameters.arguments }}
Result: {{ step.response.output[:100] }}...
{% endfor %}
```

#### `get_first_n_steps(n)` - Initial Steps  
Get the first N steps to see how the agent started:
```jinja2
### Initial Approach:
{% for step in episode.get_first_n_steps(2) %}
Step {{ step.step_number }}: {{ step.action.tool_name }}
{% endfor %}
```

#### `get_failed_steps()` - Error Analysis
Find steps that failed (non-zero exit codes):
```jinja2
{% if episode.get_failed_steps() %}
### Failed Operations:
{% for step in episode.get_failed_steps() %}
- Step {{ step.step_number }}: {{ step.action.parameters.arguments }} (FAILED)
  Error: {{ step.response.output }}
{% endfor %}
{% endif %}
```

#### `get_commands_summary(max_length)` - Command Overview
Get a summary of all commands with length limit:
```jinja2
### Command Summary (Limited to 400 chars):
{{ episode.get_commands_summary(400) }}
```

#### `get_step_count()` - Total Steps
Get the total number of steps executed:
```jinja2
**Total Steps Executed:** {{ episode.get_step_count() }}
```

## Agent Prompt Templates (For Reference)

When creating agent prompts, you can also include subtasks to break down complex tasks:

### Subtask Listing in Agent Prompts
```jinja2
## Subtasks
{% if subtasks %}
Your mission includes the following subtasks:
{% for subtask in subtasks %}
### {{ subtask.title }}
**Description:** {{ subtask.description }}
**Objective:** {{ subtask.objective }}
{% if subtask.required_tools %}
**Required Tools:** {{ subtask.required_tools|join(", ") }}
{% endif %}
{% if subtask.success_criteria %}
**Success Criteria:** {{ subtask.success_criteria }}
{% endif %}

{% endfor %}
{% else %}
No specific subtasks defined for this mission.
{% endif %}
```

### Subtask Context in Agent Prompts
You can also reference subtask data in conditional blocks:
```jinja2
{% if subtasks|length > 1 %}
This is a multi-part mission with {{ subtasks|length }} subtasks. Complete them systematically.
{% elif subtasks|length == 1 %}
Focus on the single subtask: {{ subtasks[0].title }}
{% endif %}
```

## Example Judge Template Patterns

### Comprehensive Evaluation Template
```jinja2
## Task Evaluation: {{ task_id }}

**Question:** {{ question }}
**Expected Answer:** {{ golden_answer }}
**Agent Submission:** {{ submission }}
**Execution Time:** {{ episode.duration }} seconds

### Execution Analysis
**Total Steps:** {{ episode.get_step_count() }}
**Final State:** {{ episode.state }}

### Command Execution Summary:
{{ episode.get_commands_summary(300) }}

### Recent Steps Analysis:
{% for step in episode.get_last_n_steps(5) %}
**Step {{ step.step_number }}** - {{ step.action.tool_name }}
Command: {{ step.action.parameters }}
Output: {{ step.response.output[:100] }}{% if step.response.output|length > 100 %}...{% endif %}
{% endfor %}

### Error Analysis:
{% set failed_steps = episode.get_failed_steps() %}
{% if failed_steps %}
Found {{ failed_steps|length }} failed steps:
{% for step in failed_steps %}
- Step {{ step.step_number }}: {{ step.response.output[:50] }}...
{% endfor %}
{% else %}
No failed steps detected.
{% endif %}
```

### Step Filtering and Analysis
```jinja2
### Tool Usage Pattern:
{% for step in episode.steps %}
{% if step.action.tool_name == "bash" %}
Bash Step {{ step.step_number }}: {{ step.action.parameters.arguments[:60] }}
{% elif step.action.tool_name == "python" %}
Python Step {{ step.step_number }}: Used Python for analysis
{% endif %}
{% endfor %}

### Success Indicators:
{% for step in episode.steps %}
{% if "success" in step.response.output|lower or step.response.get("exit_code") == 0 %}
✓ Step {{ step.step_number }} completed successfully
{% endif %}
{% endfor %}
```

## Best Practices

1. **Use Helper Methods**: Leverage `get_last_n_steps()`, `get_failed_steps()`, etc. for focused analysis
2. **Limit Output Length**: Truncate long command outputs to keep prompts manageable
3. **Conditional Analysis**: Use `{% if %}` blocks to handle optional data
4. **Temporal Analysis**: Use `episode.duration` and timestamps for timing evaluation
5. **Error Handling**: Always check for failed steps and error conditions
6. **Template Inheritance**: Use `{% include %}` for shared components

## Include System

Use shared templates for common patterns:
```jinja2
{% include 'shared/judge_common.md' %}
```

This allows reusing evaluation guidelines, formatting rules, and common template logic across multiple judge templates.
