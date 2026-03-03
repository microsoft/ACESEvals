## Incident Investigation Task

**Question:** {{ question }}

**Task Context:**
{% if task.description %}
{{ task.description }}
{% endif %}

---

## Agent Investigation Trace ({{ episode.get_step_count() }} steps)

{% for step in episode.steps %}
**[{{ step.step_number }}]** {{ step.tool_name }}
{% if step.tool_input %}
Input: {{ step.tool_input | string | truncate(300) }}
{% endif %}
{% if step.assistant_message %}
Agent Message: {{ step.assistant_message | truncate(800) }}
{% endif %}
{% if step.reasoning %}
Agent Reasoning: {{ step.reasoning | truncate(600) }}
{% endif %}
{% if step.output %}
Output: {{ step.output | string | truncate(1000) }}
{% endif %}

{% endfor %}

---

## Evaluation Task

Review the agent's investigation trajectory above and determine which checkpoint objectives were completed.

Remember:
- A checkpoint is completed when the agent **discovers** the specific information described (IP, SID, process ID, etc.)
- Look for evidence in tool outputs, query results, and agent understanding
- Use the STEP_EVALUATIONS format with `[step_number: checkpoint_id]` notation
- If no checkpoints were completed, respond with `[NO_COMPLETIONS]`
