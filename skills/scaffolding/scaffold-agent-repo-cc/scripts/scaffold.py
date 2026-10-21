# GENERATED from scripts/templates/scaffold.py.tmpl by scripts/build.py. Edit the template, not this file.
"""Installs hub skills into a destination repo in the Claude Code layout.

Usage: scaffold.py --hub HUB_DIR --dest DEST_DIR --skills NAME[,NAME...] [--dry-run] [--force]

Resolves each name to HUB_DIR/skills/<domain>/<name>, copies it to DEST_DIR/.claude/skills/<name>/ without evals/ and
caches, writes DEST_DIR/CLAUDE.md if absent, and records what was installed in
DEST_DIR/.claude/skills/.hub-skills.json.
Also writes .claude/settings.example.json and ignores .claude/settings.local.json.
Nothing is written when any name is unknown or any destination skill exists (unless --force). A failure part way
restores the previous state. Exit status is 1 on error.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

# One folder name: no separators and no leading dot, so a manifest entry can never point outside the skills folder.
SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")  # used with fullmatch, because "$" would accept a trailing newline
# Files besides the instruction file and the manifest that an install may write, snapshotted so a failure can undo them.
EXTRA_FILES = (".claude/settings.example.json", ".gitignore")
SKILLS_DIR = ".claude/skills"
INSTRUCTIONS = "CLAUDE.md"
# git rev-parse reads a local file and takes milliseconds. This only stops a hung git from blocking the install.
GIT_TIMEOUT_SECONDS = 30
# Names left out of copies: evals are test fixtures, not agent-facing content.
IGNORE = shutil.ignore_patterns("evals", "__pycache__")
INSTRUCTIONS_TEMPLATE = """# {project}

<!-- Describe the project, its commands and its rules here. Keep this file short. -->

## Skills

Installed from the agent-skills hub (see `{skills_dir}/.hub-skills.json`):

{skill_lines}
"""

# Local overrides must never be committed; only the example file is.
GITIGNORE_LINE = ".claude/settings.local.json"
SETTINGS_EXAMPLE = {"permissions": {"allow": [], "deny": []}}


def write_claude_extras(dest):
    """Writes .claude/settings.example.json if absent and ignores settings.local.json in .gitignore."""
    example = dest / ".claude" / "settings.example.json"
    if not present(example):
        write_atomic(example, (json.dumps(SETTINGS_EXAMPLE, indent=2) + "\n").encode("utf-8"))
    gitignore = dest / ".gitignore"
    text = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    if GITIGNORE_LINE not in text.splitlines():
        write_atomic(gitignore, (text + ("" if text.endswith("\n") or not text else "\n") + GITIGNORE_LINE + "\n").encode("utf-8"))


def find_skills(hub):
    """Maps skill name to directory for every skills/<domain>/<name>/SKILL.md under the hub.

    A skill reached through a symlinked domain folder, or one that resolves outside the hub's skills folder, is left out:
    the script refuses to copy files that live elsewhere.
    """
    root = (hub / "skills").resolve()
    found = {}
    for path in sorted((hub / "skills").glob("*/*/SKILL.md")):
        skill = path.parent
        if skill.parent.is_symlink() or not skill.resolve().is_relative_to(root):
            continue
        found[skill.name] = skill
    return found


def describe(skill_dir):
    """Returns the one-line description from a SKILL.md frontmatter, or an empty string."""
    for line in (skill_dir / "SKILL.md").read_text(encoding="utf-8").splitlines():
        if line.startswith("description:"):
            return line.split(":", 1)[1].strip()[:120]
    return ""


def hub_revision(hub):
    """Returns the hub's git SHA, or 'unknown' when the hub is not a git checkout or git does not answer in time."""
    try:
        out = subprocess.run(
            ["git", "-C", str(hub), "rev-parse", "HEAD"], capture_output=True, text=True, check=True, timeout=GIT_TIMEOUT_SECONDS
        )
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return "unknown"


def has_symlink(path):
    """True when `path` or anything under it is a symlink, which would copy files from outside the skill."""
    return path.is_symlink() or any(p.is_symlink() for p in path.rglob("*"))


def plan(hub, dest, names, force):
    """Returns (errors, actions) without touching the destination."""
    available = find_skills(hub)
    errors, actions = [], []
    for name in names:
        target = dest / SKILLS_DIR / name
        if name not in available:
            errors.append(f"Skill `{name}` not found. Available: {', '.join(available) or '(none)'}")
        elif has_symlink(available[name]):
            errors.append(f"Skill `{name}` contains a symlink; refusing to copy")
        elif target.is_symlink() or (target.exists() and not target.is_dir()):
            errors.append(f"{target} exists and is not a plain folder (a file or a link); remove it by hand first")
        elif target.exists() and not force:
            errors.append(f"{target} exists; pass --force to replace it")
        else:
            actions.append((name, available[name], target))
    return errors, actions


def parse_args(argv):
    """Parses the command line."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--hub", type=Path, required=True, help="path to the agent-skills hub checkout")
    ap.add_argument("--dest", type=Path, required=True, help="destination repo")
    ap.add_argument("--skills", required=True, help="comma-separated hub skill names")
    ap.add_argument("--dry-run", action="store_true", help="print the plan and write nothing")
    ap.add_argument("--force", action="store_true", help="replace skills that already exist in the destination")
    return ap.parse_args(argv)


def load_manifest(path):
    """Returns the manifest at `path`, or an empty one. Raises ValueError when the file is not a valid manifest."""
    if not path.exists():
        return {"skills": []}
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not valid JSON ({exc}). Fix or delete it, then rerun.") from exc
    except OSError as exc:  # a folder at this path, or a file that cannot be read
        raise ValueError(f"{path} cannot be read ({exc}). Fix it or delete it, then rerun.") from exc
    # Everything later code indexes or joins into a path is checked here, so a bad file stops the run before any write.
    skills = manifest.get("skills", []) if isinstance(manifest, dict) else None
    revisions = manifest.get("revisions", {}) if isinstance(manifest, dict) else None
    if skills is None or not isinstance(skills, list) or not all(isinstance(n, str) and SAFE_NAME.fullmatch(n) for n in skills):
        raise ValueError(f"{path}: `skills` must be a list of skill folder names. Fix or delete the file, then rerun.")
    if not isinstance(revisions, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in revisions.items()):
        raise ValueError(f"{path}: `revisions` must map skill names to revision strings. Fix or delete the file, then rerun.")
    if not isinstance(manifest.get("hub_revision", ""), str):
        raise ValueError(f"{path}: `hub_revision` must be a string. Fix or delete the file, then rerun.")
    manifest.setdefault("skills", [])
    return manifest


def present(path):
    """True when `path` exists or is a link, dangling ones included, so a link is never written through."""
    return path.exists() or path.is_symlink()


def layout_errors(dest):
    """Errors for install paths that are links or not folders: writing through or over them would leave the destination."""
    errors, path = [], dest
    for part in Path(SKILLS_DIR).parts:
        path = path / part
        if path.is_symlink():
            errors.append(f"{path} is a symlink; refusing to install through it")
        elif path.exists() and not path.is_dir():
            errors.append(f"{path} exists and is not a directory")
    if (path / ".hub-skills.json").is_symlink():
        errors.append(f"{path / '.hub-skills.json'} is a symlink; refusing to replace it with a regular file")
    errors += [f"{dest / extra} is a symlink; refusing to write through it" for extra in EXTRA_FILES if (dest / extra).is_symlink()]
    return errors


def snapshot(paths):
    """Remembers each plain file's bytes, or None when the path is absent, so a failed run can put them back.

    Links and folders are left out: this script never writes through a link and keeps an existing instruction entry
    as it is, so rollback must not touch them either.
    """
    saved = {}
    for path in paths:
        if not path.is_symlink() and not path.is_dir():
            saved[path] = path.read_bytes() if path.is_file() else None
    return saved


def restore(saved):
    """Puts back what `snapshot` saw: rewrites changed files atomically and removes the ones the run created.

    A failure to restore one file is reported and does not stop the others, and never replaces the original error.
    """
    for path, content in saved.items():
        try:
            if content is None:
                path.unlink(missing_ok=True)
            elif not path.is_file() or path.read_bytes() != content:
                write_atomic(path, content)
        except OSError as exc:
            print(f"warning: could not restore {path}: {exc}", file=sys.stderr)


def put_back(backup, target):
    """Renames a backup back to `target`. A failure is reported with the backup's location, not raised."""
    try:
        backup.rename(target)
    except OSError as exc:
        print(f"warning: could not restore {target} from {backup}: {exc}. The previous copy stays at {backup}.", file=sys.stderr)


def roll_back(done):
    """Undoes `swap`: removes the skills it installed and puts the previous ones back.

    Never raises, because it runs while another error is being handled. A step that fails is reported and the rest still run.
    """
    for target, backup in reversed(done):
        try:
            shutil.rmtree(target)
        except FileNotFoundError:
            pass
        except OSError as exc:
            print(f"warning: could not remove {target}: {exc}.", file=sys.stderr)
            if backup:
                print(f"warning: the previous copy stays at {backup}.", file=sys.stderr)
            continue
        if backup:
            put_back(backup, target)


def swap(staged):
    """Swaps each staged skill in, keeping the old one as a backup. Returns [(target, backup or None)].

    On any failure it undoes the swaps already made and re-raises.
    """
    done = []
    try:
        for staging, target in staged:
            backup = target.with_name(f".{target.name}.old-{uuid.uuid4().hex}") if target.exists() else None
            if backup:
                target.rename(backup)
            try:
                staging.rename(target)
            except Exception:
                if backup:
                    put_back(backup, target)
                raise
            done.append((target, backup))
    except Exception:
        roll_back(done)
        raise
    return done


def swap_in(actions, skills_dir):
    """Copies each skill into a private staging folder, then swaps it in. Returns what `swap` returns.

    Staging folders are always removed. A failure leaves the skills that were already installed as they were.
    """
    skills_dir.mkdir(parents=True, exist_ok=True)
    staged = []
    try:
        for name, src, target in actions:
            # mkdtemp gives a name no other process or user folder can hold, so cleanup only touches folders made here.
            staging = Path(tempfile.mkdtemp(prefix=f".{name}-", dir=skills_dir))
            staged.append((staging, target))
            shutil.copytree(src, staging, ignore=IGNORE, dirs_exist_ok=True)
        return swap(staged)
    finally:
        for staging, _ in staged:
            shutil.rmtree(staging, ignore_errors=True)


def commit(done):
    """Deletes the backups once the whole install, metadata included, has succeeded. A backup that stays is reported."""
    for _, backup in done:
        if backup:
            try:
                shutil.rmtree(backup)
            except OSError as exc:
                print(f"warning: could not remove the old copy {backup}: {exc}", file=sys.stderr)


def write_atomic(path, content):
    """Writes bytes so a failed write never leaves a half-written file at `path` and never truncates the original.

    The temporary file is created exclusively by mkstemp, so a file or link a user already has next to `path` is never
    truncated, followed or deleted.
    """
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}-", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
        # mkstemp creates the file 0600. Keep the file's mode, or use the usual 0644 for a new one.
        os.chmod(tmp, path.stat().st_mode & 0o777 if path.exists() else 0o644)
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def write_json_atomic(path, data):
    """Writes `data` as JSON through `write_atomic`."""
    write_atomic(path, (json.dumps(data, indent=2) + "\n").encode("utf-8"))


def update_manifest(manifest, skills_dir, names, revision):
    """Records what is installed. `revisions` holds the hub commit each skill was copied at, `hub_revision` the latest install."""
    previous = manifest.get("hub_revision", "unknown")
    known = manifest.get("revisions", {})
    # Drop entries whose folder was deleted, so the manifest lists only what is installed.
    installed = {n for n in manifest["skills"] if (skills_dir / n).is_dir()}
    manifest["skills"] = sorted(installed | set(names))
    # A manifest from before per-skill revisions has one shared revision, which is the best record for its old entries.
    manifest["revisions"] = {n: revision if n in names else known.get(n, previous) for n in manifest["skills"]}
    manifest["hub_revision"] = revision


def write_instructions(args, manifest, instructions):
    """Writes the instruction file listing the installed skills. A skill no longer in the hub is listed without a description."""
    available = find_skills(args.hub)
    lines = "\n".join(f"- `{n}`: {describe(available[n]) if n in available else '(not in this hub)'}" for n in manifest["skills"])
    instructions.write_text(
        INSTRUCTIONS_TEMPLATE.format(project=args.dest.resolve().name, skills_dir=SKILLS_DIR, skill_lines=lines),
        encoding="utf-8")


def apply_install(args, actions, manifest):
    """Installs the skills and writes the metadata, undoing every change if any step fails."""
    skills_dir = args.dest / SKILLS_DIR
    instructions = args.dest / INSTRUCTIONS
    # Only files this run can change are saved. An existing instruction file is never modified, so it is never restored.
    written = [skills_dir / ".hub-skills.json", *(args.dest / extra for extra in EXTRA_FILES)]
    if not present(instructions):
        written.append(instructions)
    saved = snapshot(written)
    done = swap_in(actions, skills_dir)
    try:
        update_manifest(manifest, skills_dir, {n for n, _, _ in actions}, hub_revision(args.hub))
        if not present(instructions):
            write_instructions(args, manifest, instructions)
        write_claude_extras(args.dest)
        write_json_atomic(skills_dir / ".hub-skills.json", manifest)  # last, so it never describes an install that failed
    except Exception:
        roll_back(done)
        restore(saved)
        raise
    commit(done)


def prepare(args):
    """Validates the request without writing anything. Returns (errors, actions, manifest)."""
    names = list(dict.fromkeys(n.strip() for n in args.skills.split(",") if n.strip()))  # drops repeats, keeps order
    if not names:
        return ["--skills lists no skill names"], [], None
    if not (args.hub / "skills").is_dir():
        return [f"{args.hub} has no skills/ directory"], [], None
    if not args.dest.is_dir():
        return [f"destination {args.dest} is not a directory"], [], None
    errors = layout_errors(args.dest)  # before anything else reads or writes under the destination
    plan_errors, actions = plan(args.hub, args.dest, names, args.force)
    errors += plan_errors
    manifest = None
    try:
        manifest = load_manifest(args.dest / SKILLS_DIR / ".hub-skills.json")  # read first, so a bad one stops the run before any write
    except ValueError as exc:
        errors.append(str(exc))
    return errors, actions, manifest


def print_plan(actions, instructions):
    """Prints what an install would copy and whether the instruction file is written or kept."""
    for _name, src, target in actions:
        print(f"copy {src} -> {target}")
    print(f"{'keep existing' if present(instructions) else 'write'} {instructions}")


def main(argv=None):
    """Prints the plan and, unless --dry-run, applies it. Returns the exit status."""
    args = parse_args(argv)
    errors, actions, manifest = prepare(args)
    if errors:
        print("\n".join(f"error: {e}" for e in errors), file=sys.stderr)
        return 1
    print_plan(actions, args.dest / INSTRUCTIONS)
    if args.dry_run:
        print("dry run: nothing written")
        return 0
    apply_install(args, actions, manifest)
    print(f"installed {len(actions)} skill(s) into {args.dest / SKILLS_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
