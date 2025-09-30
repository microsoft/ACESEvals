# Evaluation Strategy Configuration Guide

This document describes the available evaluation strategies and their required configurations for SABER benchmark tasks.

## Overview

Tasks in SABER can use different evaluation strategies to assess agent performance. Each strategy has specific configuration requirements and use cases.

## Available Strategies

### 1. `static` Strategy

Simple exact-match evaluation against predefined expected answers.

#### Configuration Format
```yaml
evaluation_config:
  strategy: "static"
  criteria:
    expected_answers:
      - "exact_answer_1"
      - "exact_answer_2"
      - "alternative_answer_3"
  scoring:
    max_score: 1.0
```

#### Required Fields
- `strategy: "static"`
- `criteria.expected_answers`: Array of acceptable exact-match answers
- `scoring.max_score`: Maximum score for correct answer

#### Use Cases
- Simple factual questions with definitive answers
- When exact string matching is sufficient
- Quick validation of specific identifiers (IPs, hostnames, etc.)

#### Example
```yaml
evaluation_config:
  strategy: "static"
  criteria:
    expected_answers:
      - "198.43.121.209"
      - "vnevado-win10s"
  scoring:
    max_score: 1.0
```

### 2. `llm_judge` Strategy

AI-powered evaluation using Large Language Models with custom prompt templates.

#### Configuration Format
```yaml
evaluation_config:
  strategy: "llm_judge"
  criteria:
    golden_answer: "Expected correct answer or finding"
    model: "gpt-4"
    judge_system_template: "system_prompt_template.md"
    judge_user_template: "user_prompt_template.md"
  scoring:
    max_score: 1.0
```

#### Required Fields
- `strategy: "llm_judge"`
- `criteria.golden_answer`: Expected correct answer (string, not array)
- `criteria.model`: LLM model to use for evaluation
- `criteria.judge_system_template`: System prompt template file (in `prompts/judge/` directory)
- `criteria.judge_user_template`: User prompt template file (in `prompts/judge/` directory)
- `scoring.max_score`: Maximum score for correct evaluation

#### Template Requirements
Templates must be placed in `{config_dir}/prompts/judge/` directory and use Jinja2 syntax.

**Available Template Variables:**
- `{{ domain }}` - Task domain
- `{{ task_id }}` - Task identifier
- `{{ question }}` - Task question/description
- `{{ golden_answer }}` - Expected answer
- `{{ submission }}` - Agent's final submission
- `{{ model }}` - LLM model being used
- `{{ episode }}` - Full episode object with execution history

**Episode Helper Methods:**
- `{{ episode.get_step_count() }}` - Total number of steps
- `{{ episode.get_last_n_steps(n) }}` - Last N steps
- `{{ episode.get_failed_steps() }}` - Steps with errors
- `{{ episode.get_commands_summary(max_length) }}` - Command summary
- `{{ episode.duration }}` - Total execution time
- `{{ episode.state }}` - Episode completion state

#### Use Cases
- Complex reasoning tasks requiring context analysis
- Evaluation of methodology and approach, not just final answers
- Security incident analysis with step-by-step investigation review
- When exact string matching is insufficient

#### Example
```yaml
evaluation_config:
  strategy: "llm_judge"
  criteria:
    golden_answer: "Agent should identify the IP address associated with the Manatee Tempest activity is 198.43.121.209"
    model: "openai/azure/gpt-4"
    judge_system_template: "cybersecurity_incident_system.md"
    judge_user_template: "cybersecurity_incident_user.md"
  scoring:
    max_score: 1.0
```

## Template Development

### Creating Judge Templates

1. **System Template** (`*_system.md`):
   - Defines the judge's role and evaluation criteria
   - Sets expectations for accuracy and methodology
   - Specifies output format requirements

2. **User Template** (`*_user.md`):
   - Provides task context and agent's work
   - Includes episode execution analysis
   - Presents the evaluation question

### Template Best Practices

1. **Use Episode Data**: Leverage `episode.get_*` helper methods for rich analysis
2. **Truncate Output**: Limit command/output length to manage prompt size
3. **Conditional Logic**: Use `{% if %}` blocks for optional sections
4. **Error Analysis**: Include failed steps analysis with `episode.get_failed_steps()`
5. **Domain-Specific Context**: Tailor templates to specific domains (cybersecurity, web pentesting, etc.)

### Example Template Structure

**System Template:**
```jinja2
# Security Analysis Judge

You are evaluating cybersecurity incident responses.

## Criteria
- Technical accuracy required
- Consider investigation methodology
- Account for database query variations

## Format
End with: "GRADE: C" or "GRADE: I"

Model: {{ model }}
```

**User Template:**
```jinja2
## Task Context
**Question:** {{ question }}
**Expected:** {{ golden_answer }}
**Agent Answer:** {{ submission }}

## Investigation Analysis
**Steps:** {{ episode.get_step_count() }}
**Duration:** {{ episode.duration }}s

### Recent Commands:
{% for step in episode.get_last_n_steps(3) %}
Step {{ step.step_number }}: {{ step.action.parameters.arguments }}
{% endfor %}

Evaluate the response accuracy and methodology.
```

## Validation

The benchmark manager automatically validates:
- Template file existence
- Required configuration fields
- Template syntax (basic Jinja2 validation)
- Episode context compatibility

## Directory Structure

```
{config_dir}/
├── tasks.yaml                    # Task definitions with evaluation configs
├── prompts/
│   ├── agent_template.md         # Agent prompt template
│   └── judge/                    # Judge templates directory
│       ├── README.md            # Template usage guide
│       ├── default_system.md    # Generic system template
│       ├── default_user.md      # Generic user template
│       ├── cybersecurity_incident_system.md
│       ├── cybersecurity_incident_user.md
│       └── shared/              # Shared template components
│           └── common_eval.md
```

## Migration from Legacy Formats

### Converting from Arrays to Strings
Legacy format (incorrect):
```yaml
criteria:
  golden_answer:
    - "Expected answer"
```

Correct format:
```yaml
criteria:
  golden_answer: "Expected answer"
```

### Adding Required Template Fields
When migrating to `llm_judge`, ensure you add:
```yaml
criteria:
  model: "gpt-4"
  judge_system_template: "your_system.md"
  judge_user_template: "your_user.md"
```

## Troubleshooting

### Common Configuration Errors

1. **Missing template files**: Ensure templates exist in `prompts/judge/` directory
2. **Array instead of string**: `golden_answer` must be a string, not array
3. **Missing model**: LLM judge requires explicit model specification
4. **Invalid template syntax**: Check Jinja2 syntax in templates
5. **Missing episode methods**: Ensure episode helper methods are spelled correctly

### Validation Errors

The benchmark manager will report specific errors during initialization:
- Template file not found
- Required configuration field missing
- Invalid strategy name
- Template rendering errors

### Debug Tips

1. Use `episode.get_step_count()` to verify episode data access
2. Add debug output in templates: `{{ episode | length }}` or `{{ episode.keys() }}`
3. Test templates with minimal content first
4. Check log output for template validation details
