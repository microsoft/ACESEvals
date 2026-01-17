# React2Shell Threat Report Evaluation

## Task Context
**Task**: {{ task_title }}
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

1. **Detection Completeness**: Did the analyst detect the React2Shell attack chain phases?
   - Phase 1: Initial Access (React RCE via /_next/rsc)
   - Phase 2: Credential Theft (IMDS token extraction)
   - Phase 3: Lateral Movement (ARM/KeyVault/Functions access)
   - Phase 4: Exfiltration (Blob storage access)

2. **Evidence Quality**: Are findings backed by specific log entries, timestamps, and source IPs?

3. **Report Structure**: Is the report well-organized with severity, IOCs, and recommendations?

4. **Accuracy**: Are the findings accurate? Any false positives or misattributions?

Provide your evaluation following the format specified in the system prompt.
