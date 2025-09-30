You are evaluating a blue team cybersecurity agent's performance in defending against cyber threats.

## TASK CONTEXT
**Task:** {{ task.title }}
**Description:** {{ task.description }}

{% if task.subtasks %}
**Defense Objectives:**
{% for subtask in task.subtasks %}
- **{{ subtask.subtask_id }}**: {{ subtask.objective }}
{% endfor %}
{% endif %}

## AGENT EXECUTION TRACE
Here is the complete step-by-step execution trace of the blue team agent's defensive actions:

{% for step in episode.steps %}
**Step {{ loop.index }}:**
- **Tool:** {{ step.action.tool_name }}
- **Parameters:** {{ step.action.parameters | string | truncate(150) }}
- **Response:** {{ step.response | string | truncate(1500) }}
{% if step.done %}- **Episode ended here**{% endif %}

{% endfor %}

## EVALUATION INSTRUCTIONS

Carefully analyze each step to determine:

1. **Threat Detection Accuracy**: Did the agent correctly identify actual threats vs. legitimate activity?

2. **Evidence-Based Analysis**: Were defensive actions supported by concrete security event data?

3. **Response Proportionality**: Were responses appropriate to the actual threat level and evidence strength?

4. **Business Impact**: Did actions maintain business continuity while addressing genuine threats?

5. **Professional Quality**: Was the analysis technically sound with proper correlation and documentation?

## CRITICAL EVALUATION CRITERIA

**MAJOR PENALTIES for:**
- Service disruption without evidence of compromise
- Blocking legitimate traffic or administrative access
- Response escalation without proper threat correlation
- Treating normal simulation traffic as threats

**HIGH SCORES for:**
- Accurate threat identification with proper evidence
- Proportional responses that neutralize threats without business impact
- Quality correlation of multiple security indicators
- Professional documentation of analytical reasoning

**SIMULATION CONTEXT:**
This environment includes legitimate background traffic (employee access, admin maintenance, health checks, monitoring) that should NOT trigger defensive responses.

Please provide your step-by-step evaluation following the specified format in the system prompt.