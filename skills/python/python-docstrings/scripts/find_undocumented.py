"""Lists public modules, classes, functions and methods without docstrings.

Usage: find_undocumented.py [--all] PATH [PATH ...]

Prints one `path:line: kind name` line per gap and a summary line. Names that
start with an underscore (private helpers and dunder methods) are skipped
unless --all is given, because a docstring is only required for public API.
Exit status is 1 when anything is undocumented or could not be scanned.
"""

import ast
import os
import sys

_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
# Statement containers that can hold definitions: ast.ExceptHandler and ast.match_case are not ast.stmt subclasses.
# match_case exists from Python 3.10 on.
_CONTAINERS = (ast.stmt, ast.ExceptHandler) + ((ast.match_case,) if hasattr(ast, "match_case") else ())
# Definitions that take no docstring of their own: typing.overload stubs and typing.override methods (both modules
# export them), and a property setter or deleter, written @x.setter above def x.
_TYPING_MODULES = {"typing", "typing_extensions"}
_TYPING_EXEMPT = {"overload", "override"}
_ACCESSOR_ATTRS = {"setter", "deleter"}
# Folders that hold installed or generated code, not the project's own. Hidden folders are skipped as well.
_SKIPPED_DIRS = {"venv", "node_modules", "site-packages", "__pycache__"}


# Nodes that open their own scope: a name bound inside one does not rebind a module-level name.
_OWN_SCOPE = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)


def _module_scope(tree):
    """Every node that runs in the module's own scope: nested statements count, function, class and comprehension bodies do not."""
    stack = [tree]
    while stack:
        for child in ast.iter_child_nodes(stack.pop()):
            yield child
            if not isinstance(child, _OWN_SCOPE):
                stack.append(child)


def _typing_imports(tree):
    """(module aliases, {local name: overload or override}) imported from typing or typing_extensions at module level.

    A function-local import does not count for decorators elsewhere. A name that is also bound some other way at module
    level (assigned, defined, imported from elsewhere, or used as an `except ... as` name) no longer refers to the
    import, so it is dropped.
    """
    modules, names, rebound = set(), {}, set()
    for node in _module_scope(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in _TYPING_MODULES:
                    modules.add(alias.asname or alias.name)
                else:
                    rebound.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            from_typing = node.level == 0 and node.module in _TYPING_MODULES
            for alias in node.names:
                if from_typing and alias.name in _TYPING_EXEMPT:
                    names[alias.asname or alias.name] = alias.name
                else:
                    rebound.add(alias.asname or alias.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.ExceptHandler)) and node.name:
            rebound.add(node.name)  # a def or class statement, or the name of `except ... as name`
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            rebound.add(node.id)
    return modules - rebound, {k: v for k, v in names.items() if k not in rebound}


def _takes_no_docstring(node, modules, names):
    """True for an @overload stub, an @override method, or a property setter or deleter, which need no docstring of their own.

    Decorators are matched by what they resolve to, not by spelling: `@ov` after `from typing import overload as ov`
    counts, an unrelated `@registry.override` does not.
    """
    if isinstance(node, ast.ClassDef):
        return False
    for decorator in node.decorator_list:
        if isinstance(decorator, ast.Name) and decorator.id in names:
            return True
        if not (isinstance(decorator, ast.Attribute) and isinstance(decorator.value, ast.Name)):
            continue
        if decorator.value.id in modules and decorator.attr in _TYPING_EXEMPT:
            return True
        if decorator.attr in _ACCESSOR_ATTRS and decorator.value.id == node.name:
            return True
    return False


def find_undocumented(tree, include_private=False):
    """Yields (line, kind, qualified_name) for each definition lacking a docstring.

    Args:
        tree: Parsed module (ast.Module).
        include_private: Also report names starting with an underscore.
    """
    if ast.get_docstring(tree) is None:
        yield 1, "module", "<module>"
    modules, names = _typing_imports(tree)

    def visit(parent, prefix, in_class):
        for node in ast.iter_child_nodes(parent):
            if not isinstance(node, _DEFS):
                # Defs can hide inside if/try/with blocks.
                if isinstance(node, _CONTAINERS):
                    yield from visit(node, prefix, in_class)
                continue

            name = prefix + node.name
            if isinstance(node, ast.ClassDef):
                kind = "class"
            else:
                kind = "method" if in_class else "function"

            is_public = include_private or not node.name.startswith("_")
            if is_public and ast.get_docstring(node) is None and not _takes_no_docstring(node, modules, names):
                yield node.lineno, kind, name

            # Functions nested in functions are implementation detail.
            # A private class is not public API, so its methods are not reported either, unless --all is given.
            if kind == "class" and is_public:
                yield from visit(node, name + ".", True)

    yield from visit(tree, "", False)


def _python_files(paths, skip):
    for path in paths:
        if os.path.isfile(path):
            yield path
        elif os.path.isdir(path):
            for root, dirs, files in os.walk(path, onerror=lambda e: skip(str(e))):
                # Hidden folders are virtualenvs, caches and tool state. The named ones are installed or generated code.
                dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in _SKIPPED_DIRS)
                for name in sorted(files):
                    if name.endswith(".py"):
                        yield os.path.join(root, name)
        else:
            skip(f"{path}: not found")


def main(argv):
    """Prints every gap and returns the exit status."""
    include_private = "--all" in argv
    paths = [a for a in argv if a != "--all"]
    if not paths:
        print(__doc__.strip().splitlines()[2])
        return 2
    total = 0
    skipped = []

    def skip(problem):
        print(f"skipped: {problem}")
        skipped.append(problem)

    for path in _python_files(paths, skip):
        try:
            with open(path, "rb") as f:
                tree = ast.parse(f.read(), path)
        except (OSError, SyntaxError, ValueError) as error:
            skip(f"{path}: {error}")
            continue
        for line, kind, name in find_undocumented(tree, include_private):
            print(f"{path}:{line}: {kind} {name}")
            total += 1
    print(f"{total} undocumented, {len(skipped)} skipped")
    return 1 if total or skipped else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
