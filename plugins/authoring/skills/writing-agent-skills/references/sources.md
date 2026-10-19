# Sources

The rules in this skill consolidate the following sources. Re-check them when they change. Where sources disagree, the stricter rule is used.

## Contents
- Red Hat: Building skills for AI agents
- Anthropic: Skill authoring best practices
- agentskills.io: Best practices for skill creators
- redhat-et/rhdp-rca-plugin
- databricks/databricks-agent-skills
- Where sources differ

## Red Hat: Building skills for AI agents
https://next.redhat.com/2026/07/28/building-skills-for-ai-agents-pitfalls-and-best-practices/

Used for: capability versus preference skills, skill-count overhead (1 to 3 per task), distractor skills, vague descriptions, the 500-line limit, gating L3 resources, scripts over inference (26% cost cut), harness portability, patch-release stability, security hygiene, submodules pinned to commits, evaluation on three dimensions (functional viability, directive compliance, operational efficiency), 60/40 train/test split for trigger queries, CI quality gates on token use.

Its L1, L2 and L3 labels map to: L1 is name and description (always loaded), L2 is the `SKILL.md` body (loaded on trigger), L3 is bundled files (loaded on demand).

## Anthropic: Skill authoring best practices
https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices

Used for: frontmatter limits (`name` 64 chars, lowercase letters, digits and hyphens, no reserved words; `description` 1,024 chars, no XML tags), third-person descriptions, naming conventions, degrees of freedom, one-level-deep references, table of contents in files over 100 lines, workflows and checklists, validation loops, plan-validate-execute, "solve, don't defer" in scripts, no voodoo constants, fully qualified MCP tool names, forward-slash paths, evaluation-driven development, the Claude A / Claude B iteration method, testing with several model sizes.

## agentskills.io: Best practices for skill creators
https://agentskills.io/skill-creation/best-practices

Used for: grounding skills in real expertise, synthesising from project artifacts, refining from execution traces, "add what the agent lacks", coherent-unit scoping, moderate detail, the specification limit of 500 lines and 5,000 tokens, telling the agent when to load each reference, procedures over declarations, gotchas sections, output templates, checklists, validation loops, bundling scripts the agent keeps reinventing.

Related pages on the same site, linked from it:
- Evaluating skill output quality: https://agentskills.io/skill-creation/evaluating-skills
- Optimizing skill descriptions: https://agentskills.io/skill-creation/optimizing-descriptions
- Using scripts in skills: https://agentskills.io/skill-creation/using-scripts
- Specification: https://agentskills.io/specification

## redhat-et/rhdp-rca-plugin
https://github.com/redhat-et/rhdp-rca-plugin

Used for: a worked repo layout to copy. `skills/` with one directory per skill, a `template-skill`, `.claude-plugin/` for the marketplace, `docs/` with a spec summary and `CONTRIBUTING.md`, `.pre-commit-config.yaml`, `CLAUDE.md`, `.claude/settings.example.json` copied to an untracked `settings.local.json`, Apache-2.0 license. Skill directory names are lowercase and hyphenated. Slash commands are namespaced by plugin.

## databricks/databricks-agent-skills
https://github.com/databricks/databricks-agent-skills

Used for: the generated-artifacts pattern. One source of truth (`metaplugin/plugin.meta.json`) generates per-harness plugin manifests, catalogs and a `manifest.json` through `scripts/skills.py`. A CI workflow regenerates and commits them. Skills have an optional `references/` folder. An `experimental/` area is kept out of default installs. Release tags map 1:1 to published versions. The hub vendors it as a pinned submodule under `vendor/`.

## Where sources differ
| Topic | Difference | Rule used |
|---|---|---|
| Description length | Red Hat gives no limit. Anthropic gives 1,024 chars. | 1,024 |
| Size | Anthropic says 500 lines. agentskills.io adds 5,000 tokens. | Both |
| Names | Anthropic recommends gerunds and allows nouns. | Gerund or noun phrase, one pattern per domain |
| Portability | Red Hat says duplicate or dual-manifest. Databricks generates per target. | Generate per target from one source |
