# Evaluating skills

Write evals before the skill body, so the skill answers real failures and not imagined ones.

## Contents
- Eval file format
- Evaluation-driven loop
- What to measure
- Test cases
- Iterating with two agents
- CI gates

## Eval file format

Each skill keeps `evals/evals.json`, an array of at least three cases. `scripts/validate.py` enforces the count.

```json
[
  {
    "id": "casual-phrasing",
    "skills": ["databricks-billing-queries"],
    "query": "how much did we spend on compute last month?",
    "files": [],
    "expected_behavior": [
      "Queries the billing usage system table",
      "Applies the mandatory catalog scope filter",
      "Does not invent column names"
    ]
  }
]
```

There is no built-in runner. Write a small one for your harness, or run the cases by hand at first and record the results.

## Evaluation-driven loop

1. Run the agent on representative tasks without the skill. Record concrete failures and missing context.
2. Write three cases that test those gaps.
3. Score the baseline.
4. Write the minimum instructions that close the gaps.
5. Re-run, compare with the baseline, refine.

If the baseline already passes, do not ship the skill.

## What to measure

| Dimension | Question |
|---|---|
| Functional viability | Is the output correct? |
| Directive compliance | Did the agent follow the skill's rules and workflow? |
| Operational efficiency | Tokens, tool calls and time, versus the baseline |

Track token cost on every change. Block merges that exceed an agreed regression limit.

## Test cases

Start with two or three, then add one for each failure you meet. Cover:
- Casual phrasing.
- Precise phrasing.
- A boundary condition.
- A red herring, where the right behaviour is to not use the skill or to refuse the wrong answer.

Test with every model you ship to. A small model may need more guidance, a large one less. Over-explaining wastes the large model's context.

## Iterating with two agents

Use one agent session ("A") to write and revise the skill and a fresh session ("B") to use it on real work.
1. Complete a real task with A and no skill. Note the context you supplied and the corrections you made.
2. Ask A to turn that into a skill.
3. Review for concision. Remove anything the agent already knows.
4. Run B on similar tasks. Watch where it hesitates, skips a rule or reads files in an odd order.
5. Take the specifics back to A and revise. Repeat.

Capture feedback from teammates' real use. Synthetic tests miss failure modes that real work shows.

## CI gates

- `scripts/validate.py` runs on every PR.
- A token-count comparison against the base branch is advisable once more than a few skills exist.
- Run the eval suite before promoting a new version. Roll back through git.

Full method: https://agentskills.io/skill-creation/evaluating-skills
