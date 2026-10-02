"""Demo data, created through the service layer so every record has a real audit trail.

flask --app study_tracker seed-demo
"""

import click
from flask import current_app
from flask.cli import with_appcontext

from . import services
from .db import get_session
from .models import User

DEMO_STUDIES = (
    {
        "study_id": "ONC-2026-001",
        "title": "Phase 2 study of a KRAS G12C inhibitor in previously treated NSCLC",
        "phase": "Phase 2",
        "sponsor": "Northbridge Oncology",
        "target_enrollment": "120",
        "site_count": "18",
    },
    {
        "study_id": "CV-2026-014",
        "title": "Phase 3 trial of an oral PCSK9 inhibitor after acute coronary syndrome",
        "phase": "Phase 3",
        "sponsor": "Harbor Cardiometabolic",
        "target_enrollment": "2400",
        "site_count": "210",
    },
    {
        "study_id": "ONC-2025-087",
        "title": "First-in-human dose escalation of an anti-CLDN18.2 antibody-drug conjugate",
        "phase": "Phase 1",
        "sponsor": "Larkspur Therapeutics",
        "target_enrollment": "45",
        "site_count": "4",
    },
)


@click.command("seed-demo")
@with_appcontext
def seed_demo_command() -> None:
    """Add a few demo studies with a short, realistic history."""
    db = get_session()
    manager, monitor = db.get(User, "a.rivera"), db.get(User, "j.chen")
    if services.list_studies(db):
        click.echo("Studies already exist; nothing added.")
        return

    for study in DEMO_STUDIES:
        services.create_study(db, manager, study)

    services.change_status(db, manager, "ONC-2026-001", "RECRUITING", "First site activated.")
    services.edit_study(
        db,
        monitor,
        "ONC-2026-001",
        {
            **DEMO_STUDIES[0],
            "site_count": "22",
            "reason": "Four sites added after feasibility review.",
        },
    )
    services.change_status(
        db, manager, "CV-2026-014", "RECRUITING", "Regulatory approval received."
    )
    services.change_status(db, manager, "ONC-2025-087", "RECRUITING", "First patient screened.")
    services.change_status(
        db,
        manager,
        "ONC-2025-087",
        "ACTIVE_NOT_RECRUITING",
        "Dose-escalation cohorts fully enrolled.",
    )
    services.change_status(
        db, manager, "ONC-2025-087", "COMPLETED", "Last patient's final visit done."
    )
    click.echo(f"Added {len(DEMO_STUDIES)} demo studies to {current_app.config['DATABASE']}.")
