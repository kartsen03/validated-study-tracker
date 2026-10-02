"""Every change to a study goes through this module.

Each operation validates its input, applies the change and records its audit entries
in one transaction, so the data never holds a change the audit trail doesn't record
(REQ-014). The views in views.py only translate between HTTP and these functions.
"""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import audit
from .lifecycle import FINAL_STATUSES, INITIAL_STATUS, Status, allowed_next, can_transition
from .models import AuditEntry, Study, User
from .validation import (
    ALL_FIELDS,
    EDITABLE_FIELDS,
    ValidationError,
    clean_reason,
    clean_study,
    normalize_study_id,
)


class RuleViolation(Exception):
    """The request is well formed but breaks a business rule."""


class NotFound(Exception):
    """No active study has the given ID."""


@contextmanager
def atomic(session: Session) -> Iterator[None]:
    """Commit everything done in the block, or nothing at all if it raises."""
    try:
        yield
        session.commit()
    except BaseException:
        session.rollback()
        raise


def list_studies(session: Session) -> list[Study]:
    query = select(Study).where(Study.deleted_at.is_(None)).order_by(Study.study_id)
    return list(session.scalars(query))


def get_study(session: Session, study_id: str) -> Study:
    """The active study with this ID. Deleted studies are not returned (REQ-015)."""
    normalized = normalize_study_id(study_id)
    query = select(Study).where(Study.study_id == normalized, Study.deleted_at.is_(None))
    study = session.scalar(query)
    if study is None:
        raise NotFound(f"There is no study {normalized}.")
    return study


def create_study(session: Session, user: User, form: Mapping[str, str]) -> Study:
    """REQ-001 to REQ-004: a new study, always Planned, audited field by field."""
    values = clean_study(form)
    study_id = values["study_id"]
    with atomic(session):
        existing = session.scalar(select(Study).where(Study.study_id == study_id))
        if existing is not None and existing.deleted_at is not None:
            raise RuleViolation(
                f"Study ID {study_id} belonged to a deleted study and can't be reused."
            )
        if existing is not None:
            raise RuleViolation(f"Study ID {study_id} is already in use.")
        study = Study(**values, status=INITIAL_STATUS)
        session.add(study)
        audit.record(
            session,
            study_id=study_id,
            action=audit.CREATE,
            username=user.username,
            reason=None,
            changes=[(field, None, getattr(study, field)) for field in (*ALL_FIELDS, "status")],
        )
    return study


def edit_study(session: Session, user: User, study_id: str, form: Mapping[str, str]) -> list[str]:
    """REQ-006 and REQ-007: save the fields that changed. Returns their names.

    The study ID is not an editable field, so any ID in the form is ignored (REQ-004).
    """
    values: dict[str, object] = {}
    errors: dict[str, str] = {}
    try:
        values = clean_study(form, EDITABLE_FIELDS)
    except ValidationError as exc:
        errors.update(exc.errors)
    try:
        reason = clean_reason(form.get("reason"))
    except ValidationError as exc:
        errors.update(exc.errors)
    if errors:
        raise ValidationError(errors)

    with atomic(session):
        study = get_study(session, study_id)
        changes = [
            (field, getattr(study, field), value)
            for field, value in values.items()
            if getattr(study, field) != value
        ]
        if not changes:
            raise RuleViolation("Nothing was changed: every field already has the value entered.")
        for field, _old, new in changes:
            setattr(study, field, new)
        audit.record(
            session,
            study_id=study.study_id,
            action=audit.UPDATE,
            username=user.username,
            reason=reason,
            changes=changes,
        )
    return [field for field, _old, _new in changes]


def change_status(
    session: Session, user: User, study_id: str, new_status: str | None, reason_text: str | None
) -> Study:
    """REQ-007 to REQ-009: move a study along its lifecycle."""
    errors: dict[str, str] = {}
    try:
        target = Status(new_status)
    except ValueError:
        errors["status"] = "Choose the new status."
    try:
        reason = clean_reason(reason_text)
    except ValidationError as exc:
        errors.update(exc.errors)
    if errors:
        raise ValidationError(errors)

    with atomic(session):
        study = get_study(session, study_id)
        current = Status(study.status)
        if current in FINAL_STATUSES:
            raise RuleViolation(
                f"{study.study_id} is {current.label}, a final status, so its status can't change."
            )
        if not can_transition(current, target):
            options = ", ".join(status.label for status in allowed_next(current))
            raise RuleViolation(
                f"A study can't go from {current.label} to {target.label}. "
                f"From {current.label} it can go to: {options}."
            )
        study.status = target
        audit.record(
            session,
            study_id=study.study_id,
            action=audit.STATUS_CHANGE,
            username=user.username,
            reason=reason,
            changes=[("status", current, target)],
        )
    return study


def delete_study(session: Session, user: User, study_id: str, reason_text: str | None) -> None:
    """REQ-015: mark the study deleted. The row and its history are kept."""
    reason = clean_reason(reason_text)
    with atomic(session):
        study = get_study(session, study_id)
        now = audit.utc_now()
        study.deleted_at = now
        audit.record(
            session,
            study_id=study.study_id,
            action=audit.DELETE,
            username=user.username,
            reason=reason,
            changes=[(None, None, None)],
            at=now,
        )


def study_history(session: Session, study_id: str) -> list[AuditEntry]:
    """REQ-013: the full audit history, including for a deleted study."""
    normalized = normalize_study_id(study_id)
    entries = audit.history(session, normalized)
    if not entries:
        raise NotFound(f"There is no study {normalized}.")
    return entries


def is_deleted(session: Session, study_id: str) -> bool:
    query = select(Study.deleted_at).where(Study.study_id == normalize_study_id(study_id))
    return session.scalar(query) is not None
