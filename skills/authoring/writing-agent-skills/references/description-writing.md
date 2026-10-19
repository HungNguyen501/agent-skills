# Writing descriptions

The description is the only thing the agent sees when it decides whether to load a skill. It is injected into the system prompt, so it must work among 100 or more other skills.

## Contents
- Formula
- Rules
- Examples
- Trigger testing

## Formula

What it does, then inputs it needs and outputs it produces, then when to use it, then when not to.

## Rules

1. Third person. "Extracts text from PDFs", not "I can extract" or "You can use this to extract".
2. State the task and the triggers: file types, tool names, user phrases, situations.
3. Use the words a user would type. Include synonyms ("spreadsheet", ".xlsx", "tabular data").
4. Add a negative boundary wherever a sibling skill could be confused: "Not for X; use `other-skill`."
5. At most 1,024 characters. No XML tags. One description per skill.
6. No vague verbs: "helps with", "handles", "processes data", "does stuff".
7. Do not describe how the skill works. That is the body's job.

## Examples

Weak:
```yaml
description: Helps with documents
```

Good:
```yaml
description: Extracts text and tables from PDF files, fills forms and merges documents. Use when working with PDF files or when the user mentions PDFs, forms or document extraction. Not for Word or spreadsheet files.
```

Good, with a negative boundary for a hub skill:
```yaml
description: Writes SQL against Databricks billing system tables with the mandatory scope filters applied. Use for questions about cost, DBU usage or SKU spend. Not for job failures (use databricks-jobs-queries) or access questions.
```

## Trigger testing

Build a set of 15 to 20 queries. Half should trigger the skill and half should not.
- Include casual phrasing, precise phrasing and boundary cases.
- Include near-miss queries that share keywords but need a different skill. These matter most.
- Split roughly 60/40 into a set you tune on and a held-out set you only score on.
- Run each query several times, because triggering is not deterministic.
- Check with sibling skills installed. A neighbour's description can steal the trigger.

Method detail: https://agentskills.io/skill-creation/optimizing-descriptions
