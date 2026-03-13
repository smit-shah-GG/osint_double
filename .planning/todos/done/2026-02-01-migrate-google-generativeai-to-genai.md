---
created: 2026-02-01T07:05
title: Migrate from google.generativeai to google.genai
area: llm
files:
  - osint_system/llm/gemini_client.py
  - osint_system/agents/planning_agent.py
  - requirements.txt
  - pyproject.toml
---

## Problem

The `google-generativeai` package is deprecated and no longer receiving updates or bug fixes. Every import shows a FutureWarning:

```
FutureWarning: All support for the `google.generativeai` package has ended.
Please switch to the `google.genai` package as soon as possible.
```

Files affected:
- `osint_system/llm/gemini_client.py` - Main Gemini client using `import google.generativeai as genai`
- `osint_system/agents/planning_agent.py` - Also imports the deprecated package
- `requirements.txt` - Lists `google-generativeai==0.8.3`
- `pyproject.toml` - Lists `google-generativeai>=0.8.6`

## Solution

1. Replace `google-generativeai` with `google-genai` in dependencies
2. Update import statements from `import google.generativeai as genai` to new package API
3. Review API differences - the new package may have different method signatures
4. Update `BlockedPromptException` import path
5. Test all LLM functionality after migration
