"""The project measured at every release: code, tests, charts, decisions, migrations.

Each release tag is read straight from git (``git archive``, so nothing is
checked out) and measured the same way: non-blank lines of source and of
tests, test functions (found by parsing the test files, not by grepping),
figures in the gallery, architecture decision records, methodology notes,
database migrations, and commits. The result is written to
``docs/data/growth.json``, which the gallery draws from - a clone without the
git history (CI checks out one commit) can still draw the chart.

    python -m meridian.devtools.growth            # all tags plus the working tree as "next"
"""

from __future__ import annotations

import ast
import io
import json
import subprocess
import sys
import tarfile
from dataclasses import asdict, dataclass, fields
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUTPUT = ROOT / "docs" / "data" / "growth.json"
DAYS = {
    "v0.1.0": "Foundation",
    "v0.2.0": "Foundation",
    "v0.3.0": "Market data",
    "v0.4.0": "Accounting",
    "v0.5.0": "Performance",
    "v0.6.0": "Risk",
    "v0.7.0": "Compliance",
    "v0.8.0": "Optimisation",
    "v0.9.0": "Execution",
    "v1.0.0": "Platform",
    "v1.1.0": "Rates revisited",
}


@dataclass(frozen=True)
class Release:
    tag: str
    date: str
    module: str
    source_lines: int
    test_lines: int
    tests: int
    property_tests: int
    figures: int
    decisions: int
    notes: int
    migrations: int
    commits: int
    packages: int


def _git(*arguments: str) -> bytes:
    return subprocess.run(["git", *arguments], cwd=ROOT, check=True, capture_output=True).stdout


def _count_tests(text: str) -> tuple[int, int]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return 0, 0
    tests = properties = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith("test_"):
            tests += 1
            names = {ast.unparse(decorator).split("(")[0] for decorator in node.decorator_list}
            if any(name.endswith("given") for name in names):
                properties += 1
    return tests, properties


def measure(files: dict[str, str], tag: str, date: str, commits: int) -> Release:
    source = test = tests = properties = 0
    packages = set()
    for name, text in files.items():
        lines = sum(1 for line in text.splitlines() if line.strip())
        if name.startswith("src/meridian/") and name.endswith(".py"):
            source += lines
            parts = name.split("/")
            if len(parts) > 3:
                packages.add(parts[2])
        elif name.startswith("tests/") and name.endswith(".py"):
            test += lines
            found, props = _count_tests(text)
            tests += found
            properties += props
    return Release(
        tag=tag,
        date=date,
        module=DAYS.get(tag, "next"),
        source_lines=source,
        test_lines=test,
        tests=tests,
        property_tests=properties,
        figures=sum(1 for name in files if name.startswith("docs/images/") and name.endswith(".png")),
        decisions=sum(1 for name in files if name.startswith("docs/adr/0") and name.endswith(".md")),
        notes=sum(1 for name in files if name.startswith("docs/notes/") and name.endswith(".md")),
        migrations=sum(1 for name in files if name.startswith("alembic/versions/0") and name.endswith(".py")),
        commits=commits,
        packages=len(packages),
    )


def files_at(tag: str) -> dict[str, str]:
    """Every Python and Markdown file at a tag, with its text; every image, without its bytes."""
    output: dict[str, str] = {}
    with tarfile.open(fileobj=io.BytesIO(_git("archive", "--format=tar", tag))) as archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            if member.name.endswith(".png"):
                output[member.name] = ""
            elif member.name.endswith((".py", ".md")):
                handle = archive.extractfile(member)
                output[member.name] = "" if handle is None else handle.read().decode("utf-8", errors="replace")
    return output


def files_in_tree(root: Path = ROOT) -> dict[str, str]:
    tracked = _git("ls-files", "--cached", "--others", "--exclude-standard").decode().splitlines()
    output = {}
    for name in tracked:
        path = root / name
        if path.is_file() and name.endswith((".py", ".md", ".png")):
            output[name] = "" if name.endswith(".png") else path.read_text(encoding="utf-8", errors="replace")
    return output


def collect(next_tag: str = "v1.0.0") -> list[Release]:
    tags = _git("tag", "--sort=creatordate").decode().split()
    releases = []
    for tag in tags:
        date = _git("log", "-1", "--format=%ad", "--date=short", tag).decode().strip()
        commits = int(_git("rev-list", "--count", tag).decode())
        releases.append(measure(files_at(tag), tag, date, commits))
    if next_tag not in tags:
        date = _git("log", "-1", "--format=%ad", "--date=short", "HEAD").decode().strip()
        commits = int(_git("rev-list", "--count", "HEAD").decode())
        releases.append(measure(files_in_tree(), next_tag, date, commits))
    return releases


def load(path: Path = OUTPUT) -> list[Release]:
    names = {item.name for item in fields(Release)}
    return [
        Release(**{key: value for key, value in item.items() if key in names})
        for item in json.loads(path.read_text(encoding="utf-8"))
    ]


def collected_tests() -> int:
    """How many tests pytest collects in the working tree - parametrised cases counted one by one."""
    output = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    ).stdout
    return sum(1 for line in output.splitlines() if "::" in line)


def main() -> None:
    releases = collect()
    rows = [asdict(item) for item in releases]
    rows[-1]["collected"] = collected_tests()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    for item in releases:
        print(
            f"{item.tag:7s} {item.module:13s} src {item.source_lines:6,d}  tests {item.tests:5,d}  "
            f"figures {item.figures:4d}  adr {item.decisions:3d}",
            file=sys.stdout,
        )


if __name__ == "__main__":
    main()
