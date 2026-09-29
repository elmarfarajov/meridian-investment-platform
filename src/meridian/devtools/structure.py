"""The shape of the code: which package imports which, how big each is, and how it is tested.

Parsed from the source with :mod:`ast`, so the numbers are the code's, not a
diagram someone drew. An import counts where it is written - at module level
or inside a function (the lazy imports that keep the command line fast) - and
is resolved to the package it names, so ``from ..risk.model import X`` inside
``meridian.services`` is an edge from ``services`` to ``risk``.
"""

from __future__ import annotations

import ast
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "src" / "meridian"
TESTS = ROOT / "tests"


@dataclass(frozen=True)
class PackageStats:
    name: str
    modules: int
    lines: int
    functions: int
    classes: int


#: single-file modules at the top of the package, grouped by what they are for
TOP_LEVEL = {"config": "config", "observability": "config", "seed": "seed", "__init__": "config", "__main__": "cli"}


def group_of_module(stem: str) -> str:
    if stem.endswith("gallery"):
        return "gallery"
    return TOP_LEVEL.get(stem, "config")


def package_of(path: Path, source: Path = SOURCE) -> str:
    relative = path.relative_to(source)
    if len(relative.parts) > 1:
        return relative.parts[0]
    return group_of_module(relative.stem)


def _resolve(module: str, node: ast.ImportFrom | ast.Import, path: Path, source: Path) -> list[str]:
    names: list[str] = []
    if isinstance(node, ast.Import):
        names = [alias.name for alias in node.names if alias.name.startswith("meridian")]
        return [name.split(".")[1] if name.count(".") >= 1 else "top level" for name in names]
    if node.level == 0:
        if node.module and node.module.startswith("meridian."):
            return [node.module.split(".")[1]]
        return []
    package = list(path.relative_to(source).parent.parts)
    base = package[: len(package) - (node.level - 1)] if node.level > 1 else package
    target = [*base, *(node.module.split(".") if node.module else [])]
    if not target:
        return [alias.name for alias in node.names]
    return [target[0]]


def upward(
    edges: dict[tuple[str, str], int], layers: list[list[str]] | tuple[tuple[str, ...], ...]
) -> list[tuple[str, str]]:
    """Edges from a lower layer to a higher one: the imports a layered design forbids."""
    level = {name: index for index, names in enumerate(layers) for name in names}
    return sorted(edge for edge in edges if edge[0] in level and edge[1] in level and level[edge[0]] < level[edge[1]])


def import_graph(source: Path = SOURCE) -> dict[tuple[str, str], int]:
    """(importer, imported) package -> number of import statements."""
    edges: Counter[tuple[str, str]] = Counter()
    for path in source.rglob("*.py"):
        importer = package_of(path, source)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import | ast.ImportFrom):
                for name in _resolve(importer, node, path, source):
                    if (source / name).is_dir():
                        target = name
                    elif (source / f"{name}.py").is_file():
                        target = group_of_module(name)
                    else:
                        continue
                    if target != importer:
                        edges[(importer, target)] += 1
    return dict(edges)


def package_stats(source: Path = SOURCE) -> list[PackageStats]:
    totals: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0, 0])
    for path in source.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        entry = totals[package_of(path, source)]
        entry[0] += 1
        entry[1] += sum(1 for line in text.splitlines() if line.strip())
        entry[2] += sum(isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) for node in ast.walk(tree))
        entry[3] += sum(isinstance(node, ast.ClassDef) for node in ast.walk(tree))
    return sorted((PackageStats(name, *values) for name, values in totals.items()), key=lambda item: -item.lines)


def tests_by_package(tests: Path = TESTS) -> dict[str, tuple[int, int]]:
    """Test directory -> (test functions, of which property-based)."""
    output: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for path in tests.rglob("test_*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        group = path.relative_to(tests).parts[0] if len(path.relative_to(tests).parts) > 1 else "platform"
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith("test_"):
                output[group][0] += 1
                if any(ast.unparse(item).split("(")[0].endswith("given") for item in node.decorator_list):
                    output[group][1] += 1
    return {name: (values[0], values[1]) for name, values in output.items()}
