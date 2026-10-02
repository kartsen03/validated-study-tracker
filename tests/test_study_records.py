"""REQ-001 to REQ-005: creating, validating and viewing study records."""

import sqlite3

import pytest
from helpers import LABELS, PHASES, STUDY_ID, VALID_STUDY, shown

REQUIRED = tuple(LABELS)


# REQ-001 Create a study ---------------------------------------------------------------


def test_req_001_create_study_saves_the_entered_values(browser, db):
    response = browser.create()
    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/studies/{STUDY_ID}")
    study = db.study()
    assert {field: study[field] for field in ("title", "phase", "sponsor")} == {
        "title": VALID_STUDY["title"],
        "phase": "Phase 2",
        "sponsor": VALID_STUDY["sponsor"],
    }
    assert (study["target_enrollment"], study["site_count"]) == (120, 8)
    assert db.count("studies") == 1


def test_req_001_new_study_starts_planned_whatever_status_is_submitted(browser, db):
    browser.create(status="COMPLETED")
    assert db.study()["status"] == "PLANNED"


def test_req_001_database_rejects_a_study_inserted_in_another_status(db):
    with pytest.raises(sqlite3.IntegrityError, match="must start in status PLANNED"):
        db.execute(
            "INSERT INTO studies (study_id, title, phase, sponsor, target_enrollment,"
            " site_count, status) VALUES ('X-001', 't', 'Phase 1', 's', 1, 0, 'RECRUITING')"
        )


# REQ-002 Required fields --------------------------------------------------------------


@pytest.mark.parametrize("field", REQUIRED)
def test_req_002_create_without_a_required_field_is_rejected(browser, db, field):
    response = browser.create(**{field: ""})
    assert response.status_code == 400
    assert f"{LABELS[field]} is required." in response.text
    assert db.count("studies") == 0
    assert db.count("audit_entries") == 0


def test_req_002_whitespace_only_counts_as_missing(browser, db):
    response = browser.create(title="   ")
    assert response.status_code == 400
    assert "Title is required." in response.text
    assert db.count("studies") == 0


def test_req_002_message_names_every_missing_field(browser):
    response = browser.post("/studies/new", data={})
    assert response.status_code == 400
    for label in LABELS.values():
        assert f"{label} is required." in response.text


@pytest.mark.parametrize("field", REQUIRED[1:])
def test_req_002_edit_without_a_required_field_is_rejected(browser, db, field):
    browser.create()
    before = db.snapshot()
    response = browser.edit(**{field: ""})
    assert response.status_code == 400
    assert f"{LABELS[field]} is required." in response.text
    assert db.snapshot() == before


# REQ-003 Field validation -------------------------------------------------------------

INVALID = [
    ("study_id", "AB", "Study ID must be 3 to 20 characters"),
    ("study_id", "A" * 21, "Study ID must be 3 to 20 characters"),
    ("study_id", "-ABC", "Study ID must be 3 to 20 characters"),
    ("study_id", "AB C", "Study ID must be 3 to 20 characters"),
    ("study_id", "AB_C", "Study ID must be 3 to 20 characters"),
    ("title", "x" * 301, "Title must be at most 300 characters."),
    ("sponsor", "x" * 201, "Sponsor must be at most 200 characters."),
    ("phase", "Phase 5", "Phase must be one of"),
    ("target_enrollment", "0", "Target enrollment must be a whole number from 1 to 1,000,000."),
    (
        "target_enrollment",
        "1000001",
        "Target enrollment must be a whole number from 1 to 1,000,000.",
    ),
    ("target_enrollment", "12.5", "Target enrollment must be a whole number"),
    ("target_enrollment", "-3", "Target enrollment must be a whole number"),
    ("target_enrollment", "ten", "Target enrollment must be a whole number"),
    ("target_enrollment", "1,000", "Target enrollment must be a whole number"),
    ("site_count", "-1", "Site count must be a whole number from 0 to 10,000."),
    ("site_count", "10001", "Site count must be a whole number from 0 to 10,000."),
]


@pytest.mark.parametrize(
    ("field", "value", "message"), INVALID, ids=[f"{f}={v[:10]}" for f, v, _ in INVALID]
)
def test_req_003_invalid_value_is_rejected(browser, db, field, value, message):
    response = browser.create(**{field: value})
    assert response.status_code == 400
    assert message in response.text
    assert db.count("studies") == 0


BOUNDARY = [
    ("study_id", "ABC", "ABC"),
    ("study_id", "A" * 20, "A" * 20),
    ("study_id", "9-9", "9-9"),
    ("title", "x" * 300, "x" * 300),
    ("sponsor", "x" * 200, "x" * 200),
    ("target_enrollment", "1", 1),
    ("target_enrollment", "1000000", 1_000_000),
    ("site_count", "0", 0),
    ("site_count", "10000", 10_000),
]


@pytest.mark.parametrize(
    ("field", "value", "stored"), BOUNDARY, ids=[f"{f}={v[:10]}" for f, v, _ in BOUNDARY]
)
def test_req_003_boundary_values_are_accepted(browser, db, field, value, stored):
    response = browser.create(**{field: value})
    assert response.status_code == 302, response.text
    study_id = stored if field == "study_id" else STUDY_ID
    assert db.study(study_id)[field] == stored


def test_req_003_every_defined_phase_is_accepted(browser, db):
    for number, phase in enumerate(PHASES):
        response = browser.create(study_id=f"PH-{number:03d}", phase=phase)
        assert response.status_code == 302, phase
    assert {row["phase"] for row in db.rows("SELECT phase FROM studies")} == set(PHASES)


def test_req_003_database_rejects_out_of_range_numbers(db):
    with pytest.raises(sqlite3.IntegrityError, match="ck_target_enrollment"):
        db.execute(
            "INSERT INTO studies (study_id, title, phase, sponsor, target_enrollment,"
            " site_count, status) VALUES ('X-001', 't', 'Phase 1', 's', 0, 0, 'PLANNED')"
        )


# REQ-004 Unique, permanent study IDs --------------------------------------------------


def test_req_004_ids_are_stored_in_upper_case(browser, db):
    browser.create(study_id="mp-2026-001")
    assert db.study(STUDY_ID) is not None


def test_req_004_duplicate_id_is_rejected(browser, db):
    browser.create()
    response = browser.create(title="A different study")
    assert response.status_code == 409
    assert f"Study ID {STUDY_ID} is already in use." in response.text
    assert db.count("studies") == 1


def test_req_004_ids_are_compared_without_regard_to_case(browser, db):
    browser.create()
    response = browser.create(study_id=STUDY_ID.lower())
    assert response.status_code == 409
    assert db.count("studies") == 1


def test_req_004_id_of_a_deleted_study_cannot_be_reused(browser, db):
    browser.create()
    browser.delete()
    response = browser.create(title="A new study reusing the ID")
    assert response.status_code == 409
    assert "belonged to a deleted study and can't be reused" in shown(response)
    assert db.count("studies") == 1


def test_req_004_edit_cannot_change_the_id(browser, db):
    browser.create()
    response = browser.edit(study_id="NEW-ID-1", title="Revised title")
    assert response.status_code == 302
    assert db.study("NEW-ID-1") is None
    assert db.study()["title"] == "Revised title"


def test_req_004_database_rejects_changing_an_id(browser, db):
    browser.create()
    with pytest.raises(sqlite3.IntegrityError, match="study ID cannot be changed"):
        db.execute("UPDATE studies SET study_id = 'OTHER-1'")


# REQ-005 View studies -----------------------------------------------------------------


def test_req_005_list_shows_each_studys_summary(browser):
    browser.create()
    browser.create(
        study_id="CV-2026-002", title="Second study", phase="Phase 3", sponsor="Other Co"
    )
    page = browser.get("/studies").text
    for expected in (
        STUDY_ID,
        VALID_STUDY["title"],
        "Phase 2",
        VALID_STUDY["sponsor"],
        "CV-2026-002",
        "Second study",
        "Phase 3",
        "Other Co",
        "Planned",
    ):
        assert expected in page


def test_req_005_detail_shows_every_field(browser):
    browser.create(target_enrollment="2400")
    page = browser.get(f"/studies/{STUDY_ID}").text
    for expected in (
        STUDY_ID,
        VALID_STUDY["title"],
        "Phase 2",
        VALID_STUDY["sponsor"],
        "2,400",
        ">8<",
        "Planned",
    ):
        assert expected in page


def test_req_005_unknown_study_is_not_found(browser):
    assert browser.get("/studies/NO-SUCH-1").status_code == 404
