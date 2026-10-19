"""Validate every skill under skills/. Exits non-zero on any error.

Rules come from docs/CONTRIBUTING.md and skills/authoring/writing-agent-skills.
vendor/ is never scanned: third-party skills are not held to hub rules.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import skilllib
from skilllib import MAX_BODY_LINES, MAX_BODY_TOKENS

NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
RESERVED = ("claude", "anthropic")
XML_TAG_RE = re.compile(r"</?[A-Za-z][^>]*>")
MD_LINK_RE = re.compile(r"\]\(([^)#\s]+)(?:#[^)]*)?\)")
FIRST_PERSON_RE = re.compile(r"^(i|you|we)\b|\b(i can|you can|i will|i help)\b", re.IGNORECASE)
KNOWN_KEYS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
MIN_EVALS = 3


def _local_links(text: str) -> list[str]:
    return [m for m in MD_LINK_RE.findall(text) if "://" not in m and not m.startswith("mailto:")]


def check_skill(skill_dir: Path, seen: dict[str, Path]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    rel = skill_dir.relative_to(skilllib.ROOT)

    try:
        skill = skilllib.load(skill_dir)
    except ValueError as exc:
        return [f"{rel}/SKILL.md: {exc}"], warnings

    meta, body = skill.meta, skill.body
    name, desc = skill.name, str(meta.get("description", ""))

    # frontmatter
    if not name:
        errors.append(f"{rel}: missing name")
    else:
        if len(name) > 64 or not NAME_RE.match(name):
            errors.append(f"{rel}: name '{name}' must be <=64 chars, lowercase letters/digits/hyphens")
        if any(word in name for word in RESERVED):
            errors.append(f"{rel}: name '{name}' contains a reserved word")
        if name != skill_dir.name:
            errors.append(f"{rel}: name '{name}' must equal directory name '{skill_dir.name}'")
        if name in seen:
            errors.append(f"{rel}: name '{name}' already used by {seen[name].relative_to(skilllib.ROOT)}")
        seen.setdefault(name, skill_dir)
    if not desc.strip():
        errors.append(f"{rel}: description is empty")
    if len(desc) > 1024:
        errors.append(f"{rel}: description is {len(desc)} chars (max 1024)")
    if XML_TAG_RE.search(desc) or XML_TAG_RE.search(name):
        errors.append(f"{rel}: name/description must not contain XML tags")
    if FIRST_PERSON_RE.search(desc):
        errors.append(f"{rel}: description must be third person")
    if "use when" not in desc.lower():
        warnings.append(f"{rel}: description should say when to use the skill ('Use when ...')")
    for key in set(meta) - KNOWN_KEYS:
        errors.append(f"{rel}: unknown frontmatter key '{key}' (custom keys go under metadata:)")
    for key, value in (meta.get("metadata") or {}).items():
        if not isinstance(value, str):
            errors.append(f"{rel}: metadata.{key} must be a string (quote it)")

    order = (meta.get("metadata") or {}).get("order")
    if order is not None and not str(order).isdigit():
        errors.append(f"{rel}: metadata.order must be a non-negative integer string, got '{order}'")

    # size
    lines =len(body.splitlines())
    tokens = skilllib.estimate_tokens(body)
    if lines > MAX_BODY_LINES:
        errors.append(f"{rel}: SKILL.md body is {lines} lines (max {MAX_BODY_LINES})")
    if tokens > MAX_BODY_TOKENS:
        errors.append(f"{rel}: SKILL.md body is ~{tokens} tokens (max {MAX_BODY_TOKENS})")

    # references: exist, one level deep, no backslash paths
    if "\\" in "".join(_local_links(body)):
        errors.append(f"{rel}: use forward slashes in paths")
    linked = set()
    for link in _local_links(body):
        target = (skill_dir / link).resolve()
        linked.add(target)
        if not target.exists():
            errors.append(f"{rel}: SKILL.md links to missing file '{link}'")
    refs_dir = skill_dir / "references"
    for ref in sorted(refs_dir.glob("**/*.md")) if refs_dir.is_dir() else []:
        ref_rel = ref.relative_to(skilllib.ROOT)
        ref_text = ref.read_text(encoding="utf-8")
        if ref.resolve() not in linked:
            warnings.append(f"{ref_rel}: not linked from SKILL.md")
        if len(ref_text.splitlines()) > 100 and not re.search(r"^## Contents\b", ref_text, re.MULTILINE):
            errors.append(f"{ref_rel}: over 100 lines, needs a '## Contents' section")
        for link in _local_links(ref_text):
            if link.endswith(".md"):
                errors.append(f"{ref_rel}: links to '{link}'; references must be one level deep")

    # evals
    evals_file = skill_dir / "evals" / "evals.json"
    if not evals_file.is_file():
        errors.append(f"{rel}: missing evals/evals.json")
    else:
        try:
            cases = json.loads(evals_file.read_text(encoding="utf-8"))
            if not isinstance(cases, list) or len(cases) < MIN_EVALS:
                errors.append(f"{rel}: evals/evals.json needs at least {MIN_EVALS} cases")
            else:
                for i, case in enumerate(cases):
                    for key in ("id", "query", "expected_behavior"):
                        if not case.get(key):
                            errors.append(f"{rel}: eval #{i} missing '{key}'")
        except json.JSONDecodeError as exc:
            errors.append(f"{rel}: evals/evals.json is invalid JSON: {exc}")

    return errors, warnings


def main() -> int:
    domains_file = skilllib.SKILLS_DIR / "domains.json"
    domains = json.loads(domains_file.read_text(encoding="utf-8")) if domains_file.exists() else {}
    all_errors: list[str] = []
    all_warnings: list[str] = []
    seen: dict[str, Path] = {}

    skill_dirs = skilllib.discover()
    for skill_dir in skill_dirs:
        if skill_dir.parent.name not in domains:
            all_errors.append(f"{skill_dir.parent.name}: domain missing from skills/domains.json")
        errors, warnings = check_skill(skill_dir, seen)
        all_errors += errors
        all_warnings += warnings

    for line in all_warnings:
        print(f"warning: {line}")
    for line in all_errors:
        print(f"error: {line}")
    print(f"{len(skill_dirs)} skill(s) checked, {len(all_errors)} error(s), {len(all_warnings)} warning(s)")
    return 1 if all_errors else 0


if __name__ == "__main__":
    sys.exit(main())
