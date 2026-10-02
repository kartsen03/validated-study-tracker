"""Writing and reading the audit trail (REQ-011 to REQ-013).

There is deliberately no function here, or anywhere else in the application, that
modifies or removes an entry (REQ-012). The ORM refuses both (models.py) and so does
the database (db.py).
"""

from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AuditEntry

CREATE = "CREATE"
UPDATE = "UPDATE"
STATUS_CHANGE = "STATUS"
DELETE = "DELETE"

Change = tuple[str | None, object, object]  # (field, old value, new value)


def utc_now() -> str:
    """The server's clock in UTC, to the microsecond. Never a time sent by the browser."""
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _as_text(value: object) -> str | None:
    return None if value is None else str(value)


def record(
    session: Session,
    *,
    study_id: str,
    action: str,
    username: str,
    reason: str | None,
    changes: Iterable[Change],
    at: str | None = None,
) -> list[AuditEntry]:
    """Add one entry per change to the session. They're saved when the caller commits,
    together with the change itself (REQ-014)."""
    recorded_at = at or utc_now()
    entries = [
        AuditEntry(
            study_id=study_id,
            action=action,
            field=field,
            old_value=_as_text(old),
            new_value=_as_text(new),
            reason=reason,
            username=username,
            recorded_at=recorded_at,
        )
        for field, old, new in changes
    ]
    session.add_all(entries)
    return entries


def history(session: Session, study_id: str) -> list[AuditEntry]:
    """Every entry for a study, oldest first."""
    query = select(AuditEntry).where(AuditEntry.study_id == study_id).order_by(AuditEntry.id)
    return list(session.scalars(query))
