"""Validate every skill under skills/. Exits non-zero on any error.

Rules come from docs/CONTRIBUTING.md and skills/authoring/writing-agent-skills.
vendor/ is never scanned: third-party skills are not held to hub rules.
Malformed input must produce findings for that skill and never stop the run.
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


def _rel(path: Path) -> Path:
    """Path relative to the repo root for messages; the path itself when it is elsewhere."""
    try:
        return path.relative_to(skilllib.ROOT)
    except ValueError:
        return path


def _local_links(text: str) -> list[str]:
    return [m for m in MD_LINK_RE.findall(text) if "://" not in m and not m.startswith("mailto:")]


def check_name(skill: Skill, rel: Path, seen: dict[str, Path]) -> list[str]:
    raw = skill.meta.get("name")
    if raw is None or raw == "":
        return [f"{rel}: missing name"]
    if not isinstance(raw, str):
        return [f"{rel}: name must be a string, got {type(raw).__name__} ({raw!r}); quote it"]
    errors: list[str] = []
    if len(raw) > 64 or not NAME_RE.match(raw):
        errors.append(f"{rel}: name '{raw}' must be <=64 chars, lowercase letters/digits/hyphens")
    if any(word in raw for word in RESERVED):
        errors.append(f"{rel}: name '{raw}' contains a reserved word")
    if raw != skill.path.name:
        errors.append(f"{rel}: name '{raw}' must equal directory name '{skill.path.name}'")
    if raw in seen:
        errors.append(f"{rel}: name '{raw}' already used by {_rel(seen[raw])}")
    seen.setdefault(raw, skill.path)
    return errors


def check_description(skill: Skill, rel: Path) -> Findings:
    raw = skill.meta.get("description")
    if raw is None or raw == "":
        return [f"{rel}: description is empty"], []
    if not isinstance(raw, str):
        return [f"{rel}: description must be a string, got {type(raw).__name__}; quote it"], []
    errors: list[str] = []
    warnings: list[str] = []
    if not raw.strip():
        errors.append(f"{rel}: description is empty")
    if len(raw) > 1024:
        errors.append(f"{rel}: description is {len(raw)} chars (max 1024)")
    if XML_TAG_RE.search(raw) or XML_TAG_RE.search(str(skill.meta.get("name", ""))):
        errors.append(f"{rel}: name/description must not contain XML tags")
    if FIRST_PERSON_RE.search(raw):
        errors.append(f"{rel}: description must be third person")
    if "use when" not in raw.lower():
        warnings.append(f"{rel}: description should say when to use the skill ('Use when ...')")
    return errors, warnings


def check_metadata(skill: Skill, rel: Path) -> list[str]:
    errors = [
        f"{rel}: unknown frontmatter key '{key}' (custom keys go under metadata:)"
        for key in sorted(set(skill.meta) - KNOWN_KEYS, key=str)
    ]
    metadata = skill.meta.get("metadata")
    if metadata is None:
        return errors
    if not isinstance(metadata, dict):
        return errors + [f"{rel}: metadata must be a mapping, got {type(metadata).__name__}"]
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


def _check_links(text: str, base: Path, root: Path, label: Path) -> tuple[list[str], set[Path]]:
    """Check local links resolved from `base`: forward slashes, inside the skill directory, and existing."""
    errors: list[str] = []
    resolved: set[Path] = set()
    for link in _local_links(text):
        if "\\" in link:
            errors.append(f"{label}: use forward slashes in paths ('{link}')")
            continue
        target = (base / link).resolve()
        resolved.add(target)
        if not target.is_relative_to(root):
            errors.append(f"{label}: link '{link}' points outside the skill directory, so it will be missing once packaged")
        elif not target.exists():
            errors.append(f"{label}: links to missing file '{link}'")
    return errors, resolved


def check_references(skill: Skill, rel: Path) -> Findings:
    """Links resolve inside the skill, references are one level deep, long files have a contents list."""
    root = skill.path.resolve()
    errors, linked = _check_links(skill.body, root, root, rel / "SKILL.md")
    warnings: list[str] = []

    refs_dir = skill.path / "references"
    for ref in sorted(refs_dir.glob("**/*.md")) if refs_dir.is_dir() else []:
        ref_rel = _rel(ref)
        ref_text = ref.read_text(encoding="utf-8")
        if ref.resolve() not in linked:
            warnings.append(f"{ref_rel}: not linked from SKILL.md")
        if len(ref_text.splitlines()) > 100 and not re.search(r"^## Contents\b", ref_text, re.MULTILINE):
            errors.append(f"{ref_rel}: over 100 lines, needs a '## Contents' section")
        link_errors, _ = _check_links(ref_text, ref.parent.resolve(), root, ref_rel)
        errors += link_errors
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
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return [f"{rel}: evals/evals.json is invalid: {exc}"]
    if not isinstance(cases, list) or len(cases) < MIN_EVALS:
        return [f"{rel}: evals/evals.json needs at least {MIN_EVALS} cases"]
    errors: list[str] = []
    for i, case in enumerate(cases):
        if not isinstance(case, dict):
            errors.append(f"{rel}: eval #{i} must be an object, got {type(case).__name__}")
            continue
        errors += [f"{rel}: eval #{i} missing '{key}'" for key in ("id", "query", "expected_behavior") if not case.get(key)]
    return errors


def check_skill(skill_dir: Path, seen: dict[str, Path]) -> Findings:
    """Run every validator for one skill and aggregate their findings. Never raises on bad skill input."""
    rel = _rel(skill_dir)
    try:
        skill = skilllib.load(skill_dir)
    except (ValueError, OSError) as exc:
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
