"""REQ-006, REQ-007 and REQ-010: editing studies, reasons for change, and identified users."""

import pytest
from helpers import STUDY_ID, VALID_STUDY, Browser

# REQ-006 Edit a study -----------------------------------------------------------------


def test_req_006_edit_saves_the_changed_fields(browser, db):
    browser.create()
    response = browser.edit(title="Revised title", site_count="12")
    assert response.status_code == 302
    study = db.study()
    assert (study["title"], study["site_count"]) == ("Revised title", 12)
    assert (study["phase"], study["sponsor"]) == ("Phase 2", VALID_STUDY["sponsor"])


def test_req_006_edit_form_shows_the_current_values(browser):
    browser.create()
    page = browser.get(f"/studies/{STUDY_ID}/edit").text
    assert VALID_STUDY["title"] in page
    assert VALID_STUDY["sponsor"] in page


def test_req_006_edits_are_validated_like_new_studies(browser, db):
    browser.create()
    before = db.snapshot()
    response = browser.edit(target_enrollment="0")
    assert response.status_code == 400
    assert "Target enrollment must be a whole number from 1 to 1,000,000." in response.text
    assert db.snapshot() == before


def test_req_006_editing_an_unknown_study_is_not_found(browser):
    assert browser.get("/studies/NO-SUCH-1/edit").status_code == 404
    assert browser.edit(of="NO-SUCH-1").status_code == 404


# REQ-007 Reason for change ------------------------------------------------------------

ACTIONS = {
    "edit": lambda browser, reason: browser.edit(title="Revised title", reason=reason),
    "status": lambda browser, reason: browser.change_status("RECRUITING", reason=reason),
    "delete": lambda browser, reason: browser.delete(reason=reason),
}


@pytest.mark.parametrize("reason", [None, "", "   \n "], ids=["missing", "empty", "whitespace"])
@pytest.mark.parametrize("action", list(ACTIONS))
def test_req_007_change_without_a_reason_is_rejected(browser, db, action, reason):
    browser.create()
    before = db.snapshot()
    response = ACTIONS[action](browser, reason)
    assert response.status_code == 400
    assert "A reason for change is required." in response.text
    assert db.snapshot() == before


def test_req_007_reason_longer_than_500_characters_is_rejected(browser, db):
    browser.create()
    before = db.snapshot()
    response = browser.edit(title="Revised title", reason="x" * 501)
    assert response.status_code == 400
    assert "at most 500 characters" in response.text
    assert db.snapshot() == before


def test_req_007_reason_of_exactly_500_characters_is_accepted(browser, db):
    browser.create()
    assert browser.edit(title="Revised title", reason="x" * 500).status_code == 302
    assert db.audit()[-1]["reason"] == "x" * 500


def test_req_007_reason_is_saved_without_surrounding_whitespace(browser, db):
    browser.create()
    browser.edit(title="Revised title", reason="  Typo in the title.  ")
    assert db.audit()[-1]["reason"] == "Typo in the title."


def test_req_007_creating_a_study_needs_no_reason(browser, db):
    assert browser.create().status_code == 302
    assert {entry["reason"] for entry in db.audit()} == {None}


# REQ-010 Identified users only --------------------------------------------------------

CHANGES = {
    "create": ("/studies/new", {**VALID_STUDY, "study_id": "OTHER-001"}),
    "edit": (f"/studies/{STUDY_ID}/edit", {**VALID_STUDY, "title": "Changed", "reason": "x"}),
    "status": (f"/studies/{STUDY_ID}/status", {"status": "RECRUITING", "reason": "x"}),
    "delete": (f"/studies/{STUDY_ID}/delete", {"reason": "x"}),
}


@pytest.mark.parametrize("change", list(CHANGES))
def test_req_010_change_without_an_identified_user_is_rejected(app, db, change):
    Browser(app.test_client()).sign_in().create()
    before = db.snapshot()
    path, form = CHANGES[change]
    response = Browser(app.test_client()).post(path, data=form)
    assert response.status_code == 302
    assert "/sign-in" in response.headers["Location"]
    assert db.snapshot() == before


@pytest.mark.parametrize(
    "path",
    [
        "/studies",
        "/studies/new",
        f"/studies/{STUDY_ID}",
        f"/studies/{STUDY_ID}/edit",
        f"/studies/{STUDY_ID}/audit",
    ],
)
def test_req_010_viewing_requires_an_identified_user(app, anonymous, path):
    Browser(app.test_client()).sign_in().create()
    response = anonymous.get(path)
    assert response.status_code == 302
    assert "/sign-in" in response.headers["Location"]


def test_req_010_an_unknown_username_is_not_accepted(anonymous):
    response = anonymous.post("/sign-in", data={"username": "mallory"})
    assert response.status_code == 400
    assert anonymous.get("/studies").status_code == 302


def test_req_010_changes_are_attributed_to_the_signed_in_user(app, db):
    monitor = Browser(app.test_client()).sign_in("j.chen")
    monitor.create()
    manager = Browser(app.test_client()).sign_in("a.rivera")
    manager.change_status("RECRUITING")
    entries = db.audit()
    assert {entry["username"] for entry in entries[:-1]} == {"j.chen"}
    assert entries[-1]["username"] == "a.rivera"
