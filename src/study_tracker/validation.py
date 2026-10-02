"""Field rules for study records (REQ-002, REQ-003) and the reason for change (REQ-007).

Every rule reports all problems at once, by field, so the user can fix a form in one
pass, and nothing is saved while any remain.
"""

import re
from collections.abc import Callable, Mapping

from .lifecycle import PHASES

EDITABLE_FIELDS = ("title", "phase", "sponsor", "target_enrollment", "site_count")
ALL_FIELDS = ("study_id", *EDITABLE_FIELDS)

FIELD_LABELS = {
    "study_id": "Study ID",
    "title": "Title",
    "phase": "Phase",
    "sponsor": "Sponsor",
    "target_enrollment": "Target enrollment",
    "site_count": "Site count",
    "reason": "Reason for change",
    "status": "Status",
}

REASON_MAX_LENGTH = 500
STUDY_ID_PATTERN = re.compile(r"[A-Z0-9][A-Z0-9-]{2,19}")


class ValidationError(Exception):
    """One or more fields are missing or invalid. `errors` maps field to message."""

    def __init__(self, errors: Mapping[str, str]):
        self.errors = dict(errors)
        super().__init__("; ".join(self.errors.values()))


def normalize_study_id(raw: str | None) -> str:
    """Study IDs are compared without regard to case and stored in upper case (REQ-004)."""
    return (raw or "").strip().upper()


def _study_id(raw: str) -> str:
    value = normalize_study_id(raw)
    if not STUDY_ID_PATTERN.fullmatch(value):
        raise ValueError(
            "Study ID must be 3 to 20 characters, using only letters, digits and hyphens, "
            "and start with a letter or digit."
        )
    return value


def _text(field: str, limit: int) -> Callable[[str], str]:
    def clean(raw: str) -> str:
        if len(raw) > limit:
            raise ValueError(f"{FIELD_LABELS[field]} must be at most {limit} characters.")
        return raw

    return clean


def _phase(raw: str) -> str:
    if raw not in PHASES:
        raise ValueError(f"Phase must be one of: {', '.join(PHASES)}.")
    return raw


def _whole_number(field: str, low: int, high: int) -> Callable[[str], int]:
    def clean(raw: str) -> int:
        message = f"{FIELD_LABELS[field]} must be a whole number from {low:,} to {high:,}."
        if not re.fullmatch(r"\d+", raw):
            raise ValueError(message)
        value = int(raw)
        if not low <= value <= high:
            raise ValueError(message)
        return value

    return clean


_CLEANERS: dict[str, Callable[[str], object]] = {
    "study_id": _study_id,
    "title": _text("title", 300),
    "phase": _phase,
    "sponsor": _text("sponsor", 200),
    "target_enrollment": _whole_number("target_enrollment", 1, 1_000_000),
    "site_count": _whole_number("site_count", 0, 10_000),
}


def clean_study(form: Mapping[str, str], fields: tuple[str, ...] = ALL_FIELDS) -> dict[str, object]:
    """Validate the given fields of a submitted form and return their typed values."""
    values: dict[str, object] = {}
    errors: dict[str, str] = {}
    for name in fields:
        raw = (form.get(name) or "").strip()
        if not raw:
            errors[name] = f"{FIELD_LABELS[name]} is required."
            continue
        try:
            values[name] = _CLEANERS[name](raw)
        except ValueError as exc:
            errors[name] = str(exc)
    if errors:
        raise ValidationError(errors)
    return values


def clean_reason(raw: str | None) -> str:
    """A reason for change: 1 to 500 characters, not counting surrounding whitespace."""
    reason = (raw or "").strip()
    if not reason:
        raise ValidationError({"reason": "A reason for change is required."})
    if len(reason) > REASON_MAX_LENGTH:
        raise ValidationError(
            {"reason": f"The reason for change must be at most {REASON_MAX_LENGTH} characters."}
        )
    return reason
