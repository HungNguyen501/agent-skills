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
from skilllib import MAX_BODY_LINES, MAX_BODY_TOKENS, Skill

NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
RESERVED = ("claude", "anthropic")
XML_TAG_RE = re.compile(r"</?[A-Za-z][^>]*>")
MD_LINK_RE = re.compile(r"\]\(([^)#\s]+)(?:#[^)]*)?\)")
FIRST_PERSON_RE = re.compile(r"^(i|you|we)\b|\b(i can|you can|i will|i help)\b", re.IGNORECASE)
KNOWN_KEYS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
MIN_EVALS = 3

Findings = tuple[list[str], list[str]]  # (errors, warnings)


def _local_links(text: str) -> list[str]:
    return [m for m in MD_LINK_RE.findall(text) if "://" not in m and not m.startswith("mailto:")]


def check_name(skill: Skill, rel: Path, seen: dict[str, Path]) -> list[str]:
    errors: list[str] = []
    name = skill.name
    if not name:
        return [f"{rel}: missing name"]
    if len(name) > 64 or not NAME_RE.match(name):
        errors.append(f"{rel}: name '{name}' must be <=64 chars, lowercase letters/digits/hyphens")
    if any(word in name for word in RESERVED):
        errors.append(f"{rel}: name '{name}' contains a reserved word")
    if name != skill.path.name:
        errors.append(f"{rel}: name '{name}' must equal directory name '{skill.path.name}'")
    if name in seen:
        errors.append(f"{rel}: name '{name}' already used by {seen[name].relative_to(skilllib.ROOT)}")
    seen.setdefault(name, skill.path)
    return errors


def check_description(skill: Skill, rel: Path) -> Findings:
    errors: list[str] = []
    warnings: list[str] = []
    desc = str(skill.meta.get("description", ""))
    if not desc.strip():
        errors.append(f"{rel}: description is empty")
    if len(desc) > 1024:
        errors.append(f"{rel}: description is {len(desc)} chars (max 1024)")
    if XML_TAG_RE.search(desc) or XML_TAG_RE.search(skill.name):
        errors.append(f"{rel}: name/description must not contain XML tags")
    if FIRST_PERSON_RE.search(desc):
        errors.append(f"{rel}: description must be third person")
    if "use when" not in desc.lower():
        warnings.append(f"{rel}: description should say when to use the skill ('Use when ...')")
    return errors, warnings


def check_metadata(skill: Skill, rel: Path) -> list[str]:
    errors = [
        f"{rel}: unknown frontmatter key '{key}' (custom keys go under metadata:)"
        for key in sorted(set(skill.meta) - KNOWN_KEYS)
    ]
    metadata = skill.meta.get("metadata") or {}
    errors += [f"{rel}: metadata.{key} must be a string (quote it)" for key, value in metadata.items() if not isinstance(value, str)]
    order = metadata.get("order")
    if order is not None and not str(order).isdigit():
        errors.append(f"{rel}: metadata.order must be a non-negative integer string, got '{order}'")
    return errors


def check_size(skill: Skill, rel: Path) -> list[str]:
    errors: list[str] = []
    lines = len(skill.body.splitlines())
    tokens = skilllib.estimate_tokens(skill.body)
    if lines > MAX_BODY_LINES:
        errors.append(f"{rel}: SKILL.md body is {lines} lines (max {MAX_BODY_LINES})")
    if tokens > MAX_BODY_TOKENS:
        errors.append(f"{rel}: SKILL.md body is ~{tokens} tokens (max {MAX_BODY_TOKENS})")
    return errors


def check_references(skill: Skill, rel: Path) -> Findings:
    """Links resolve, references are one level deep, long files have a contents list."""
    errors: list[str] = []
    warnings: list[str] = []
    links = _local_links(skill.body)
    if any("\\" in link for link in links):
        errors.append(f"{rel}: use forward slashes in paths")
    linked = set()
    for link in links:
        target = (skill.path / link).resolve()
        linked.add(target)
        if not target.exists():
            errors.append(f"{rel}: SKILL.md links to missing file '{link}'")

    refs_dir = skill.path / "references"
    for ref in sorted(refs_dir.glob("**/*.md")) if refs_dir.is_dir() else []:
        ref_rel = ref.relative_to(skilllib.ROOT)
        ref_text = ref.read_text(encoding="utf-8")
        if ref.resolve() not in linked:
            warnings.append(f"{ref_rel}: not linked from SKILL.md")
        if len(ref_text.splitlines()) > 100 and not re.search(r"^## Contents\b", ref_text, re.MULTILINE):
            errors.append(f"{ref_rel}: over 100 lines, needs a '## Contents' section")
        errors += [
            f"{ref_rel}: links to '{link}'; references must be one level deep"
            for link in _local_links(ref_text)
            if link.endswith(".md")
        ]
    return errors, warnings


def check_evals(skill: Skill, rel: Path) -> list[str]:
    evals_file = skill.path / "evals" / "evals.json"
    if not evals_file.is_file():
        return [f"{rel}: missing evals/evals.json"]
    try:
        cases = json.loads(evals_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"{rel}: evals/evals.json is invalid JSON: {exc}"]
    if not isinstance(cases, list) or len(cases) < MIN_EVALS:
        return [f"{rel}: evals/evals.json needs at least {MIN_EVALS} cases"]
    return [
        f"{rel}: eval #{i} missing '{key}'"
        for i, case in enumerate(cases)
        for key in ("id", "query", "expected_behavior")
        if not case.get(key)
    ]


def check_skill(skill_dir: Path, seen: dict[str, Path]) -> Findings:
    """Run every validator for one skill and aggregate their findings."""
    rel = skill_dir.relative_to(skilllib.ROOT)
    try:
        skill = skilllib.load(skill_dir)
    except ValueError as exc:
        return [f"{rel}/SKILL.md: {exc}"], []

    desc_errors, desc_warnings = check_description(skill, rel)
    ref_errors, ref_warnings = check_references(skill, rel)
    errors = (
        check_name(skill, rel, seen)
        + desc_errors
        + check_metadata(skill, rel)
        + check_size(skill, rel)
        + ref_errors
        + check_evals(skill, rel)
    )
    return errors, desc_warnings + ref_warnings


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
