"""Regression tests for the validator, frontmatter parsing, loader and sync script.

Run: uv run python -m unittest discover -s tests -v
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "runtimes" / "python"))

import loader  # noqa: E402
import skilllib  # noqa: E402
import sync  # noqa: E402
import validate  # noqa: E402

GOOD_EVALS = [{"id": str(i), "query": "q", "expected_behavior": ["b"]} for i in range(3)]


def make_skill(base: Path, name: str, frontmatter: str | None = None, body: str = "Body.\n", evals=GOOD_EVALS, files=None) -> Path:
    """Create <base>/<name>/SKILL.md (+ evals) and return the skill directory."""
    skill = base / name
    skill.mkdir(parents=True)
    front = frontmatter if frontmatter is not None else f"name: {name}\ndescription: Does a thing. Use when testing.\n"
    (skill / "SKILL.md").write_text(f"---\n{front}---\n{body}", encoding="utf-8")
    if evals is not None:
        (skill / "evals").mkdir()
        (skill / "evals" / "evals.json").write_text(json.dumps(evals), encoding="utf-8")
    for rel, content in (files or {}).items():
        path = skill / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode())
    return skill


class TmpDirCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)


class ValidatorTests(TmpDirCase):
    def run_check(self, skill_dir: Path) -> list[str]:
        errors, _ = validate.check_skill(skill_dir, {})
        return errors

    def test_valid_skill_has_no_errors(self):
        self.assertEqual(self.run_check(make_skill(self.tmp, "good-skill")), [])

    def test_invalid_yaml_is_reported_not_raised(self):
        skill = make_skill(self.tmp, "broken", frontmatter="name: broken\ndescription: a: b: c\n  bad: [\n")
        errors = self.run_check(skill)
        self.assertTrue(any("invalid YAML" in e for e in errors), errors)

    def test_scalar_and_list_metadata_are_reported_not_raised(self):
        for i, value in enumerate(("just-a-string", "[a, b]")):
            name = f"meta-{i}"
            skill = make_skill(self.tmp, name, frontmatter=f"name: {name}\ndescription: Use when testing.\nmetadata: {value}\n")
            errors = self.run_check(skill)
            self.assertTrue(any("metadata must be a mapping" in e for e in errors), errors)

    def test_non_object_eval_entry_is_reported_not_raised(self):
        skill = make_skill(self.tmp, "bad-evals", evals=["a string", 5, {"id": "x", "query": "q", "expected_behavior": ["b"]}])
        errors = self.run_check(skill)
        self.assertEqual(sum("must be an object" in e for e in errors), 2, errors)

    def test_numeric_name_is_rejected(self):
        skill = make_skill(self.tmp, "123", frontmatter="name: 123\ndescription: Use when testing.\n")
        errors = self.run_check(skill)
        self.assertTrue(any("name must be a string" in e for e in errors), errors)

    def test_non_string_description_is_rejected(self):
        skill = make_skill(self.tmp, "num-desc", frontmatter="name: num-desc\ndescription: 42\n")
        errors = self.run_check(skill)
        self.assertTrue(any("description must be a string" in e for e in errors), errors)

    def test_link_escaping_the_skill_directory_is_rejected(self):
        (self.tmp / "outside.md").write_text("x", encoding="utf-8")
        skill = make_skill(self.tmp, "escaper", body="See [other](../outside.md).\n")
        errors = self.run_check(skill)
        self.assertTrue(any("outside the skill directory" in e for e in errors), errors)

    def test_link_inside_the_skill_directory_passes(self):
        skill = make_skill(self.tmp, "inside", body="See [ref](references/a.md).\n", files={"references/a.md": "# A\n"})
        self.assertEqual(self.run_check(skill), [])

    def test_one_bad_skill_does_not_stop_later_skills(self):
        bad = make_skill(self.tmp, "bad", frontmatter="name: bad\nmetadata: nope\ndescription: x\n", evals=[1])
        good = make_skill(self.tmp, "good")
        seen: dict = {}
        bad_errors, _ = validate.check_skill(bad, seen)
        good_errors, _ = validate.check_skill(good, seen)
        self.assertTrue(bad_errors)
        self.assertEqual(good_errors, [])

    def test_real_hub_validates_cleanly(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(validate.main(), 0, buf.getvalue())


class FrontmatterTests(unittest.TestCase):
    TEXT = 'name: demo\ndescription: Use when comparing ---\nmetadata:\n  always: "true"\n'

    def test_triple_dash_inside_a_value_is_not_a_delimiter(self):
        text = f"---\n{self.TEXT}---\nBODY\n---\nafter rule\n"
        meta, body = skilllib.parse_skill_md(text)
        self.assertEqual(meta["description"], "Use when comparing ---")
        self.assertIn("after rule", body)
        parsed, loader_body = loader._parse(text)
        self.assertEqual(parsed["description"], "Use when comparing ---")
        self.assertIn("after rule", loader_body)

    def test_malformed_frontmatter_raises_value_error_in_both_parsers(self):
        for bad in ("no frontmatter\n", "---\nname: x\nnever closed\n", "---\n- a\n- b\n---\nbody\n"):
            for parse in (skilllib.parse_skill_md, loader._parse):
                with self.assertRaises(ValueError, msg=bad):
                    parse(bad)


class LoaderTests(TmpDirCase):
    def test_duplicate_name_across_directories_raises(self):
        make_skill(self.tmp / "a", "dup")
        make_skill(self.tmp / "b", "dup")
        with self.assertRaises(ValueError):
            loader.discover([self.tmp / "a", self.tmp / "b"])

    def test_duplicate_name_raises_even_when_the_allowlist_excludes_it(self):
        make_skill(self.tmp / "a", "dup")
        make_skill(self.tmp / "b", "dup")
        make_skill(self.tmp / "a", "wanted")
        with self.assertRaises(ValueError):
            loader.discover([self.tmp / "a", self.tmp / "b"], allow={"wanted"})

    def test_allowlist_filters_routed_skills_but_not_always_on(self):
        make_skill(self.tmp, "routed-a")
        make_skill(self.tmp, "routed-b")
        make_skill(self.tmp, "core", frontmatter='name: core\ndescription: Use when testing.\nmetadata:\n  always: "true"\n')
        found = loader.discover(self.tmp, allow={"routed-a"})
        self.assertEqual(sorted(found), ["core", "routed-a"])

    def test_order_sorts_skills(self):
        for name, order in (("late", "30"), ("early", "5"), ("middle", "10")):
            make_skill(self.tmp, name, frontmatter=f'name: {name}\ndescription: Use when testing.\nmetadata:\n  order: "{order}"\n')
        self.assertEqual(list(loader.discover(self.tmp)), ["early", "middle", "late"])

    def test_malformed_skill_error_names_the_file(self):
        make_skill(self.tmp, "broken", frontmatter="name: broken\ndescription: [\n")
        with self.assertRaisesRegex(ValueError, "broken"):
            loader.discover(self.tmp)

    def test_read_skill_file_handles_binary_and_traversal(self):
        make_skill(self.tmp, "files", files={"assets/blob.bin": b"\xff\xfe\x00\x80", "references/ok.md": "hello"})
        (self.tmp / "secret.txt").write_text("secret", encoding="utf-8")
        skills = loader.discover(self.tmp)
        self.assertEqual(loader.read_skill_file(skills, "files", "references/ok.md"), "hello")
        self.assertIn("not UTF-8", loader.read_skill_file(skills, "files", "assets/blob.bin"))
        self.assertIn("not found", loader.read_skill_file(skills, "files", "../secret.txt"))
        self.assertIn("not found", loader.read_skill_file(skills, "files", "references"))
        self.assertIn("not found", loader.read_skill_file(skills, "files", "nope.md"))
        # handle_tool_call must return a result, not raise
        result = loader.handle_tool_call(skills, "read_skill_file", {"name": "files", "path": "assets/blob.bin"})
        self.assertIn("not UTF-8", result)


class SyncTests(TmpDirCase):
    def setUp(self):
        super().setUp()
        self.hub = self.tmp / "hub"
        make_skill(self.hub / "skills" / "d", "alpha")
        make_skill(self.hub / "skills" / "d", "beta")
        manifest = {"skills": [{"name": n, "path": f"skills/d/{n}"} for n in ("alpha", "beta")]}
        (self.hub / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        self.dest = self.tmp / "consumer" / "skills"

    def run_sync(self, include: list[str]) -> int:
        config = self.tmp / "skills.toml"
        config.write_text("[skills]\ninclude = [" + ", ".join(f'"{n}"' for n in include) + "]\n", encoding="utf-8")
        argv = ["sync.py", "--hub", str(self.hub), "--config", str(config), "--dest", str(self.dest)]
        with mock.patch.object(sys, "argv", argv), redirect_stdout(io.StringIO()):
            return sync.main()

    def test_sync_copies_and_deduplicates(self):
        self.assertEqual(self.run_sync(["alpha", "alpha", "beta"]), 0)
        self.assertEqual(sorted(p.name for p in self.dest.iterdir() if not p.name.startswith(".")), ["alpha", "beta"])
        self.assertTrue((self.dest / ".hub-version").is_file())
        self.assertFalse((self.dest / "alpha" / "evals").exists())

    def test_failed_sync_keeps_the_previous_destination(self):
        self.assertEqual(self.run_sync(["alpha"]), 0)
        for bad in (["alpha", "missing"], []):
            self.assertEqual(self.run_sync(bad), 1)
            self.assertTrue((self.dest / "alpha" / "SKILL.md").is_file())
        leftovers = [p.name for p in self.dest.parent.iterdir() if p.name != "skills"]
        self.assertEqual(leftovers, [])

    def test_successful_resync_replaces_content(self):
        self.assertEqual(self.run_sync(["alpha"]), 0)
        self.assertEqual(self.run_sync(["beta"]), 0)
        self.assertFalse((self.dest / "alpha").exists())
        self.assertTrue((self.dest / "beta" / "SKILL.md").is_file())


if __name__ == "__main__":
    unittest.main()
