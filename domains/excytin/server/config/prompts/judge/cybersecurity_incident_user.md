## Incident Context
**Domain:** {{ domain }}
**Task:** {{ task_id }}
**Episode:** {{ episode.episode_id }}
**Duration:** {{ episode.duration }} seconds
**Incident Question:** {{ question }}

## Expected Finding
**Golden Answer:** {{ golden_answer }}

## Agent Step-by-Step Execution Analysis
**Final Submission:** {{ submission }}
**Total Steps:** {{ episode.get_step_count() }}
**Completion Status:** {{ episode.state }}

### Complete Step-by-Step Investigation:
{% for step in episode.steps %}
**Step {{ step.step_number }}** ({{ step.timestamp }})
- Tool: {{ step.action.tool_name }}
- Parameters: {{ step.action.parameters | string | truncate(150) }}
- Response: {{ step.response | string | truncate(1500) }}
{% if step.done %}- **Episode ended here**{% endif %}

{% endfor %}

{% set failed_steps = episode.get_failed_steps() %}
{% if failed_steps %}
### Failed Operations Summary:
{% for step in failed_steps %}
- Step {{ step.step_number }}: {{ step.action.parameters | string | truncate(80) }} (FAILED)
  Error: {{ step.response | string | truncate(150) }}
{% endfor %}
{% endif %}

### Database Query Analysis:
{% for step in episode.steps %}
{% if step.action.tool_name == "mysql" or "mysql" in (step.action.parameters | string) %}
**Database Query Step {{ step.step_number }}:**
- Parameters: {{ step.action.parameters | string | truncate(200) }}
- Result: {{ step.response | string | truncate(350) }}
{% endif %}
{% endfor %}

## Evaluation Task

Analyze each step above against the subtask objectives. Identify which steps successfully completed which objectives (subtasks or main task). Consider the technical accuracy of findings, investigation methodology, and logical progression through the security incident analysis.

Provide your step evaluation in the required STEP_EVALUATIONS format.
