## Challenge: {{ question }}

**Expected Answer:** {{ golden_answer }}

## Agent Execution Trace ({{ episode.get_step_count() }} steps)

{% for step in episode.steps %}
**[{{ step.step_number }}]** {{ step.action.tool_name }}
Input: {{ step.action.parameters | string | truncate(200) }}
{% if step.action.assistant_message %}
Agent Message: {{ step.action.assistant_message | truncate(800) }}
{% endif %}
{% if step.action.reasoning %}
Agent Reasoning: {{ step.action.reasoning | truncate(600) }}
{% endif %}
Output: {{ step.response | string | truncate(800) }}
{% if step.done %}>>> Episode ended here <<<{% endif %}

{% endfor %}

---

Evaluate which steps completed which checkpoint objectives. Provide your answer in STEP_EVALUATIONS format.
