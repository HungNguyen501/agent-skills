"""Regression tests for the validator, frontmatter parsing, loader and sync script.

Run: uv run pytest
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

import build  # noqa: E402
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


def symlink_or_skip(target: str, link: Path) -> None:
    """Create a symlink, skipping the test where the platform does not allow it."""
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError) as exc:
        raise unittest.SkipTest(f"cannot create symlinks here: {exc}") from exc


def add_symlink_loops(skill_dir: Path) -> None:
    """A self-referential link and a mutually recursive pair: Path.resolve() raises RuntimeError on 3.11/3.12."""
    refs = skill_dir / "references"
    refs.mkdir(exist_ok=True)
    symlink_or_skip("loop.md", refs / "loop.md")
    symlink_or_skip("b.md", refs / "a.md")
    symlink_or_skip("a.md", refs / "b.md")


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

    def test_null_and_list_order_are_reported_not_raised(self):
        # "²" and Arabic-Indic digits pass str.isdigit() but are not ASCII digits; "-1" is negative
        for i, order in enumerate(("null", "[1, 2]", "abc", "1.5", '"²"', '"-1"', '"١٢"', '""', '" 5"')):
            name = f"order-{i}"
            skill = make_skill(self.tmp, name, frontmatter=f"name: {name}\ndescription: Use when testing.\nmetadata:\n  order: {order}\n")
            errors = self.run_check(skill)
            self.assertTrue(any("metadata.order" in e for e in errors), (order, errors))

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

    def test_titled_link_to_existing_file_counts_as_linked(self):
        skill = make_skill(
            self.tmp, "titled-ok", body='See [ref](references/a.md "Details").\n',
            files={"references/a.md": "# A\n"},
        )
        errors, warnings = validate.check_skill(skill, {})
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])  # no "not linked from SKILL.md"

    def test_titled_link_to_missing_file_is_an_error(self):
        skill = make_skill(self.tmp, "titled-missing", body='See [ref](references/missing.md "Details").\n')
        errors = self.run_check(skill)
        self.assertTrue(any("missing file 'references/missing.md'" in e for e in errors), errors)

    def test_titled_link_escaping_the_skill_directory_is_an_error(self):
        (self.tmp / "outside.md").write_text("x", encoding="utf-8")
        skill = make_skill(self.tmp, "titled-escape", body='See [other](../outside.md "Details").\n')
        errors = self.run_check(skill)
        self.assertTrue(any("outside the skill directory" in e for e in errors), errors)

    def test_symlink_loops_are_reported_and_later_skills_are_still_checked(self):
        looped = make_skill(self.tmp, "looped", body="See [a](references/loop.md) and [b](references/a.md).\n")
        add_symlink_loops(looped)
        good = make_skill(self.tmp, "good-after-loop")
        seen: dict = {}
        errors, _ = validate.check_skill(looped, seen)  # must not raise RuntimeError
        good_errors, _ = validate.check_skill(good, seen)
        self.assertTrue(any("symlinks are not allowed" in e for e in errors), errors)
        self.assertEqual(good_errors, [])

    def test_link_resolution_failure_is_a_finding_not_a_crash(self):
        looped = make_skill(self.tmp, "resolve-fail", body="See [a](references/loop.md).\n")
        add_symlink_loops(looped)
        errors, _ = validate._check_links("See [a](references/loop.md).", looped.resolve(), looped.resolve(), Path("resolve-fail"))
        self.assertEqual(len(errors), 1)
        self.assertTrue("symlink loop" in errors[0] or "missing file" in errors[0] or "outside" in errors[0], errors)

    def test_any_symlink_in_a_skill_is_rejected(self):
        skill = make_skill(self.tmp, "linked", files={"references/real.md": "# R\n"})
        symlink_or_skip("real.md", skill / "references" / "alias.md")
        symlink_or_skip("references", skill / "refs-dir")
        errors = self.run_check(skill)
        flagged = [e for e in errors if "symlinks are not allowed" in e]
        self.assertEqual(len(flagged), 2, errors)

    def test_valid_ascii_order_is_accepted(self):
        skill = make_skill(self.tmp, "ok-order", frontmatter='name: ok-order\ndescription: Use when testing.\nmetadata:\n  order: "007"\n')
        self.assertEqual(self.run_check(skill), [])

    def test_unreadable_reference_is_reported_and_later_skills_are_still_checked(self):
        bad = make_skill(self.tmp, "bad-ref", body="See [r](references/bad.md).\n", files={"references/bad.md": b"\xff\xfe invalid utf-8"})
        good = make_skill(self.tmp, "good-after")
        seen: dict = {}
        bad_errors, _ = validate.check_skill(bad, seen)
        good_errors, _ = validate.check_skill(good, seen)
        self.assertTrue(any("cannot read reference" in e and "bad.md" in e for e in bad_errors), bad_errors)
        self.assertEqual(good_errors, [])

    def test_links_into_directories_that_are_not_packaged_are_rejected(self):
        for target in ("evals/evals.json", "references/evals/x.json", "scripts/__pycache__/m.pyc"):
            name = "into-" + target.split("/")[0] + str(abs(hash(target)) % 1000)
            skill = make_skill(self.tmp, name, body=f"See [x]({target}).\n", files={target: "{}"})
            errors = self.run_check(skill)
            self.assertTrue(any("not packaged" in e for e in errors), (target, errors))

    def test_package_ignore_lists_match_between_build_and_sync(self):
        self.assertEqual(sync.PACKAGE_IGNORE, skilllib.PACKAGE_IGNORE)

    def test_every_validated_link_exists_in_the_packaged_skill(self):
        """Validate against the real packaging, not just the source tree."""
        for skill_dir in skilllib.discover():
            skill = skilllib.load(skill_dir)
            out = self.tmp / f"pkg-{skill.name}"
            build.package_skill(out, skill)
            packaged = out / "plugins" / skill.domain / "skills" / skill_dir.name
            for link in validate._local_links(skill.body):
                self.assertTrue((packaged / link).exists(), f"{skill.name}: link '{link}' missing from packaged skill")

    def test_link_extraction_variants(self):
        text = '[a](x.md) [b](y.md#frag) [c](z.md "t") [d](<w.md>) [e](https://example.com "t") [f](mailto:a@b.c)'
        self.assertEqual(validate._local_links(text), ["x.md", "y.md", "z.md", "w.md"])

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

    def test_malformed_order_raises_value_error_naming_the_file(self):
        # null, list, bool, float and non-numeric text must all raise ValueError (never TypeError) with the path
        for i, order in enumerate(("null", "[1, 2]", "true", "1.5", "abc", '"1.5"')):
            name = f"bad-order-{i}"
            make_skill(self.tmp, name, frontmatter=f"name: {name}\ndescription: Use when testing.\nmetadata:\n  order: {order}\n")
            with self.assertRaisesRegex(ValueError, f"{name}.*metadata.order", msg=f"order: {order}"):
                loader.discover(self.tmp)
            (self.tmp / name / "SKILL.md").unlink()
            (self.tmp / name / "evals" / "evals.json").unlink()
            (self.tmp / name / "evals").rmdir()
            (self.tmp / name).rmdir()

    def test_integer_and_integer_string_order_are_accepted(self):
        make_skill(self.tmp, "int-order", frontmatter="name: int-order\ndescription: Use when testing.\nmetadata:\n  order: 7\n")
        make_skill(self.tmp, "str-order", frontmatter='name: str-order\ndescription: Use when testing.\nmetadata:\n  order: "3"\n')
        self.assertEqual(list(loader.discover(self.tmp)), ["str-order", "int-order"])

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


class ToolCallTests(TmpDirCase):
    BAD_VALUES = (None, ["a"], {"a": 1}, 5, True, "")

    def setUp(self):
        super().setUp()
        make_skill(self.tmp, "demo", files={"references/ok.md": "hello"})
        self.skills = loader.discover(self.tmp)

    def test_invalid_name_never_raises_for_either_tool(self):
        for tool, extra in (("load_skill", {}), ("read_skill_file", {"path": "references/ok.md"})):
            for bad in self.BAD_VALUES:
                result = loader.handle_tool_call(self.skills, tool, {"name": bad, **extra})
                self.assertIn("Invalid argument 'name'", result, (tool, bad))

    def test_invalid_path_never_raises(self):
        for bad in self.BAD_VALUES:
            result = loader.handle_tool_call(self.skills, "read_skill_file", {"name": "demo", "path": bad})
            self.assertIn("Invalid argument 'path'", result, bad)

    def test_missing_arguments_and_non_object_args_return_errors(self):
        self.assertIn("Invalid argument 'name'", loader.handle_tool_call(self.skills, "load_skill", {}))
        self.assertIn("Invalid argument 'path'", loader.handle_tool_call(self.skills, "read_skill_file", {"name": "demo"}))
        for tool in ("load_skill", "read_skill_file"):
            for bad_args in (None, ["demo"], "demo", 5):
                self.assertIn("Invalid arguments", loader.handle_tool_call(self.skills, tool, bad_args), (tool, bad_args))

    def test_symlink_loop_in_a_bundled_file_returns_an_error_string(self):
        add_symlink_loops(self.tmp / "demo")
        for path in ("references/loop.md", "references/a.md", "references/b.md"):
            for call in (
                lambda p=path: loader.read_skill_file(self.skills, "demo", p),
                lambda p=path: loader.handle_tool_call(self.skills, "read_skill_file", {"name": "demo", "path": p}),
            ):
                result = call()  # must not raise RuntimeError
                self.assertIsInstance(result, str)
                self.assertTrue("could not be read" in result or "not found" in result, result)

    def test_nul_byte_in_path_returns_an_error_string(self):
        result = loader.handle_tool_call(self.skills, "read_skill_file", {"name": "demo", "path": "a\x00b"})
        self.assertIsInstance(result, str)

    def test_valid_calls_and_unknown_tools_are_unchanged(self):
        self.assertEqual(loader.handle_tool_call(self.skills, "load_skill", {"name": "demo"}), "Body.")
        self.assertEqual(loader.handle_tool_call(self.skills, "read_skill_file", {"name": "demo", "path": "references/ok.md"}), "hello")
        self.assertIn("Unknown skill", loader.handle_tool_call(self.skills, "load_skill", {"name": "nope"}))
        self.assertIsNone(loader.handle_tool_call(self.skills, "execute_query", {"sql": "select 1"}))


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

    def run_sync_raw(self, config_text: str, manifest_text: str | None = None) -> int:
        config = self.tmp / "raw.toml"
        config.write_text(config_text, encoding="utf-8")
        if manifest_text is not None:
            (self.hub / "manifest.json").write_text(manifest_text, encoding="utf-8")
        argv = ["sync.py", "--hub", str(self.hub), "--config", str(config), "--dest", str(self.dest)]
        with mock.patch.object(sys, "argv", argv), redirect_stdout(io.StringIO()):
            return sync.main()

    def assert_controlled_failure_keeps_dest(self, code: int):
        self.assertEqual(code, 1)
        self.assertTrue((self.dest / "alpha" / "SKILL.md").is_file())
        self.assertEqual([p.name for p in self.dest.parent.iterdir() if p.name != "skills"], [])

    def test_malformed_config_shapes_fail_cleanly_and_keep_the_destination(self):
        self.assertEqual(self.run_sync(["alpha"]), 0)
        for text in (
            'skills = "alpha"\n',  # scalar instead of a table
            'skills = ["alpha"]\n',  # list instead of a table
            "skills = 5\n",
            "[skills]\ninclude = \"alpha\"\n",  # scalar include
            "[skills]\ninclude = [1, 2]\n",  # non-string entries
            "[skills]\ninclude = {a = 1}\n",  # table include
            "[other]\nx = 1\n",  # no [skills] at all
            "this is = not [valid toml\n",
        ):
            self.assert_controlled_failure_keeps_dest(self.run_sync_raw(text))

    def test_malformed_manifest_fails_cleanly_and_keeps_the_destination(self):
        good_manifest = (self.hub / "manifest.json").read_text(encoding="utf-8")
        self.assertEqual(self.run_sync(["alpha"]), 0)
        for manifest in (
            "[]",  # not an object
            "{}",  # no skills key
            '{"skills": "alpha"}',  # scalar skills
            '{"skills": ["alpha"]}',  # entries not objects
            '{"skills": [{"name": "alpha"}]}',  # no path
            '{"skills": [{"name": 5, "path": "x"}]}',  # non-string name
            "not json",
        ):
            self.assert_controlled_failure_keeps_dest(self.run_sync_raw('[skills]\ninclude = ["alpha"]\n', manifest))
        (self.hub / "manifest.json").write_text(good_manifest, encoding="utf-8")
        self.assertEqual(self.run_sync(["alpha"]), 0)

    def backup(self) -> Path:
        return sync.backup_path(self.dest)

    def test_orphaned_backup_is_restored_not_deleted(self):
        """A crash after dest->backup leaves no dest. The backup is the only copy and must survive."""
        self.assertEqual(self.run_sync(["alpha"]), 0)
        self.dest.rename(self.backup())  # simulate the crash window
        self.assertFalse(self.dest.exists())
        # even a run that fails early must put the previous skills back
        self.assertEqual(self.run_sync(["missing"]), 1)
        self.assertTrue((self.dest / "alpha" / "SKILL.md").is_file())
        self.assertFalse(self.backup().exists())

    def test_orphaned_backup_survives_a_failure_while_staging(self):
        self.assertEqual(self.run_sync(["alpha"]), 0)
        self.dest.rename(self.backup())
        with mock.patch.object(sync, "stage", side_effect=OSError("disk full")):
            self.assertEqual(self.run_sync(["beta"]), 1)
        self.assertTrue((self.dest / "alpha" / "SKILL.md").is_file())  # previous skills intact

    def test_successful_sync_after_a_crash_replaces_content_and_leaves_no_backup(self):
        self.assertEqual(self.run_sync(["alpha"]), 0)
        self.dest.rename(self.backup())
        self.assertEqual(self.run_sync(["beta"]), 0)
        self.assertTrue((self.dest / "beta" / "SKILL.md").is_file())
        self.assertFalse((self.dest / "alpha").exists())
        self.assertFalse(self.backup().exists())

    def test_stale_backup_next_to_a_live_dest_is_cleaned_up(self):
        self.assertEqual(self.run_sync(["alpha"]), 0)
        self.backup().mkdir()
        (self.backup() / "stale.txt").write_text("old", encoding="utf-8")
        self.assertEqual(self.run_sync(["alpha"]), 0)
        self.assertFalse(self.backup().exists())
        self.assertTrue((self.dest / "alpha" / "SKILL.md").is_file())

    def test_failed_swap_restores_the_previous_destination(self):
        self.assertEqual(self.run_sync(["alpha"]), 0)
        staging = self.dest.with_name(".skills.staging")  # never created, so the final rename fails
        with self.assertRaises(OSError):
            sync.replace_dest(staging, self.dest)
        self.assertTrue((self.dest / "alpha" / "SKILL.md").is_file())
        self.assertFalse(self.backup().exists())

    def test_successful_resync_replaces_content(self):
        self.assertEqual(self.run_sync(["alpha"]), 0)
        self.assertEqual(self.run_sync(["beta"]), 0)
        self.assertFalse((self.dest / "alpha").exists())
        self.assertTrue((self.dest / "beta" / "SKILL.md").is_file())


if __name__ == "__main__":
    unittest.main()
