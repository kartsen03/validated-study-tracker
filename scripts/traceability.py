"""Trace every requirement to the tests that verify it.

Reads the numbered requirements in docs/requirements.md and the results of a test run
(pytest's JUnit XML). A test verifies REQ-NNN when its name starts with test_req_NNN_.
From these it writes the traceability matrix and, optionally, a test execution report
that adds the run's environment and coverage.

It exits with status 1 unless the run verified every requirement: that means a
requirement with no passing test, any failed test, a test that names a requirement
the document doesn't have, or (with --check) a committed matrix that no longer
matches the results.

    python scripts/traceability.py --junit reports/junit.xml            # regenerate the matrix
    python scripts/traceability.py --junit reports/junit.xml --check    # verify it, as CI does
"""

import argparse
import difflib
import platform
import re
import sys
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REQUIREMENTS = ROOT / "docs" / "requirements.md"
DEFAULT_MATRIX = ROOT / "docs" / "traceability_matrix.md"
PACKAGE = "validated-study-tracker"
REPORTED_PACKAGES = ("flask", "sqlalchemy", "pytest", "coverage")

REQUIREMENT_HEADING = re.compile(r"^\*\*(REQ-\d{3}) (.+?)\.\*\*[ \t]*$", re.MULTILINE)
TEST_REQUIREMENT = re.compile(r"^test_req_(\d{3})_")

PASS, FAIL, NOT_TESTED, NOT_VERIFIED = "Pass", "Fail", "Not tested", "Not verified"
# When pytest reports one case more than once (a failure, then an error in teardown),
# the worst outcome stands.
SEVERITY = {"passed": 0, "skipped": 1, "failed": 2, "error": 3}


@dataclass(frozen=True)
class Requirement:
    id: str
    title: str


@dataclass(frozen=True)
class Case:
    """One test case. A parametrized test function runs one case per parameter set."""

    module: str  # tests.test_status
    name: str  # test_req_008_status_transition[PLANNED->RECRUITING]
    outcome: str  # passed, failed, error or skipped

    @property
    def function(self) -> str:
        return self.name.split("[", 1)[0]

    @property
    def node(self) -> str:
        return f"{self.module.replace('.', '/')}.py::{self.name}"


@dataclass(frozen=True)
class Run:
    cases: list[Case]
    started: datetime | None


@dataclass(frozen=True)
class Coverage:
    lines_covered: int
    lines_valid: int
    branches_covered: int
    branches_valid: int


def read_requirements(path: Path) -> list[Requirement]:
    found = [Requirement(*match) for match in REQUIREMENT_HEADING.findall(path.read_text("utf-8"))]
    ids = [requirement.id for requirement in found]
    duplicates = sorted({rid for rid in ids if ids.count(rid) > 1})
    if duplicates:
        raise ValueError(f"{path.name} defines {', '.join(duplicates)} more than once")
    if not found:
        raise ValueError(f"{path.name} contains no requirements")
    return found


def read_junit(path: Path) -> Run:
    root = ET.parse(path).getroot()
    outcomes: dict[tuple[str, str], str] = {}
    for element in root.iter("testcase"):
        if element.find("error") is not None:
            outcome = "error"
        elif element.find("failure") is not None:
            outcome = "failed"
        elif element.find("skipped") is not None:
            outcome = "skipped"
        else:
            outcome = "passed"
        key = (element.get("classname", ""), element.get("name", ""))
        if key not in outcomes or SEVERITY[outcome] > SEVERITY[outcomes[key]]:
            outcomes[key] = outcome
    suite = next(root.iter("testsuite"), None)
    stamp = suite.get("timestamp") if suite is not None else None
    started = datetime.fromisoformat(stamp).astimezone(UTC) if stamp else None
    cases = [Case(module, name, outcome) for (module, name), outcome in outcomes.items()]
    return Run(cases, started)


def read_coverage(path: Path) -> Coverage:
    root = ET.parse(path).getroot()
    count = {
        key: int(root.get(key, "0"))
        for key in ("lines-covered", "lines-valid", "branches-covered", "branches-valid")
    }
    return Coverage(
        count["lines-covered"],
        count["lines-valid"],
        count["branches-covered"],
        count["branches-valid"],
    )


@dataclass
class Trace:
    requirements: list[Requirement]
    cases: list[Case]

    def __post_init__(self) -> None:
        known = {requirement.id for requirement in self.requirements}
        self.by_requirement: dict[str, list[Case]] = {rid: [] for rid in known}
        self.supporting: list[Case] = []
        self.unknown: list[tuple[Case, str]] = []
        for case in self.cases:
            match = TEST_REQUIREMENT.match(case.function)
            if match is None:
                self.supporting.append(case)
            elif (rid := f"REQ-{match.group(1)}") in known:
                self.by_requirement[rid].append(case)
            else:
                self.unknown.append((case, rid))

    def status(self, requirement: Requirement) -> str:
        outcomes = {case.outcome for case in self.by_requirement[requirement.id]}
        if not outcomes:
            return NOT_TESTED
        if outcomes & {"failed", "error"}:
            return FAIL
        return PASS if "passed" in outcomes else NOT_VERIFIED

    def verified(self) -> int:
        return sum(self.status(requirement) == PASS for requirement in self.requirements)

    def failed(self) -> list[Case]:
        return [case for case in self.cases if case.outcome in {"failed", "error"}]

    def problems(self) -> list[str]:
        problems = []
        if not self.cases:
            problems.append("the test results contain no test cases")
        for requirement in self.requirements:
            status = self.status(requirement)
            if status != PASS:
                reason = {
                    NOT_TESTED: "no test verifies it",
                    FAIL: "a test failed",
                    NOT_VERIFIED: "every test was skipped",
                }[status]
                problems.append(f"{requirement.id} {requirement.title}: {reason}")
        problems += [
            f"{case.node} names {rid}, which isn't in the requirements"
            for case, rid in self.unknown
        ]
        problems += [f"{case.outcome}: {case.node}" for case in self.failed()]
        return problems


def _functions(cases: list[Case]) -> dict[str, int]:
    """Test function name -> number of cases, sorted by name."""
    counts: dict[str, int] = {}
    for case in cases:
        counts[case.function] = counts.get(case.function, 0) + 1
    return dict(sorted(counts.items()))


def _table(trace: Trace) -> list[str]:
    rows = ["| Requirement | Title | Tests | Cases | Result |", "|---|---|---|---|---|"]
    for requirement in trace.requirements:
        functions = _functions(trace.by_requirement[requirement.id])
        tests = "<br>".join(
            f"`{name}`" + (f" ({count})" if count > 1 else "") for name, count in functions.items()
        )
        title = requirement.title.replace("|", "\\|")
        count = sum(functions.values())
        rows.append(
            f"| {requirement.id} | {title} | {tests or 'none'} | {count} "
            f"| {trace.status(requirement)} |"
        )
    return rows


def _supporting(trace: Trace) -> str:
    cases = trace.supporting
    modules = sorted({case.module.replace(".", "/") + ".py" for case in cases})
    failed = sum(case.outcome in {"failed", "error"} for case in cases)
    where = ", ".join(f"`{module}`" for module in modules) or "no files"
    state = f"{failed} failed." if failed else "All passed."
    return (
        f"{len(cases)} test cases in {len(_functions(cases))} test functions check behaviour "
        f"that isn't a numbered requirement ({where}). They run in the same suite and must "
        f"pass for the build to pass. {state}"
    )


def _summary(trace: Trace) -> str:
    traced = [case for cases in trace.by_requirement.values() for case in cases]
    return (
        f"**{trace.verified()} of {len(trace.requirements)} requirements verified** by "
        f"{len(traced)} test cases in {len(_functions(traced))} test functions."
    )


def render_matrix(trace: Trace) -> str:
    lines = [
        "# Requirements traceability matrix",
        "",
        "Generated by [`scripts/traceability.py`](../scripts/traceability.py) from the",
        "[requirements](requirements.md) and the results of a full test run. A test verifies",
        "the requirement its name starts with: `test_req_008_...` verifies REQ-008, and a",
        "number in brackets counts the cases a parametrized test runs. Don't edit this file",
        "by hand. CI regenerates it on every push and fails if it is out of date or if any",
        "requirement lacks a passing test.",
        "",
        _summary(trace),
        "",
        *_table(trace),
        "",
        "## Supporting tests",
        "",
        _supporting(trace),
        "",
    ]
    return "\n".join(lines)


def _percent(covered: int, valid: int) -> str:
    return f"{100 * covered / valid:.1f}%" if valid else "n/a"


def _installed(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "not installed"


def render_report(
    trace: Trace,
    run: Run,
    problems: list[str],
    *,
    coverage: Coverage | None,
    commit: str | None,
    release: str | None,
) -> str:
    total = len(trace.cases)
    passed = sum(case.outcome == "passed" for case in trace.cases)
    skipped = sum(case.outcome == "skipped" for case in trace.cases)
    result = "PASS" if not problems else "FAIL"
    outcome = f"**{result}**: {passed} of {total} test cases passed"
    if skipped:
        outcome += f", {skipped} skipped"
    executed = run.started.strftime("%Y-%m-%d %H:%M:%S UTC") if run.started else "unknown"
    measured = (
        f"{_percent(coverage.lines_covered, coverage.lines_valid)} of lines "
        f"({coverage.lines_covered} of {coverage.lines_valid}), "
        f"{_percent(coverage.branches_covered, coverage.branches_valid)} of branches "
        f"({coverage.branches_covered} of {coverage.branches_valid})"
        if coverage
        else "not measured"
    )
    packages = ", ".join(f"{name} {_installed(name)}" for name in REPORTED_PACKAGES)
    lines = [
        f"# Test execution report: {release or 'CI run'}",
        "",
        "| | |",
        "|---|---|",
        f"| Software | Validated Study Tracker {_installed(PACKAGE)} |",
        f"| Release | {release or 'none (not a tagged release)'} |",
        f"| Commit | `{commit or 'unknown'}` |",
        f"| Executed | {executed} |",
        f"| Environment | {platform.platform()}, Python {platform.python_version()} |",
        f"| Packages | {packages} |",
        f"| Result | {outcome} |",
        f"| Requirements | {trace.verified()} of {len(trace.requirements)} verified by at least "
        f"one passing test |",
        f"| Coverage | {measured} |",
        "",
        "## Requirements traceability",
        "",
        _summary(trace),
        "",
        *_table(trace),
        "",
        "## Supporting tests",
        "",
        _supporting(trace),
        "",
    ]
    if problems:
        lines += ["## Problems", "", *[f"- {problem}" for problem in problems], ""]
    return "\n".join(lines)


def _display(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Trace requirements to the tests that verify them."
    )
    parser.add_argument("--junit", type=Path, required=True, help="pytest's JUnit XML results")
    parser.add_argument("--requirements", type=Path, default=DEFAULT_REQUIREMENTS)
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument(
        "--check",
        action="store_true",
        help="compare the results with the committed matrix instead of writing it",
    )
    parser.add_argument("--report", type=Path, help="also write a test execution report here")
    parser.add_argument("--coverage", type=Path, help="coverage XML to include in the report")
    parser.add_argument("--commit", help="the commit that was tested")
    parser.add_argument("--release", help="the release tag, which must match the package version")
    parser.add_argument(
        "--summary", type=Path, help="append the result to this file (GitHub's job summary)"
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    run = read_junit(args.junit)
    trace = Trace(read_requirements(args.requirements), run.cases)
    problems = trace.problems()

    matrix = render_matrix(trace)
    if args.check:
        committed = args.matrix.read_text("utf-8") if args.matrix.exists() else ""
        if committed.replace("\r\n", "\n") != matrix:
            name = _display(args.matrix)
            diff = difflib.unified_diff(
                committed.splitlines(),
                matrix.splitlines(),
                f"{name} (committed)",
                f"{name} (this run)",
                lineterm="",
            )
            print("\n".join(diff), file=sys.stderr)
            problems.append(
                f"{name} is out of date. Regenerate it with "
                "`python scripts/traceability.py --junit <results>` and commit it."
            )
    else:
        _write(args.matrix, matrix)

    output = matrix
    if args.report:
        installed = _installed(PACKAGE)
        if args.release and args.release != f"v{installed}":
            problems.append(
                f"release tag {args.release} doesn't match the package version {installed}"
            )
        coverage = read_coverage(args.coverage) if args.coverage else None
        output = render_report(
            trace, run, problems, coverage=coverage, commit=args.commit, release=args.release
        )
        _write(args.report, output)
    if args.summary:
        with args.summary.open("a", encoding="utf-8") as handle:
            handle.write(output + "\n")

    for problem in problems:
        print(f"error: {problem}", file=sys.stderr)
    if problems:
        return 1
    print(
        f"{trace.verified()} of {len(trace.requirements)} requirements verified by "
        f"{len(trace.cases) - len(trace.supporting)} test cases; "
        f"{len(trace.supporting)} supporting test cases also passed."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
