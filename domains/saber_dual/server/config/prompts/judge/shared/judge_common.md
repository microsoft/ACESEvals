# Judge Common Guidelines

## Standard Response Format
All judge responses must follow this exact JSON structure:
```json
{
  "analysis": "Your detailed reasoning and evaluation explanation",
  "is_correct": true/false
}
```

## Core Evaluation Principles
- Be deterministic and consistent
- Focus on essential information matching
- Consider domain-specific context
- Provide clear reasoning in analysis field
- Use boolean true/false for is_correct field

## Common Validation Rules
- Exact match for technical identifiers (IPs, hashes, IDs)
- Case-sensitive matching for most security artifacts
- Whitespace normalization is acceptable
- Consider functionally equivalent expressions
