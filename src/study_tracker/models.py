"""Database tables.

Studies are never removed from the table: deleting one records the time it was deleted
(REQ-015). That keeps its ID reserved by the unique constraint (REQ-004) and its audit
history meaningful.
"""

from typing import ClassVar

from sqlalchemy import CheckConstraint, Column, ForeignKey, Integer, String, Table, Text, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(40), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(100))


class Study(Base):
    __tablename__ = "studies"
    __table_args__ = (
        CheckConstraint("target_enrollment BETWEEN 1 AND 1000000", name="ck_target_enrollment"),
        CheckConstraint("site_count BETWEEN 0 AND 10000", name="ck_site_count"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    study_id: Mapped[str] = mapped_column(String(20), unique=True)
    title: Mapped[str] = mapped_column(String(300))
    phase: Mapped[str] = mapped_column(String(20))
    sponsor: Mapped[str] = mapped_column(String(200))
    target_enrollment: Mapped[int]
    site_count: Mapped[int]
    status: Mapped[str] = mapped_column(String(30))
    deleted_at: Mapped[str | None] = mapped_column(String(32), default=None)


class AuditEntry(Base):
    """One change to one field (REQ-011). Rows are only ever inserted (REQ-012)."""

    __tablename__ = "audit_entries"
    # AUTOINCREMENT: ids are never reused, so they give a stable order even when
    # entries written in one transaction share a timestamp.
    __table_args__: ClassVar[dict] = {"sqlite_autoincrement": True}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    study_id: Mapped[str] = mapped_column(String(20), index=True)
    action: Mapped[str] = mapped_column(String(10))
    field: Mapped[str | None] = mapped_column(String(40))
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(String(500))
    username: Mapped[str] = mapped_column(ForeignKey("users.username"))
    recorded_at: Mapped[str] = mapped_column(String(32))


# The status lifecycle, loaded from lifecycle.TRANSITIONS when the schema is created and
# read by the trigger that checks every status change (see db.py).
status_transitions = Table(
    "status_transitions",
    Base.metadata,
    Column("from_status", String(30), primary_key=True),
    Column("to_status", String(30), primary_key=True),
)


class AuditTrailViolation(Exception):
    """Raised on any attempt to modify or remove an audit entry through the ORM."""


# Defence in depth: the database triggers reject these too, but failing here gives a
# clear error before any SQL is sent.
@event.listens_for(AuditEntry, "before_update")
def _refuse_update(mapper, connection, target):
    raise AuditTrailViolation("Audit entries are append-only and cannot be modified.")


@event.listens_for(AuditEntry, "before_delete")
def _refuse_delete(mapper, connection, target):
    raise AuditTrailViolation("Audit entries are append-only and cannot be deleted.")
