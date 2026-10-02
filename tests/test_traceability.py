"""The traceability tool (scripts/traceability.py), run against small hand-written inputs.

These are supporting tests: they check the tool that checks the requirements."""

import runpy
from importlib.metadata import version
from xml.sax.saxutils import quoteattr

import pytest
import traceability
from helpers import ROOT

REQUIREMENTS = """# User requirements

**REQ-001 Create a study.**
A user can create a study.

**REQ-002 Required fields.**
Every field is required.
"""

CHILD = {
    "passed": "",
    "failed": '<failure message="assert 1 == 2" />',
    "error": '<error message="fixture failed" />',
    "skipped": '<skipped message="not yet" />',
}


def junit(*cases: tuple[str, str], timestamp="2026-10-01T09:30:00.000000-04:00") -> str:
    """JUnit XML shaped like pytest's. Each case is (name, outcome)."""
    body = "".join(
        f'<testcase classname="tests.test_example" name={quoteattr(name)} time="0.01">'
        f"{CHILD[outcome]}</testcase>"
        for name, outcome in cases
    )
    return (
        '<?xml version="1.0" encoding="utf-8"?><testsuites name="pytest tests">'
        f'<testsuite name="pytest" timestamp="{timestamp}">{body}</testsuite></testsuites>'
    )


COVERAGE = (
    '<?xml version="1.0" ?><coverage lines-valid="200" lines-covered="190" '
    'branches-valid="40" branches-covered="36" line-rate="0.95" branch-rate="0.9"></coverage>'
)

COMPLETE = [
    ("test_req_001_creates_a_study", "passed"),
    ("test_req_002_rejects_a_missing_field[title]", "passed"),
    ("test_req_002_rejects_a_missing_field[phase]", "passed"),
    ("test_req_002_rejects_a_missing_field[sponsor]", "passed"),
    ("test_index_redirects", "passed"),
]


@pytest.fixture
def tool(tmp_path, capsys):
    """Run the tool on given results; returns (exit status, stdout, stderr, paths)."""
    requirements = tmp_path / "requirements.md"
    requirements.write_text(REQUIREMENTS, encoding="utf-8")
    paths = {
        "junit": tmp_path / "junit.xml",
        "matrix": tmp_path / "docs" / "matrix.md",
        "report": tmp_path / "report.md",
        "coverage": tmp_path / "coverage.xml",
        "summary": tmp_path / "summary.md",
    }
    paths["coverage"].write_text(COVERAGE, encoding="utf-8")

    def run(cases, *options, timestamp="2026-10-01T09:30:00.000000-04:00"):
        paths["junit"].write_text(junit(*cases, timestamp=timestamp), encoding="utf-8")
        status = traceability.main(
            [
                "--junit",
                str(paths["junit"]),
                "--requirements",
                str(requirements),
                "--matrix",
                str(paths["matrix"]),
                *options,
            ]
        )
        out, err = capsys.readouterr()
        return status, out, err, paths

    return run


def text(path) -> str:
    return path.read_text(encoding="utf-8")


def test_traces_every_requirement_and_writes_the_matrix(tool):
    status, out, err, paths = tool(COMPLETE)
    assert status == 0, err
    matrix = text(paths["matrix"])
    assert "**2 of 2 requirements verified** by 4 test cases in 2 test functions." in matrix
    assert "| REQ-001 | Create a study | `test_req_001_creates_a_study` | 1 | Pass |" in matrix
    assert (
        "| REQ-002 | Required fields | `test_req_002_rejects_a_missing_field` (3) | 3 | Pass |"
        in matrix
    )
    assert "1 test cases in 1 test functions" in matrix
    assert "`tests/test_example.py`" in matrix
    assert "2 of 2 requirements verified by 4 test cases" in out


def test_matrix_is_written_with_lf_line_endings(tool):
    _, _, _, paths = tool(COMPLETE)
    assert b"\r\n" not in paths["matrix"].read_bytes()


def test_a_requirement_without_tests_fails_the_run(tool):
    status, _, err, paths = tool(COMPLETE[:1] + COMPLETE[4:])
    assert status == 1
    assert "REQ-002 Required fields: no test verifies it" in err
    assert "| REQ-002 | Required fields | none | 0 | Not tested |" in text(paths["matrix"])
    assert "**1 of 2 requirements verified**" in text(paths["matrix"])


@pytest.mark.parametrize("outcome", ["failed", "error"])
def test_a_failed_case_fails_its_requirement_and_the_run(tool, outcome):
    cases = [*COMPLETE[:2], ("test_req_002_rejects_a_missing_field[phase]", outcome)]
    status, _, err, paths = tool(cases)
    assert status == 1
    assert "REQ-002 Required fields: a test failed" in err
    assert f"{outcome}: tests/test_example.py::test_req_002_rejects_a_missing_field[phase]" in err
    assert "| 2 | Fail |" in text(paths["matrix"])


def test_a_requirement_whose_tests_were_all_skipped_is_not_verified(tool):
    cases = [COMPLETE[0], ("test_req_002_rejects_a_missing_field[title]", "skipped")]
    status, _, err, paths = tool(cases)
    assert status == 1
    assert "REQ-002 Required fields: every test was skipped" in err
    assert "| Not verified |" in text(paths["matrix"])


def test_a_skipped_case_alongside_passing_ones_still_verifies(tool):
    status, _, err, _ = tool([*COMPLETE, ("test_req_002_rejects_a_missing_field[x]", "skipped")])
    assert status == 0, err


def test_a_failing_supporting_test_fails_the_run(tool):
    status, _, err, paths = tool([*COMPLETE[:4], ("test_index_redirects", "failed")])
    assert status == 1
    assert "failed: tests/test_example.py::test_index_redirects" in err
    assert "1 failed." in text(paths["matrix"])


def test_a_test_naming_an_unknown_requirement_fails_the_run(tool):
    status, _, err, _ = tool([*COMPLETE, ("test_req_099_something", "passed")])
    assert status == 1
    assert "test_req_099_something names REQ-099, which isn't in the requirements" in err


@pytest.mark.parametrize("error_first", [False, True], ids=["error-last", "error-first"])
def test_a_case_reported_twice_keeps_its_worst_outcome(tool, error_first):
    # pytest reports a test twice when it passes but then errors in teardown.
    reports = [
        ("test_req_001_creates_a_study", "passed"),
        ("test_req_001_creates_a_study", "error"),
    ]
    if error_first:
        reports.reverse()
    status, _, err, paths = tool([*reports, *COMPLETE[1:]])
    assert status == 1
    assert "error: tests/test_example.py::test_req_001_creates_a_study" in err
    assert "| REQ-001 | Create a study | `test_req_001_creates_a_study` | 1 | Fail |" in text(
        paths["matrix"]
    )


def test_results_with_no_test_cases_fail(tool):
    status, _, err, _ = tool([])
    assert status == 1
    assert "the test results contain no test cases" in err


def test_check_passes_when_the_committed_matrix_matches(tool):
    tool(COMPLETE)
    status, _, err, _ = tool(COMPLETE, "--check")
    assert status == 0, err


def test_check_accepts_a_matrix_checked_out_with_crlf_endings(tool):
    _, _, _, paths = tool(COMPLETE)
    paths["matrix"].write_bytes(paths["matrix"].read_bytes().replace(b"\n", b"\r\n"))
    assert tool(COMPLETE, "--check")[0] == 0


def test_check_fails_with_a_diff_when_the_matrix_is_stale_and_leaves_it_alone(tool):
    _, _, _, paths = tool(COMPLETE[:3] + COMPLETE[4:])
    stale = text(paths["matrix"])
    status, _, err, _ = tool(COMPLETE, "--check")
    assert status == 1
    assert "is out of date. Regenerate it with" in err
    assert (
        "-| REQ-002 | Required fields | `test_req_002_rejects_a_missing_field` (2) | 2 | Pass |"
        in err
    )
    assert (
        "+| REQ-002 | Required fields | `test_req_002_rejects_a_missing_field` (3) | 3 | Pass |"
        in err
    )
    assert text(paths["matrix"]) == stale


def test_check_fails_when_there_is_no_committed_matrix(tool):
    status, _, err, paths = tool(COMPLETE, "--check")
    assert status == 1
    assert "is out of date" in err
    assert not paths["matrix"].exists()


def test_report_records_the_run(tool, tmp_path):
    release = f"v{version('validated-study-tracker')}"
    status, _, err, paths = tool(
        COMPLETE,
        "--report",
        str(tmp_path / "report.md"),
        "--coverage",
        str(tmp_path / "coverage.xml"),
        "--commit",
        "0123abc",
        "--release",
        release,
    )
    assert status == 0, err
    report = text(paths["report"])
    assert f"# Test execution report: {release}" in report
    assert "| Commit | `0123abc` |" in report
    # The suite's timestamp, converted to UTC.
    assert "| Executed | 2026-10-01 13:30:00 UTC |" in report
    assert "| Result | **PASS**: 5 of 5 test cases passed |" in report
    assert "| Requirements | 2 of 2 verified by at least one passing test |" in report
    assert "| Coverage | 95.0% of lines (190 of 200), 90.0% of branches (36 of 40) |" in report
    assert "Python " in report
    assert "flask " in report
    assert "## Problems" not in report


def test_report_without_optional_details_says_so(tool, tmp_path):
    cases = [*COMPLETE, ("test_req_002_rejects_a_missing_field[x]", "skipped")]
    status, _, _, paths = tool(cases, "--report", str(tmp_path / "report.md"), timestamp="")
    assert status == 0
    report = text(paths["report"])
    assert "# Test execution report: CI run" in report
    assert "| Release | none (not a tagged release) |" in report
    assert "| Commit | `unknown` |" in report
    assert "| Executed | unknown |" in report
    assert "| Coverage | not measured |" in report
    assert "5 of 6 test cases passed, 1 skipped" in report


def test_report_lists_problems_and_fails(tool, tmp_path):
    status, _, _, paths = tool(COMPLETE[:1], "--report", str(tmp_path / "report.md"))
    assert status == 1
    report = text(paths["report"])
    assert "| Result | **FAIL**: 1 of 1 test cases passed |" in report
    assert "## Problems\n\n- REQ-002 Required fields: no test verifies it" in report


def test_a_release_tag_must_match_the_package_version(tool, tmp_path):
    status, _, err, _ = tool(
        COMPLETE, "--report", str(tmp_path / "report.md"), "--release", "v0.0.1"
    )
    assert status == 1
    assert "release tag v0.0.1 doesn't match the package version" in err


def test_result_is_appended_to_the_job_summary(tool, tmp_path):
    summary = tmp_path / "summary.md"
    summary.write_text("earlier step\n", encoding="utf-8")
    tool(COMPLETE, "--summary", str(summary))
    assert text(summary).startswith("earlier step\n# Requirements traceability matrix")


def test_job_summary_gets_the_report_when_one_is_written(tool, tmp_path):
    summary = tmp_path / "summary.md"
    tool(COMPLETE, "--report", str(tmp_path / "report.md"), "--summary", str(summary))
    assert text(summary).startswith("# Test execution report")


def test_the_requirements_document_defines_req_001_to_req_015_in_order():
    ids = [
        requirement.id
        for requirement in traceability.read_requirements(traceability.DEFAULT_REQUIREMENTS)
    ]
    assert ids == [f"REQ-{number:03d}" for number in range(1, 16)]


def test_a_requirement_id_defined_twice_is_rejected(tmp_path):
    path = tmp_path / "requirements.md"
    path.write_text(REQUIREMENTS + "\n**REQ-001 Create a study again.**\n", encoding="utf-8")
    with pytest.raises(ValueError, match="defines REQ-001 more than once"):
        traceability.read_requirements(path)


def test_a_document_without_requirements_is_rejected(tmp_path):
    path = tmp_path / "requirements.md"
    path.write_text("# Nothing here\n", encoding="utf-8")
    with pytest.raises(ValueError, match="contains no requirements"):
        traceability.read_requirements(path)


def test_report_details_degrade_gracefully():
    assert traceability._installed("no-such-package-for-this-test") == "not installed"
    # A coverage run without branch measurement reports zero branches.
    assert traceability._percent(0, 0) == "n/a"


def test_paths_outside_the_repository_are_shown_in_full(tmp_path):
    assert traceability._display(tmp_path / "x.md") == str(tmp_path / "x.md")
    assert traceability._display(ROOT / "docs" / "x.md") == "docs/x.md"


def test_runs_as_a_command(tmp_path, monkeypatch, capsys):
    results = tmp_path / "junit.xml"
    results.write_text(junit(*COMPLETE), encoding="utf-8")
    requirements = tmp_path / "requirements.md"
    requirements.write_text(REQUIREMENTS, encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "traceability.py",
            "--junit",
            str(results),
            "--requirements",
            str(requirements),
            "--matrix",
            str(tmp_path / "matrix.md"),
        ],
    )
    with pytest.raises(SystemExit) as exited:
        runpy.run_path(str(ROOT / "scripts" / "traceability.py"), run_name="__main__")
    assert exited.value.code == 0
    assert "2 of 2 requirements verified" in capsys.readouterr().out
