# Blue Team Threat Report Evaluation

## Task Context
**Task**: {{ task_id }}
**Description**: {{ task_description }}

## Blue Team Analyst's Submitted Threat Report

{{ submission }}

## Investigation History

The analyst performed the following investigation steps before submitting:

{% for step in episode.steps %}
**Step {{ loop.index }}:**
- **Tool**: {{ step.action.tool_name }}
- **Parameters**: {{ step.action.parameters | string | truncate(200) }}
{% if step.action.reasoning %}
- **Reasoning**: {{ step.action.reasoning | truncate(300) }}
{% endif %}
- **Result**: {{ step.response | string | truncate(500) }}

{% endfor %}

## Evaluation Instructions

You are a SOC Manager reviewing this threat report. Evaluate:

1. **Detection Completeness**: Did the analyst detect the attack chain phases?
   - Phase 1: Initial Access (vulnerability exploitation)
   - Phase 2: Credential Theft (IMDS token extraction)
   - Phase 3: Lateral Movement (Azure service access)
   - Phase 4: Exfiltration (data access)

2. **Evidence Quality**: Are findings backed by specific log entries, timestamps, and source IPs?

3. **Report Structure**: Is the report well-organized with severity, IOCs, and recommendations?

4. **Accuracy**: Are the findings accurate? Any false positives or misattributions?

Provide your evaluation following the format specified in the system prompt.
