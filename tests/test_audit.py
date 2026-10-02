"""REQ-011 to REQ-015: the audit trail, atomic changes, and deletion."""

import re
import sqlite3
from datetime import UTC, datetime

import pytest
from helpers import STUDY_ID, VALID_STUDY
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

import study_tracker.audit
from study_tracker.db import get_session
from study_tracker.models import AuditEntry, AuditTrailViolation

UTC_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z")


def parse_utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


# REQ-011 Audit entry content ----------------------------------------------------------


def test_req_011_creating_a_study_writes_one_entry_per_field(browser, db):
    browser.create()
    entries = db.audit()
    assert [entry["field"] for entry in entries] == [
        "study_id",
        "title",
        "phase",
        "sponsor",
        "target_enrollment",
        "site_count",
        "status",
    ]
    assert {entry["action"] for entry in entries} == {"CREATE"}
    assert {entry["old_value"] for entry in entries} == {None}
    assert [entry["new_value"] for entry in entries] == [
        STUDY_ID,
        VALID_STUDY["title"],
        "Phase 2",
        VALID_STUDY["sponsor"],
        "120",
        "8",
        "PLANNED",
    ]
    assert {entry["username"] for entry in entries} == {"a.rivera"}


def test_req_011_an_edit_writes_entries_only_for_changed_fields(browser, db):
    browser.create()
    browser.edit(title="Revised title", site_count="9", reason="Sites added.")
    entries = db.audit()[7:]
    assert [
        (e["action"], e["field"], e["old_value"], e["new_value"], e["reason"]) for e in entries
    ] == [
        ("UPDATE", "title", VALID_STUDY["title"], "Revised title", "Sites added."),
        ("UPDATE", "site_count", "8", "9", "Sites added."),
    ]


def test_req_011_a_status_change_writes_one_entry(browser, db):
    browser.create()
    browser.change_status("RECRUITING", reason="First site activated.")
    entries = db.audit()[7:]
    assert [
        (e["action"], e["field"], e["old_value"], e["new_value"], e["reason"]) for e in entries
    ] == [
        ("STATUS", "status", "PLANNED", "RECRUITING", "First site activated."),
    ]


def test_req_011_a_deletion_writes_one_entry_for_the_whole_study(browser, db):
    browser.create()
    browser.delete(reason="Duplicate of another record.")
    entries = db.audit()[7:]
    assert [
        (e["action"], e["field"], e["old_value"], e["new_value"], e["reason"]) for e in entries
    ] == [
        ("DELETE", None, None, None, "Duplicate of another record."),
    ]


def test_req_011_entries_record_the_user_and_a_utc_time(browser, db):
    browser.create()
    started = datetime.now(UTC)
    browser.edit(title="Revised title")
    finished = datetime.now(UTC)
    entry = db.audit()[-1]
    assert entry["username"] == "a.rivera"
    assert UTC_TIMESTAMP.fullmatch(entry["recorded_at"])
    assert started <= parse_utc(entry["recorded_at"]) <= finished


def test_req_011_the_timestamp_is_set_by_the_server(browser, db):
    browser.create()
    browser.edit(title="Revised title", recorded_at="1999-01-01T00:00:00.000000Z")
    assert db.audit()[-1]["recorded_at"] > "2020"


def test_req_011_entries_from_one_change_share_a_timestamp(browser, db):
    browser.create()
    assert len({entry["recorded_at"] for entry in db.audit()}) == 1


def test_req_011_an_edit_that_changes_nothing_is_refused_and_writes_nothing(browser, db):
    browser.create()
    before = db.snapshot()
    response = browser.edit()
    assert response.status_code == 409
    assert "Nothing was changed" in response.text
    assert db.snapshot() == before


# REQ-012 The audit trail is append-only -----------------------------------------------


def test_req_012_database_rejects_updating_an_audit_entry(browser, db):
    browser.create()
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.execute("UPDATE audit_entries SET reason = 'rewritten'")
    assert {entry["reason"] for entry in db.audit()} == {None}


def test_req_012_database_rejects_deleting_an_audit_entry(browser, db):
    browser.create()
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.execute("DELETE FROM audit_entries")
    assert len(db.audit()) == 7


def test_req_012_the_application_refuses_to_modify_an_audit_entry(app, browser):
    browser.create()
    with app.app_context():
        session = get_session()
        entry = session.scalars(select(AuditEntry)).first()
        entry.reason = "rewritten"
        with pytest.raises(AuditTrailViolation):
            session.commit()
        session.rollback()


def test_req_012_the_application_refuses_to_delete_an_audit_entry(app, browser):
    browser.create()
    with app.app_context():
        session = get_session()
        session.delete(session.scalars(select(AuditEntry)).first())
        with pytest.raises(AuditTrailViolation):
            session.commit()
        session.rollback()


def test_req_012_no_route_accepts_changes_to_the_audit_trail(app):
    audit_routes = [rule for rule in app.url_map.iter_rules() if "audit" in rule.rule]
    assert audit_routes
    for rule in audit_routes:
        assert rule.methods <= {"GET", "HEAD", "OPTIONS"}


def test_req_012_the_audit_module_has_no_way_to_change_entries():
    public = {name for name in dir(study_tracker.audit) if not name.startswith("_")}
    assert not {
        name
        for name in public
        if re.search("update|delete|modify|remove|edit", name, re.I)
        and name not in {"UPDATE", "DELETE"}
    }


# REQ-013 Audit history view -----------------------------------------------------------


def test_req_013_history_lists_every_entry_oldest_first(browser, db):
    browser.create()
    browser.edit(title="Revised title", reason="Title clarified.")
    browser.change_status("RECRUITING", reason="First site activated.")
    page = browser.get(f"/studies/{STUDY_ID}/audit").text
    entries = db.audit()
    positions = [page.index(f'id="entry-{entry["id"]}"') for entry in entries]
    assert positions == sorted(positions)
    for entry in entries:
        for value in (entry["recorded_at"], entry["username"], entry["action"]):
            assert value in page
    for text in ("Title clarified.", "First site activated.", "Revised title", "RECRUITING"):
        assert text in page


def test_req_013_history_of_a_deleted_study_is_still_available(browser):
    browser.create()
    browser.delete(reason="Entered in error.")
    response = browser.get(f"/studies/{STUDY_ID}/audit")
    assert response.status_code == 200
    assert "This study has been deleted." in response.text
    assert "Entered in error." in response.text


def test_req_013_history_of_an_unknown_study_is_not_found(browser):
    assert browser.get("/studies/NO-SUCH-1/audit").status_code == 404


# REQ-014 A change and its audit entries are saved together ----------------------------

OPERATIONS = {
    "create": lambda browser: browser.create(study_id="NEW-2026-002"),
    "edit": lambda browser: browser.edit(title="Should not be saved"),
    "status": lambda browser: browser.change_status("RECRUITING"),
    "delete": lambda browser: browser.delete(),
}


@pytest.mark.parametrize("operation", list(OPERATIONS))
def test_req_014_if_the_audit_write_fails_the_change_is_not_saved(browser, db, operation):
    browser.create()
    before = db.snapshot()
    # Make the database itself refuse audit entries, after the change has been sent.
    db.execute(
        "CREATE TRIGGER simulate_audit_failure BEFORE INSERT ON audit_entries"
        " BEGIN SELECT RAISE(ABORT, 'simulated audit failure'); END"
    )
    with pytest.raises(IntegrityError, match="simulated audit failure"):
        OPERATIONS[operation](browser)
    assert db.snapshot() == before


def test_req_014_an_error_while_recording_rolls_the_change_back(browser, db, monkeypatch):
    browser.create()
    before = db.snapshot()

    def fail(*args, **kwargs):
        raise RuntimeError("audit service unavailable")

    monkeypatch.setattr(study_tracker.audit, "record", fail)
    with pytest.raises(RuntimeError, match="audit service unavailable"):
        browser.edit(title="Should not be saved")
    assert db.snapshot() == before


# REQ-015 Deleting a study keeps its history -------------------------------------------


def test_req_015_a_deleted_study_leaves_the_list(browser):
    browser.create()
    browser.create(study_id="KEEP-001", title="A study that stays")
    assert browser.delete().status_code == 302
    page = browser.get("/studies").text
    # The confirmation message names the deleted study, so look for its row's link.
    assert f'href="/studies/{STUDY_ID}"' not in page
    assert 'href="/studies/KEEP-001"' in page


def test_req_015_a_deleted_study_can_no_longer_be_opened_or_changed(browser, db):
    browser.create()
    browser.delete()
    before = db.snapshot()
    assert browser.get(f"/studies/{STUDY_ID}").status_code == 404
    assert browser.edit(title="x").status_code == 404
    assert browser.change_status("RECRUITING").status_code == 404
    assert browser.delete().status_code == 404
    assert db.snapshot() == before


def test_req_015_history_is_kept_and_ends_with_the_deletion(browser, db):
    browser.create()
    browser.delete(reason="Duplicate record.")
    entries = db.audit()
    assert len(entries) == 8
    assert (entries[-1]["action"], entries[-1]["reason"]) == ("DELETE", "Duplicate record.")


def test_req_015_database_keeps_the_row_and_refuses_to_remove_it(browser, db):
    browser.create()
    browser.delete()
    assert db.study()["deleted_at"] is not None
    with pytest.raises(sqlite3.IntegrityError, match="never removed"):
        db.execute("DELETE FROM studies")
    with pytest.raises(sqlite3.IntegrityError, match="deleted study cannot be changed"):
        db.execute("UPDATE studies SET title = 'resurrected'")
