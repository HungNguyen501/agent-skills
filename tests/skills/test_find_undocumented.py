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


@pytest.mark.parametrize(
    "decorator",
    ["@overload", "@typing.overload", "@x.setter", "@x.deleter", "@override", "@typing.override"],
)
def test_skips_definitions_that_take_no_docstring(decorator):
    source = MODULE + f'class A:\n    """A."""\n    {decorator}\n    def m(self): pass\n'
    assert gaps(source) == []


def test_other_decorators_are_still_reported():
    source = MODULE + 'class A:\n    """A."""\n    @staticmethod\n    def m(): pass\n    @registry.register("x")\n    def n(self): pass\n'
    assert gaps(source) == [("method", "A.m"), ("method", "A.n")]


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
