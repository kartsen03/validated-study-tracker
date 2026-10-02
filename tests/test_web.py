"""Supporting behaviour that isn't a numbered requirement: form tokens, sign-in
redirects, escaping, startup, and the demo data command. These aren't named after a
requirement, so the traceability matrix lists them separately."""

import pytest
from helpers import SPEC_TRANSITIONS, STUDY_ID, VALID_STUDY, Browser, Database

from study_tracker import create_app
from study_tracker.db import ENGINE_KEY


def test_index_redirects_to_the_study_list(browser):
    response = browser.get("/")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/studies")


def test_a_form_without_its_security_token_is_rejected(browser, db):
    response = browser.client.post("/studies/new", data=VALID_STUDY)
    assert response.status_code == 400
    assert db.count("studies") == 0


def test_a_form_with_the_wrong_security_token_is_rejected(browser, db):
    response = browser.client.post("/studies/new", data={**VALID_STUDY, "csrf_token": "forged"})
    assert response.status_code == 400
    assert db.count("studies") == 0


def test_rendered_forms_carry_the_sessions_token(browser):
    page = browser.get("/studies/new").text
    assert f'name="csrf_token" value="{browser.token()}"' in page


def test_sign_in_returns_to_the_page_that_was_requested(anonymous):
    response = anonymous.get("/studies/new?from=list")
    assert response.headers["Location"].endswith("/sign-in?next=/studies/new?from%3Dlist")
    response = anonymous.post(
        "/sign-in", query_string={"next": "/studies/new?from=list"}, data={"username": "j.chen"}
    )
    assert response.headers["Location"].endswith("/studies/new?from=list")


# Each of these is read by browsers as a link to another site.
OFFSITE = [
    "//evil.example/",
    "/\\evil.example/",
    "/\t/evil.example/",
    "/\n/evil.example/",
    "https://evil.example/",
    "evil.example",
    "javascript:alert(1)",
]


@pytest.mark.parametrize("target", OFFSITE, ids=lambda target: repr(target))
def test_sign_in_never_redirects_to_another_site(anonymous, target):
    response = anonymous.post(
        "/sign-in", query_string={"next": target}, data={"username": "j.chen"}
    )
    assert response.status_code == 302
    assert response.headers["Location"] == "/studies"


def test_sign_in_page_lists_the_users(anonymous):
    page = anonymous.get("/sign-in").text
    assert "Ana Rivera, Clinical Data Manager" in page


def test_signing_out_forgets_the_user(browser):
    assert browser.post("/sign-out").status_code == 302
    assert browser.get("/studies").status_code == 302


def test_html_in_a_field_is_shown_as_text(browser):
    browser.create(title="<script>alert(1)</script>")
    page = browser.get(f"/studies/{STUDY_ID}").text
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page


def test_list_is_empty_before_any_study_exists(browser):
    assert "No studies yet." in browser.get("/studies").text


def test_successful_actions_confirm_what_happened(browser):
    browser.create()
    page = browser.edit(title="Revised title", site_count="9")
    assert page.status_code == 302
    detail = browser.get(f"/studies/{STUDY_ID}").text
    assert "Saved changes to: Title, Site count." in detail


def test_two_users_see_the_same_records(app):
    first = Browser(app.test_client()).sign_in("a.rivera")
    first.create()
    second = Browser(app.test_client()).sign_in("m.okafor")
    assert STUDY_ID in second.get("/studies").text


def test_demo_data_command_builds_an_audited_history(app, db):
    runner = app.test_cli_runner()
    result = runner.invoke(args=["seed-demo"])
    assert "Added 3 demo studies" in result.output
    assert db.count("studies") == 3
    assert {row["status"] for row in db.rows("SELECT status FROM studies")} == {
        "RECRUITING",
        "COMPLETED",
    }
    assert "Studies already exist" in runner.invoke(args=["seed-demo"]).output


def test_restarting_on_an_existing_database_changes_nothing(app, browser, db):
    browser.create()
    browser.change_status("RECRUITING")

    def everything():
        return (
            db.snapshot(),
            db.rows("SELECT * FROM users ORDER BY username"),
            db.rows("SELECT * FROM status_transitions ORDER BY from_status, to_status"),
        )

    before = everything()
    restarted = create_app(
        {"TESTING": True, "DATABASE": app.config["DATABASE"], "SECRET_KEY": "another-secret"}
    )
    restarted.extensions[ENGINE_KEY].dispose()
    assert everything() == before


def test_configuration_comes_from_the_environment(tmp_path, monkeypatch):
    path = tmp_path / "from-environment.sqlite"
    monkeypatch.setenv("STUDY_TRACKER_DATABASE", str(path))
    monkeypatch.setenv("STUDY_TRACKER_SECRET_KEY", "from-environment")
    app = create_app()
    try:
        assert app.config["DATABASE"] == str(path)
        assert app.config["SECRET_KEY"] == "from-environment"
        # The schema and the lifecycle were created in the configured file.
        expected = sum(len(targets) for targets in SPEC_TRANSITIONS.values())
        assert Database(str(path)).count("status_transitions") == expected
    finally:
        app.extensions[ENGINE_KEY].dispose()
