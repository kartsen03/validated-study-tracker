import pytest
from helpers import Browser, Database

from study_tracker import create_app
from study_tracker.db import ENGINE_KEY


@pytest.fixture
def app(tmp_path):
    app = create_app(
        {"TESTING": True, "DATABASE": str(tmp_path / "test.sqlite"), "SECRET_KEY": "test-secret"}
    )
    yield app
    app.extensions[ENGINE_KEY].dispose()


@pytest.fixture
def anonymous(app):
    """A visitor who hasn't identified themselves."""
    return Browser(app.test_client())


@pytest.fixture
def browser(app):
    """A user signed in as a.rivera."""
    return Browser(app.test_client()).sign_in()


@pytest.fixture
def db(app):
    return Database(app.config["DATABASE"])
