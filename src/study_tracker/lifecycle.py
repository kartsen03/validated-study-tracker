"""Study phases and statuses, and the status lifecycle (REQ-008, REQ-009).

The transition table is defined once, here. The service layer checks it to give the
user a clear message, and the database enforces it with a trigger that reads the same
table (see db.py), so neither a bug nor a direct SQL edit can bypass it.
"""

from enum import StrEnum

PHASES = (
    "Early Phase 1",
    "Phase 1",
    "Phase 1/2",
    "Phase 2",
    "Phase 2/3",
    "Phase 3",
    "Phase 4",
    "Not applicable",
)


class Status(StrEnum):
    PLANNED = "PLANNED"
    RECRUITING = "RECRUITING"
    ACTIVE_NOT_RECRUITING = "ACTIVE_NOT_RECRUITING"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"
    TERMINATED = "TERMINATED"
    WITHDRAWN = "WITHDRAWN"

    @property
    def label(self) -> str:
        return _LABELS[self]


# Labels match the requirements document, which uses them in the transition table.
_LABELS = {
    Status.PLANNED: "Planned",
    Status.RECRUITING: "Recruiting",
    Status.ACTIVE_NOT_RECRUITING: "Active not recruiting",
    Status.SUSPENDED: "Suspended",
    Status.COMPLETED: "Completed",
    Status.TERMINATED: "Terminated",
    Status.WITHDRAWN: "Withdrawn",
}

INITIAL_STATUS = Status.PLANNED

# Withdrawn means stopped before the first participant enrolled and Terminated means
# stopped after enrollment began (ClinicalTrials.gov's definitions), so a Planned study
# can be withdrawn but not terminated.
TRANSITIONS: dict[Status, frozenset[Status]] = {
    Status.PLANNED: frozenset({Status.RECRUITING, Status.WITHDRAWN}),
    Status.RECRUITING: frozenset(
        {Status.ACTIVE_NOT_RECRUITING, Status.SUSPENDED, Status.TERMINATED}
    ),
    Status.ACTIVE_NOT_RECRUITING: frozenset(
        {Status.COMPLETED, Status.SUSPENDED, Status.TERMINATED}
    ),
    Status.SUSPENDED: frozenset(
        {Status.RECRUITING, Status.ACTIVE_NOT_RECRUITING, Status.TERMINATED}
    ),
    Status.COMPLETED: frozenset(),
    Status.TERMINATED: frozenset(),
    Status.WITHDRAWN: frozenset(),
}

FINAL_STATUSES = frozenset(status for status, targets in TRANSITIONS.items() if not targets)


def can_transition(current: Status, new: Status) -> bool:
    return new in TRANSITIONS[current]


def allowed_next(current: Status) -> list[Status]:
    """Statuses reachable from `current`, in lifecycle order."""
    return [status for status in Status if status in TRANSITIONS[current]]
