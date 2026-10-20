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
from urllib.parse import unquote

import skilllib
import skillpkg
from skilllib import MAX_BODY_LINES, MAX_BODY_TOKENS, Skill

NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
RESERVED = ("claude", "anthropic")
XML_TAG_RE = re.compile(r"</?[A-Za-z][^>]*>")
MD_LINK_START_RE = re.compile(r"\]\(\s*")  # where the destination of an inline link [text](dest ...) starts
# Where the destination of a reference definition [ref]: dest "title" starts. Up to three leading spaces, as in CommonMark.
MD_REF_DEF_START_RE = re.compile(r"^ {0,3}\[[^\]]+\]:[ \t]*", re.MULTILINE)
ESCAPABLE = frozenset("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")  # a backslash before one of these is an escape
FIRST_PERSON_RE = re.compile(r"^(i|you|we)\b|\b(i can|you can|i will|i help)\b", re.IGNORECASE)
KNOWN_KEYS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
MIN_EVALS = 3
ORDER_RE = re.compile(r"[0-9]+")  # ASCII digits only: str.isdigit() accepts characters such as "²" that int() rejects

Findings = tuple[list[str], list[str]]  # (errors, warnings)


def _rel(path: Path) -> Path:
    """Path relative to the repo root for messages; the path itself when it is elsewhere."""
    try:
        return path.relative_to(skilllib.ROOT)
    except ValueError:
        return path


def _read_destination(text: str, start: int) -> str:
    """Read a link destination that starts at `start`, following CommonMark: `<...>` (spaces allowed) or a run of
    non-space characters with balanced parentheses, and backslash escapes before punctuation. Returns "" if invalid."""
    angle = text.startswith("<", start)
    i, depth, out = (start + 1 if angle else start), 0, []
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text) and text[i + 1] in ESCAPABLE:
            out.append(text[i + 1])
            i += 2
            continue
        if angle:
            if ch == ">":
                return "".join(out)
            if ch in "<\n":
                return ""
        elif ch.isspace() or (ch == ")" and depth == 0):
            break
        elif ch in "()":
            depth += 1 if ch == "(" else -1
        out.append(ch)
        i += 1
    return "" if angle else "".join(out)


def _local_links(text: str) -> list[str]:
    """Local file destinations of inline links and reference definitions. Web and mail links, and links that are
    only a fragment, are skipped. The fragment is removed first and the path is then percent-decoded, so
    `api%20guide.md#x` is the file `api guide.md`.

    Every definition counts, used or not, so a broken one cannot hide behind [text][ref]. This does not skip fenced code blocks.
    """
    raw = [_read_destination(text, m.end()) for pattern in (MD_LINK_START_RE, MD_REF_DEF_START_RE) for m in pattern.finditer(text)]
    local = [r for r in raw if r and "://" not in r and not r.startswith("mailto:")]
    return [path for path in (unquote(r.split("#", 1)[0]) for r in local) if path]


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
    # Non-string values are already reported above, so only strings are checked here.
    if isinstance(order, str) and not ORDER_RE.fullmatch(order):
        errors.append(f"{rel}: metadata.order must be a non-negative integer string of ASCII digits, got '{order}'")
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
        try:
            target = (base / link).resolve()
        except (OSError, ValueError, RuntimeError) as exc:  # RuntimeError: symlink loop on Python 3.11/3.12
            errors.append(f"{label}: link '{link}' cannot be resolved ({exc.__class__.__name__}); check for a symlink loop")
            continue
        resolved.add(target)
        if not target.is_relative_to(root):
            errors.append(f"{label}: link '{link}' points outside the skill directory, so it will be missing once packaged")
        elif set(target.relative_to(root).parts) & set(skillpkg.PACKAGE_IGNORE):
            ignored = "/".join(skillpkg.PACKAGE_IGNORE)
            errors.append(f"{label}: link '{link}' points into {ignored}, which are not packaged, so it will be missing once packaged")
        elif not target.exists():
            errors.append(f"{label}: links to missing file '{link}'")
    return errors, resolved


def check_references(skill: Skill, rel: Path) -> Findings:
    """Links resolve inside the skill, references are one level deep, long files have a contents list."""
    root = skill.path.resolve()
    errors, linked = _check_links(skill.body, root, root, rel / "SKILL.md")
    warnings: list[str] = []

    # only what packaging ships: fixtures under evals/ or __pycache__/ and symlinks (reported separately) are not read
    for ref in skillpkg.packaged_files(skill.path / "references", ".md"):
        ref_rel = _rel(ref)
        try:
            ref_resolved = ref.resolve()
            ref_text = ref.read_text(encoding="utf-8")
        except (OSError, ValueError, RuntimeError) as exc:  # ValueError includes UnicodeDecodeError
            errors.append(f"{ref_rel}: cannot read reference ({exc.__class__.__name__}): {exc}")
            continue
        if ref_resolved not in linked:
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


def check_symlinks(skill: Skill) -> list[str]:
    """Skills must not contain symlinks in anything that gets packaged: copying would follow them, so a link
    can pull in files from outside the skill or fail on a loop. The walk is skillpkg.find_symlinks, which skips
    the same names build.py leaves out, so a link is rejected exactly when packaging would follow it."""
    return [
        f"{_rel(path)}: symlinks are not allowed in skills (packaging follows them)"
        for path in skillpkg.find_symlinks(skill.path)
    ]


def check_evals(skill: Skill, rel: Path) -> list[str]:
    evals_file = skill.path / "evals" / "evals.json"
    if not evals_file.is_file():
        return [f"{rel}: missing evals/evals.json"]
    try:
        cases = json.loads(evals_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError) as exc:
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


def check_roots(skill_dir: Path) -> list[str]:
    """Reject a symlinked skill or domain directory. os.walk in check_symlinks never inspects its own
    starting directory and packaging follows links, so this runs before anything is read through them."""
    return [f"{_rel(path)}: {label} must not be a symlink (packaging follows it)" for path, label in skillpkg.root_links(skill_dir)]


def check_loaded(skill: Skill, rel: Path, seen: dict[str, Path]) -> Findings:
    """Run every validator on a loaded skill and aggregate their findings."""
    desc_errors, desc_warnings = check_description(skill, rel)
    ref_errors, ref_warnings = check_references(skill, rel)
    errors = (
        check_name(skill, rel, seen)
        + desc_errors
        + check_metadata(skill, rel)
        + check_size(skill, rel)
        + ref_errors
        + check_symlinks(skill)
        + check_evals(skill, rel)
    )
    return errors, desc_warnings + ref_warnings


def check_skill(skill_dir: Path, seen: dict[str, Path]) -> Findings:
    """Load one skill and validate it. Never raises on bad skill input, so one skill cannot stop the run."""
    rel = _rel(skill_dir)
    root_errors = check_roots(skill_dir)
    if root_errors:
        return root_errors, []
    try:
        skill = skilllib.load(skill_dir)
    except (ValueError, OSError) as exc:
        return [f"{rel}/SKILL.md: {exc}"], []
    try:
        return check_loaded(skill, rel, seen)
    except (ValueError, OSError, RuntimeError) as exc:  # last resort: an unreadable file or symlink loop
        return [f"{rel}: validation aborted ({exc.__class__.__name__}): {exc}"], []


def main() -> int:
    all_errors: list[str] = []
    all_warnings: list[str] = []
    seen: dict[str, Path] = {}
    try:
        domains: dict[str, str] | None = skilllib.load_domains()
    except ValueError as exc:
        all_errors.append(f"skills/{exc}")
        domains = None  # the registry itself is the finding; do not add a missing-domain error to every skill

    skill_dirs = skilllib.discover()
    for skill_dir in skill_dirs:
        if domains is not None and skill_dir.parent.name not in domains:
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
