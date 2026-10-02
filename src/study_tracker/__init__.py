"""Validated Study Tracker: clinical study records with an append-only audit trail.

Requirements are in docs/requirements.md; every one is traced to automated tests.
"""

import os
import secrets
from collections.abc import Mapping

from flask import Flask

from . import db, demo, security, views


def create_app(test_config: Mapping | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        # Set STUDY_TRACKER_SECRET_KEY to keep sessions across restarts.
        SECRET_KEY=os.environ.get("STUDY_TRACKER_SECRET_KEY") or secrets.token_hex(32),
        DATABASE=os.environ.get("STUDY_TRACKER_DATABASE")
        or os.path.join(app.instance_path, "study_tracker.sqlite"),
    )
    if test_config:
        app.config.update(test_config)
    os.makedirs(os.path.dirname(os.path.abspath(app.config["DATABASE"])), exist_ok=True)

    db.init_app(app)
    security.init_app(app)
    app.register_blueprint(views.bp)
    app.cli.add_command(demo.seed_demo_command)
    return app
