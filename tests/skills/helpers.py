"""Shared helpers for the scaffold script tests"""
import json

from tests.mocks import REPO_ROOT, load_script

# variant -> (skills folder, instruction file)
VARIANTS = {
    "cc": (".claude/skills", "CLAUDE.md"),
    "codex": (".agents/skills", "AGENTS.md"),
}


def load_variant(variant):
    """Import the generated scaffold script of one variant under a fresh module name"""
    path = REPO_ROOT / f"skills/scaffolding/scaffold-agent-repo-{variant}/scripts/scaffold.py"
    return load_script(path, f"scaffold_{variant}")


def manifest(skills_dir):
    """The parsed .hub-skills.json"""
    return json.loads((skills_dir / ".hub-skills.json").read_text(encoding="utf-8"))


def fail_manifest_write(module, monkeypatch):
    """Make only the final manifest replace fail the way a full disk would, so the atomic restore of other files still works"""
    real_replace = module.os.replace

    def flaky(src, dst):
        if module.Path(dst).name == ".hub-skills.json":
            raise OSError("disk full")
        return real_replace(src, dst)

    monkeypatch.setattr(module.os, "replace", flaky)
