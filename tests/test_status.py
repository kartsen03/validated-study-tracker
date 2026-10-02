"""REQ-008 and REQ-009: the status lifecycle.

Every one of the 49 possible (from, to) pairs is tested against the table in the
requirements document.
"""

import sqlite3

import pytest
from helpers import FINAL_STATUSES, SPEC_TRANSITIONS, STATUSES, STUDY_ID, shown

from study_tracker.lifecycle import TRANSITIONS

PAIRS = [(current, target) for current in STATUSES for target in STATUSES]


# REQ-008 Allowed status transitions ---------------------------------------------------


@pytest.mark.parametrize(("current", "target"), PAIRS, ids=[f"{a}->{b}" for a, b in PAIRS])
def test_req_008_status_transition(browser, db, current, target):
    browser.create()
    browser.bring_to(current)
    entries_before = len(db.audit())

    response = browser.change_status(target)

    if target in SPEC_TRANSITIONS[current]:
        assert response.status_code == 302, response.text
        assert db.study()["status"] == target
        assert len(db.audit()) == entries_before + 1
    else:
        assert response.status_code == 409
        assert db.study()["status"] == current
        assert len(db.audit()) == entries_before


def test_req_008_lifecycle_in_the_code_matches_the_requirements_document():
    assert {
        str(status): {str(t) for t in targets} for status, targets in TRANSITIONS.items()
    } == SPEC_TRANSITIONS


def test_req_008_rejection_lists_the_allowed_statuses(browser):
    browser.create()
    response = browser.change_status("COMPLETED")
    assert response.status_code == 409
    assert "A study can't go from Planned to Completed." in shown(response)
    assert "From Planned it can go to: Recruiting, Withdrawn." in shown(response)


def test_req_008_an_unknown_status_is_rejected(browser, db):
    browser.create()
    response = browser.change_status("FINISHED")
    assert response.status_code == 400
    assert "Choose the new status." in response.text
    assert db.study()["status"] == "PLANNED"


def test_req_008_study_page_offers_only_the_allowed_statuses(browser):
    browser.create()
    page = browser.get(f"/studies/{STUDY_ID}").text
    offered = {status for status in STATUSES if f'<option value="{status}">' in page}
    assert offered == SPEC_TRANSITIONS["PLANNED"]


def test_req_008_database_rejects_a_transition_outside_the_table(browser, db):
    browser.create()
    with pytest.raises(sqlite3.IntegrityError, match="status transition not allowed"):
        db.execute("UPDATE studies SET status = 'COMPLETED'")


def test_req_008_lifecycle_table_in_the_database_cannot_be_altered(db):
    for statement in (
        "INSERT INTO status_transitions VALUES ('COMPLETED', 'RECRUITING')",
        "UPDATE status_transitions SET to_status = 'COMPLETED'",
        "DELETE FROM status_transitions",
    ):
        with pytest.raises(sqlite3.IntegrityError, match="lifecycle is fixed"):
            db.execute(statement)


# REQ-009 Final statuses are locked ----------------------------------------------------


def test_req_009_a_completed_study_cannot_return_to_recruiting(browser, db):
    browser.create()
    browser.bring_to("COMPLETED")
    response = browser.change_status("RECRUITING")
    assert response.status_code == 409
    assert "Completed, a final status" in response.text
    assert db.study()["status"] == "COMPLETED"


@pytest.mark.parametrize("final", FINAL_STATUSES)
def test_req_009_a_final_status_never_changes(browser, db, final):
    browser.create()
    browser.bring_to(final)
    for target in STATUSES:
        assert browser.change_status(target).status_code == 409
    assert db.study()["status"] == final


@pytest.mark.parametrize("final", FINAL_STATUSES)
def test_req_009_database_rejects_leaving_a_final_status(browser, db, final):
    browser.create()
    browser.bring_to(final)
    with pytest.raises(sqlite3.IntegrityError, match="status transition not allowed"):
        db.execute("UPDATE studies SET status = 'RECRUITING'")


def test_req_009_fields_of_a_final_study_can_still_be_corrected(browser, db):
    browser.create()
    browser.bring_to("COMPLETED")
    response = browser.edit(title="Corrected title", reason="Title had a typo.")
    assert response.status_code == 302
    assert db.study()["title"] == "Corrected title"
    assert db.audit()[-1]["reason"] == "Title had a typo."


def test_req_009_study_page_explains_that_the_status_is_final(browser):
    browser.create()
    browser.bring_to("WITHDRAWN")
    page = browser.get(f"/studies/{STUDY_ID}").text
    assert "Withdrawn is a final status" in page
    assert 'name="status"' not in page
