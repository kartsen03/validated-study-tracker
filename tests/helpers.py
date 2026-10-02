"""Shared test helpers.

Expected behaviour comes from docs/requirements.md, not from the application's own
constants: if a test imported the implementation's transition table, a wrong table
would pass its own tests.
"""

import contextlib
import html
import sqlite3
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = ROOT / "docs" / "requirements.md"

STUDY_ID = "MP-2026-001"
VALID_STUDY = {
    "study_id": STUDY_ID,
    "title": "Phase 2 study of an oral JAK inhibitor in moderate ulcerative colitis",
    "phase": "Phase 2",
    "sponsor": "Example Biosciences",
    "target_enrollment": "120",
    "site_count": "8",
}
EDITABLE = ("title", "phase", "sponsor", "target_enrollment", "site_count")

# Field names as the requirements and the UI use them.
LABELS = {
    "study_id": "Study ID",
    "title": "Title",
    "phase": "Phase",
    "sponsor": "Sponsor",
    "target_enrollment": "Target enrollment",
    "site_count": "Site count",
}
PHASES = (
    "Early Phase 1",
    "Phase 1",
    "Phase 1/2",
    "Phase 2",
    "Phase 2/3",
    "Phase 3",
    "Phase 4",
    "Not applicable",
)

_UNSET = object()


def shown(response) -> str:
    """The page as a person reads it. Jinja escapes values it renders (an apostrophe
    arrives as &#39;), so messages are compared after decoding entities."""
    return html.unescape(response.get_data(as_text=True))


def _transition_table() -> dict[str, set[str]]:
    """The REQ-008 table, read from the requirements document, keyed by status code."""
    text = REQUIREMENTS.read_text(encoding="utf-8")
    section = text.split("**REQ-008", 1)[1].split("**REQ-009", 1)[0]
    code = {
        "Planned": "PLANNED",
        "Recruiting": "RECRUITING",
        "Active not recruiting": "ACTIVE_NOT_RECRUITING",
        "Suspended": "SUSPENDED",
        "Completed": "COMPLETED",
        "Terminated": "TERMINATED",
        "Withdrawn": "WITHDRAWN",
    }
    table: dict[str, set[str]] = {}
    for line in section.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells[0] == "From" or set(cells[0]) <= {"-"}:
            continue
        targets = set() if cells[1] == "none" else {code[t.strip()] for t in cells[1].split(",")}
        for source in cells[0].split(","):
            table[code[source.strip()]] = targets
    assert set(table) == set(code.values()), "REQ-008 table must list every status"
    return table


SPEC_TRANSITIONS = _transition_table()
STATUSES = tuple(SPEC_TRANSITIONS)
FINAL_STATUSES = tuple(status for status, targets in SPEC_TRANSITIONS.items() if not targets)


def path_from_planned(target: str) -> list[str]:
    """The shortest series of allowed status changes from Planned to `target`."""
    previous: dict[str, str | None] = {"PLANNED": None}
    queue = deque(["PLANNED"])
    while queue:
        current = queue.popleft()
        for nxt in sorted(SPEC_TRANSITIONS[current]):
            if nxt not in previous:
                previous[nxt] = current
                queue.append(nxt)
    steps: list[str] = []
    status: str | None = target
    while status != "PLANNED":
        steps.append(status)
        status = previous[status]
    return steps[::-1]


class Browser:
    """The test client as a person uses it: every form carries the session's CSRF token."""

    def __init__(self, client):
        self.client = client

    def token(self) -> str:
        with self.client.session_transaction() as session:
            return session.setdefault("csrf_token", "test-csrf-token")

    def get(self, path, **kwargs):
        return self.client.get(path, **kwargs)

    def post(self, path, data=None, **kwargs):
        return self.client.post(path, data={"csrf_token": self.token(), **(data or {})}, **kwargs)

    def sign_in(self, username: str = "a.rivera") -> "Browser":
        response = self.post("/sign-in", data={"username": username})
        assert response.status_code == 302, response.text
        return self

    def create(self, **overrides):
        return self.post("/studies/new", data={**VALID_STUDY, **overrides})

    # `of` names the study in the URL. It isn't called study_id because study_id is also
    # a form field, and tests need to be able to submit one (REQ-004).

    def edit(self, of: str = STUDY_ID, reason=_UNSET, **overrides):
        form = {field: VALID_STUDY[field] for field in EDITABLE} | overrides
        if reason is _UNSET:
            reason = "Correcting the record."
        if reason is not None:
            form["reason"] = reason
        return self.post(f"/studies/{of}/edit", data=form)

    def change_status(self, status: str, of: str = STUDY_ID, reason=_UNSET):
        form = {"status": status}
        if reason is _UNSET:
            reason = "Lifecycle update."
        if reason is not None:
            form["reason"] = reason
        return self.post(f"/studies/{of}/status", data=form)

    def delete(self, of: str = STUDY_ID, reason=_UNSET):
        form = {}
        if reason is _UNSET:
            reason = "Entered in error."
        if reason is not None:
            form["reason"] = reason
        return self.post(f"/studies/{of}/delete", data=form)

    def bring_to(self, status: str, of: str = STUDY_ID) -> None:
        for step in path_from_planned(status):
            response = self.change_status(step, of)
            assert response.status_code == 302, response.text


class Database:
    """Reads and writes the database file directly, independently of the application."""

    def __init__(self, path: str):
        self.path = path

    def rows(self, sql: str, params: tuple = ()) -> list[dict]:
        with contextlib.closing(sqlite3.connect(self.path)) as connection:
            connection.row_factory = sqlite3.Row
            return [dict(row) for row in connection.execute(sql, params)]

    def execute(self, sql: str, params: tuple = ()) -> None:
        with contextlib.closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute(sql, params)

    def study(self, study_id: str = STUDY_ID) -> dict | None:
        found = self.rows("SELECT * FROM studies WHERE study_id = ?", (study_id,))
        return found[0] if found else None

    def audit(self, study_id: str = STUDY_ID) -> list[dict]:
        return self.rows("SELECT * FROM audit_entries WHERE study_id = ? ORDER BY id", (study_id,))

    def count(self, table: str) -> int:
        """Rows in a table. `table` is always a literal name written in a test."""
        return self.rows(f"SELECT COUNT(*) AS n FROM {table}")[0]["n"]

    def snapshot(self) -> tuple[list[dict], list[dict]]:
        """Every study and every audit entry, for asserting that nothing changed."""
        return (
            self.rows("SELECT * FROM studies ORDER BY id"),
            self.rows("SELECT * FROM audit_entries ORDER BY id"),
        )
