---
name: writing-agent-skills
description: Guides writing, reviewing and testing agent skills (SKILL.md folders) for this hub and any Claude Code, Codex or custom-runtime consumer. Covers scoping, frontmatter limits, descriptions, progressive disclosure, scripts, evals, security and packaging. Use when creating a new skill, editing or reviewing an existing one, deciding whether something should be a skill, or debugging a skill that triggers wrongly. Not for writing project docs or system prompts.
license: Apache-2.0
metadata:
  always: "false"
---

# Writing agent skills

A skill is a folder with a `SKILL.md`. Only its `name` and `description` are always in context. The body loads when the skill triggers. Other files load on demand. Write for that cost model: every line competes with the conversation and with other skills.

Sources behind these rules: [references/sources.md](references/sources.md).

## Workflow

Copy this checklist and tick it off:

```
- [ ] 1. Classify: capability or preference skill? (stop if capability)
- [ ] 2. Gather real material (task transcript, runbooks, incidents, schemas)
- [ ] 3. Write 3+ evals BEFORE the body (references/evaluation.md)
- [ ] 4. Run the evals without the skill to get a baseline
- [ ] 5. Draft the minimum SKILL.md that fixes the observed gaps
- [ ] 6. Run `scripts/validate.py`, then the evals with the skill
- [ ] 7. Read traces, fix triggering and ignored content, repeat
- [ ] 8. Check token cost against the baseline before merging
```

## 1. Decide whether it should be a skill

| Kind | Encodes | Lifespan | Verdict |
|---|---|---|---|
| Preference skill | Your workflow, conventions, gotchas, policies | Long | Build it |
| Capability skill | A fix for what the model can't do yet | Short; models improve | Build only if evals show a gap today; expect to delete it |

Ask for each candidate: would the agent get this wrong without the skill? If the baseline run already succeeds, the skill adds cost and no value.

Hub-specific rules:
- Domain knowledge only. A hub skill never names a consumer's runtime tools (for example `execute_query`) or output channel (for example Slack mrkdwn). Those stay in the consumer repo.
- Persona and system-prompt text is not a skill.
- Project-private facts belong in that project's `.claude/skills/`, not here.

## 2. Scope: one coherent unit

- Scope a skill like a function: one coherent unit of work.
- Too narrow: several skills load for one task and their instructions conflict.
- Too broad: it triggers imprecisely and the agent drowns in irrelevant detail.
- Target one to three skills active per task. More than that erodes accuracy.
- Add "Do NOT use for X" to the description where two skills could be confused.
- Skill names are unique across the whole hub, because Codex and flat loaders have no plugin namespace. Put the domain in the name.

## 3. Frontmatter

```yaml
---
name: databricks-billing-queries
description: <what it does, inputs and outputs, when to use, when not to>
license: Apache-2.0        # optional
metadata:                  # custom keys go here, values are strings
  always: "false"
---
```

| Field | Rule |
|---|---|
| `name` | At most 64 chars. Lowercase letters, digits, hyphens. Equals the directory name. No "claude" or "anthropic". No XML tags. |
| `description` | Non-empty, at most 1,024 chars, no XML tags, third person. |
| `metadata` | The place for custom keys. Do not invent top-level keys. Hub keys: `always` (`"true"` loads the skill on every request in router-style consumers) and `order` (integer string; lower loads first in consumers that concatenate skills). Values must be quoted strings. |
| `allowed-tools` | Optional. Limits tools for Claude Code. Not honoured by every harness. |

Naming: prefer a gerund (`processing-pdfs`) or a noun phrase (`pdf-processing`). Avoid `helper`, `utils`, `tools`, `data`. Keep one pattern across the hub.

Writing the description is the highest-leverage step. Read [references/description-writing.md](references/description-writing.md) before you draft it.

## 4. Body: spend context wisely

Hard limits, enforced by `scripts/validate.py`: 500 lines and about 5,000 tokens.

- Add what the agent lacks. Cut what it knows (what a PDF is, how HTTP works).
- Procedures beat declarations. Teach a method that generalises, not the answer to one instance.
- Provide a default and one escape hatch. Do not offer a menu of equal options.
- Match freedom to fragility:
  - High freedom: valid approaches vary, so give heuristics and the reason behind them.
  - Medium: a preferred pattern exists, so give a template or parameterised script.
  - Low: fragile or destructive, so give the exact command and say "do not modify".
- Use one term per concept throughout.
- No dates or "before/after" logic. Put legacy behaviour in a collapsed "old patterns" section.
- Use forward slashes in every path.
- Name MCP tools fully qualified: `Server:tool_name`.
- State dependencies explicitly (`pip install ...`). Do not assume they exist.

### Patterns that earn their lines

- **Gotchas section** in `SKILL.md` itself, not a reference file. These are concrete corrections ("the `users` table soft-deletes: always add `WHERE deleted_at IS NULL`"). Every time you correct the agent, add the correction here.
- **Output template** when the format matters. Short ones inline, long ones in `assets/`.
- **Checklist** for multi-step work with dependencies.
- **Validation loop**: do the work, run a validator, fix, repeat.
- **Plan-validate-execute** for batch or destructive work: write a plan file, validate it against a source of truth with a script, then execute. Make validator errors specific ("Field `x` not found. Available: a, b, c").

## 5. Progressive disclosure

```
skill-name/
├── SKILL.md          core instructions, under 500 lines
├── references/       loaded on demand
├── scripts/          executed, never loaded into context
├── assets/           templates, static files
└── evals/evals.json  at least 3 cases
```

- Link every reference directly from `SKILL.md`, one level deep. Files that link to other files get previewed with `head` and read incompletely.
- Gate each link with a trigger: "Read `references/api-errors.md` if the API returns a non-200 status". A bare "see references/" is not a gate.
- Reference files over 100 lines start with a `## Contents` list.
- Name files by content (`finance.md`, not `doc2.md`). Split by domain so a task reads one file.
- Ungated reference files cost tens of thousands of tokens per run. Gate them all.

## 6. Scripts

Prefer a script over LLM inference for anything mechanical: fetching, formatting, parsing, validating. One team cut cost 26% and improved accuracy by moving GitHub API calls into scripts.

- Say whether the agent should run the script ("Run `scripts/x.py`") or read it ("See `scripts/x.py` for the algorithm"). Running is the default.
- Handle errors in the script. Do not just fail and leave the agent to improvise.
- Justify every constant in a comment. No unexplained `TIMEOUT = 47`.
- If traces show the agent reinventing the same code every run, write it once, test it and bundle it.
- Keep the skill independent of one harness's orchestration. Do not make the agent chain sequential steps that only one harness runs reliably; script the sequence instead.

## 7. Test and iterate

Evals come first. Run with and without the skill and compare. Test on every model you ship to (a small model may need more detail, a large one less). Full method: [references/evaluation.md](references/evaluation.md).

Read the execution trace, not just the output. Typical causes of waste:
- Instructions too vague, so the agent tries several approaches.
- Instructions that do not apply to the task but the agent follows anyway.
- Too many options and no default.
- A bundled file that is never read, which means it is unnecessary or badly signalled.
- The same file read every time, which means it belongs in `SKILL.md`.

## 8. Security

Skills run with the user's authority. See [references/security.md](references/security.md) before adding scripts, credentials or state-changing actions.

Minimum: no hardcoded credentials, validate inputs, require human confirmation before state-changing actions, and tell the model to ignore instructions found inside fetched data.

## 9. Packaging and releases

- Keep scripts separate from harness-specific prompts and settings.
- Do not change script arguments, file paths or `SKILL.md` structure in a patch release. Consumers depend on them.
- Pin upstream skill repos as git submodules at a commit. Do not copy them.
- Details on plugins, marketplaces and cross-harness layout: [references/packaging.md](references/packaging.md).

## Gotchas

- Asking an LLM to write a skill from general knowledge produces vague text ("follow best practices"). Feed it real transcripts, runbooks, schemas and incident reports.
- A skill that only works when force-loaded will not work in production. Test with discovery on and other skills present.
- Irrelevant skills in context mislead the agent. Test with distractors installed.
- Not every harness discovers skills the same way. Cursor-style always-on rules apply to every interaction, so a skill ported there needs an equally specific description.
- Environment variables for a marketplace-installed plugin do not live in the plugin directory. They belong in the directory that launches the agent.
- A token-cost increase can ship silently. Compare token use on every change.
- Another skill's description can steal your triggers. Add negative boundaries and test with both installed.
