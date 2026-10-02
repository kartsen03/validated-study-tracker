"""Engine, per-request session, and schema setup.

The schema includes SQLite triggers for the rules that must hold however the data is
changed. The application checks the same rules first so the user gets a clear message;
the triggers make sure a bug, or SQL run outside the application, can't break them.
"""

from flask import Flask, current_app, g
from sqlalchemy import Engine, create_engine, event, func, insert, select
from sqlalchemy.orm import Session

from .lifecycle import INITIAL_STATUS, TRANSITIONS
from .models import Base, User, status_transitions

TRIGGERS = (
    # REQ-012: the audit trail is append-only.
    """CREATE TRIGGER IF NOT EXISTS audit_entries_no_update
       BEFORE UPDATE ON audit_entries
       BEGIN SELECT RAISE(ABORT, 'audit entries are append-only and cannot be updated'); END""",
    """CREATE TRIGGER IF NOT EXISTS audit_entries_no_delete
       BEFORE DELETE ON audit_entries
       BEGIN SELECT RAISE(ABORT, 'audit entries are append-only and cannot be deleted'); END""",
    # REQ-001: a new study starts Planned.
    f"""CREATE TRIGGER IF NOT EXISTS studies_start_planned
        BEFORE INSERT ON studies
        WHEN NEW.status IS NOT '{INITIAL_STATUS}'
        BEGIN SELECT RAISE(ABORT, 'a new study must start in status {INITIAL_STATUS}'); END""",
    # REQ-004: a study ID never changes.
    """CREATE TRIGGER IF NOT EXISTS studies_id_immutable
       BEFORE UPDATE OF study_id ON studies
       WHEN NEW.study_id IS NOT OLD.study_id
       BEGIN SELECT RAISE(ABORT, 'a study ID cannot be changed'); END""",
    # REQ-008 and REQ-009: status changes follow the lifecycle table. Final statuses
    # have no rows in it, so they can never be left.
    """CREATE TRIGGER IF NOT EXISTS studies_status_transition
       BEFORE UPDATE OF status ON studies
       WHEN NEW.status IS NOT OLD.status AND NOT EXISTS (
           SELECT 1 FROM status_transitions
           WHERE from_status = OLD.status AND to_status = NEW.status)
       BEGIN SELECT RAISE(ABORT, 'status transition not allowed'); END""",
    # REQ-015: a deleted study is kept, unchanged, and rows are never removed.
    """CREATE TRIGGER IF NOT EXISTS studies_deleted_read_only
       BEFORE UPDATE ON studies
       WHEN OLD.deleted_at IS NOT NULL
       BEGIN SELECT RAISE(ABORT, 'a deleted study cannot be changed'); END""",
    """CREATE TRIGGER IF NOT EXISTS studies_no_delete
       BEFORE DELETE ON studies
       BEGIN SELECT RAISE(ABORT, 'studies are never removed; deletion is recorded instead'); END""",
    # The lifecycle table is fixed once loaded. These are created after it is filled.
    """CREATE TRIGGER IF NOT EXISTS status_transitions_no_insert
       BEFORE INSERT ON status_transitions
       BEGIN SELECT RAISE(ABORT, 'the status lifecycle is fixed'); END""",
    """CREATE TRIGGER IF NOT EXISTS status_transitions_no_update
       BEFORE UPDATE ON status_transitions
       BEGIN SELECT RAISE(ABORT, 'the status lifecycle is fixed'); END""",
    """CREATE TRIGGER IF NOT EXISTS status_transitions_no_delete
       BEFORE DELETE ON status_transitions
       BEGIN SELECT RAISE(ABORT, 'the status lifecycle is fixed'); END""",
)

DEMO_USERS = (
    ("a.rivera", "Ana Rivera, Clinical Data Manager"),
    ("j.chen", "Jun Chen, Clinical Research Associate"),
    ("m.okafor", "Mira Okafor, QA Reviewer"),
)

ENGINE_KEY = "study_tracker.engine"


def make_engine(path: str) -> Engine:
    engine = create_engine(f"sqlite:///{path}")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA foreign_keys = ON")

    return engine


def init_schema(engine: Engine) -> None:
    """Create tables and triggers, load the lifecycle, and add the demo users.

    Safe to run against an existing database: nothing that already exists is changed.
    """
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        if connection.scalar(select(func.count()).select_from(status_transitions)) == 0:
            connection.execute(
                insert(status_transitions),
                [
                    {"from_status": current, "to_status": target}
                    for current, targets in TRANSITIONS.items()
                    for target in targets
                ],
            )
        for statement in TRIGGERS:
            connection.exec_driver_sql(statement)
        if connection.scalar(select(func.count()).select_from(User)) == 0:
            connection.execute(
                insert(User),
                [{"username": name, "display_name": display} for name, display in DEMO_USERS],
            )


def init_app(app: Flask) -> None:
    engine = make_engine(app.config["DATABASE"])
    init_schema(engine)
    app.extensions[ENGINE_KEY] = engine
    app.teardown_appcontext(_close_session)


def get_session() -> Session:
    """The session for the current request, opened on first use."""
    if "db_session" not in g:
        # expire_on_commit=False lets a view render an object it just saved.
        g.db_session = Session(current_app.extensions[ENGINE_KEY], expire_on_commit=False)
    return g.db_session


def _close_session(_exception: BaseException | None) -> None:
    session = g.pop("db_session", None)
    if session is not None:
        session.close()
