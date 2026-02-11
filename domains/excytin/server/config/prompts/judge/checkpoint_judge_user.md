## Incident Investigation Task

**Question:** {{ question }}

**Task Context:**
{% if task.description %}
{{ task.description }}
{% endif %}

---

## Agent Investigation Trace ({{ episode.get_step_count() }} steps)

{% for step in episode.steps %}
**[{{ step.step_number }}]** {{ step.action.tool_name }}
{% if step.action.parameters %}
Input: {{ step.action.parameters | string | truncate(300) }}
{% endif %}
{% if step.action.assistant_message %}
Agent Message: {{ step.action.assistant_message | truncate(800) }}
{% endif %}
{% if step.action.reasoning %}
Agent Reasoning: {{ step.action.reasoning | truncate(600) }}
{% endif %}
{% if step.response %}
Output: {{ step.response | string | truncate(1000) }}
{% endif %}
{% if step.done %}>>> Investigation ended here <<<{% endif %}

{% endfor %}

---

## Evaluation Task

Review the agent's investigation trajectory above and determine which checkpoint objectives were completed.

Remember:
- A checkpoint is completed when the agent **discovers** the specific information described (IP, SID, process ID, etc.)
- Look for evidence in tool outputs, query results, and agent understanding
- Use the STEP_EVALUATIONS format with `[step_number: checkpoint_id]` notation
- If no checkpoints were completed, respond with `[NO_COMPLETIONS]`
