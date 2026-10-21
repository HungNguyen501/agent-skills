"""Unit tests for the python-docstrings script find_undocumented"""
import ast
import sys

import pytest

from tests.mocks import REPO_ROOT, load_script

fu = load_script(REPO_ROOT / "skills/python/python-docstrings/scripts/find_undocumented.py", "find_undocumented")


def gaps(source, include_private=False):
    """(kind, name) of every definition the script reports for `source`"""
    return [(kind, name) for _, kind, name in fu.find_undocumented(ast.parse(source), include_private)]


MODULE = '"""Doc."""\n'


def test_reports_public_function_class_and_method():
    source = MODULE + "def f(): pass\nclass A:\n    def m(self): pass\n"
    assert gaps(source) == [("function", "f"), ("class", "A"), ("method", "A.m")]


def test_documented_module_has_no_gaps():
    assert gaps(MODULE + 'def f():\n    """F."""\n') == []


def test_missing_module_docstring_is_reported():
    assert gaps("def f():\n    '''F.'''\n") == [("module", "<module>")]


@pytest.mark.parametrize(
    "source",
    [
        "try:\n    import x\nexcept ImportError:\n    def fallback(): pass\n",
        "if True:\n    def f(): pass\n",
        "with open('x') as h:\n    def f(): pass\n",
    ],
    ids=["except-handler", "if-block", "with-block"],
)
def test_finds_definitions_inside_statement_containers(source):
    assert gaps(MODULE + source)[0][0] == "function"


@pytest.mark.skipif(sys.version_info < (3, 10), reason="match statements need Python 3.10")
def test_finds_definitions_inside_match_case():
    source = MODULE + "match 1:\n    case 1:\n        def f(): pass\n"
    assert gaps(source) == [("function", "f")]


IMPORTS = (
    "import typing\nimport typing as t\nimport typing_extensions as te\n"
    "from typing import overload, override\nfrom typing import overload as ov\n"
    "from typing_extensions import override as te_override\n"
)


@pytest.mark.parametrize(
    "decorator, func",
    [
        ("@overload", "m"),
        ("@override", "m"),
        ("@typing.overload", "m"),
        ("@typing.override", "m"),
        ("@t.overload", "m"),
        ("@te.override", "m"),
        ("@ov", "m"),
        ("@te_override", "m"),
        ("@x.setter", "x"),
        ("@x.deleter", "x"),
    ],
)
def test_skips_definitions_that_take_no_docstring(decorator, func):
    source = MODULE + IMPORTS + f'class A:\n    """A."""\n    {decorator}\n    def {func}(self): pass\n'
    assert gaps(source) == []


@pytest.mark.parametrize(
    "decorator, func",
    [
        ("@registry.override", "m"),
        ("@registry.overload", "m"),
        ("@other.setter", "x"),
        ("@x.setter", "y"),
        ("@staticmethod", "m"),
        ("@overload", "m"),
        ("@override", "m"),
    ],
    ids=["unrelated-override", "unrelated-overload", "setter-of-another-name", "setter-on-another-function",
         "staticmethod", "overload-never-imported", "override-never-imported"],
)
def test_other_decorators_are_still_reported(decorator, func):
    source = MODULE + f'class A:\n    """A."""\n    {decorator}\n    def {func}(self): pass\n'
    assert gaps(source) == [("method", f"A.{func}")]


def test_private_names_need_all_flag():
    source = MODULE + "def _h(): pass\nclass A:\n    def __init__(self): pass\n"
    assert gaps(source) == [("class", "A")]
    assert gaps(source, include_private=True) == [("function", "_h"), ("class", "A"), ("method", "A.__init__")]


def test_functions_nested_in_functions_are_ignored():
    assert gaps(MODULE + 'def f():\n    """F."""\n    def inner(): pass\n') == []


def test_main_exit_status_and_summary(tmp_path, capsys):
    clean = tmp_path / "clean.py"
    clean.write_text(MODULE, encoding="utf-8")
    bad = tmp_path / "bad.py"
    bad.write_text(MODULE + "def f(): pass\n", encoding="utf-8")

    assert fu.main([str(clean)]) == 0
    assert fu.main([str(bad)]) == 1
    assert "1 undocumented, 0 skipped" in capsys.readouterr().out


def test_main_reports_missing_path_and_syntax_error_as_skipped(tmp_path, capsys):
    broken = tmp_path / "broken.py"
    broken.write_text("def (:\n", encoding="utf-8")

    assert fu.main([str(broken), str(tmp_path / "nope.py")]) == 1
    assert "0 undocumented, 2 skipped" in capsys.readouterr().out


PRIVATE_CLASSES = MODULE + "class _Internal:\n    def run(self): pass\nclass Public:\n    \"\"\"P.\"\"\"\n    class _Inner:\n        def go(self): pass\n"


def test_private_class_and_its_members_are_not_public_api():
    assert gaps(PRIVATE_CLASSES) == []


def test_all_flag_reports_private_classes_and_their_members():
    assert gaps(PRIVATE_CLASSES, include_private=True) == [
        ("class", "_Internal"),
        ("method", "_Internal.run"),
        ("class", "Public._Inner"),
        ("method", "Public._Inner.go"),
    ]


def test_decorated_class_named_like_a_stub_is_still_reported():
    assert gaps(MODULE + "@override\nclass A: pass\n") == [("class", "A")]


def test_directory_walk_skips_hidden_and_installed_code_folders(tmp_path, capsys):
    for folder in (".hidden", "venv", "node_modules", "site-packages", "__pycache__"):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / "x.py").write_text(MODULE + "def f(): pass\n", encoding="utf-8")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "ok.py").write_text(MODULE, encoding="utf-8")

    assert fu.main([str(tmp_path)]) == 0
    assert "0 undocumented, 0 skipped" in capsys.readouterr().out
