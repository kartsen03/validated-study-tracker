"""HTTP routes. Each translates a request into one services call and back; the rules
themselves live in services.py."""

import re
from collections.abc import Mapping

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from sqlalchemy import select

from . import services
from .db import get_session
from .lifecycle import PHASES, Status, allowed_next
from .models import Study, User
from .security import current_user, identified_user_required
from .validation import EDITABLE_FIELDS, FIELD_LABELS, ValidationError, normalize_study_id

bp = Blueprint("main", __name__)


@bp.app_template_filter("status_label")
def status_label(value: str) -> str:
    return Status(value).label


# A path on this site: one leading slash, then only characters a path or query string
# here can contain. Browsers read "//host", "/\host" and "/<tab>/host" as another site,
# so the second character can't be a slash, and backslashes and whitespace never match.
_LOCAL_PATH = re.compile(r"/(?!/)[\w\-./?=&%]*")


def _safe_next(target: str | None) -> str:
    """Only follow redirects within this site."""
    if target and _LOCAL_PATH.fullmatch(target):
        return target
    return url_for("main.study_list")


def _get_or_404(study_id: str) -> Study:
    try:
        return services.get_study(get_session(), study_id)
    except services.NotFound:
        abort(404)


def _form(mode: str, values: Mapping, errors: Mapping[str, str], study: Study | None = None):
    return render_template(
        "study_form.html",
        mode=mode,
        values=values,
        errors=errors,
        study=study,
        phases=PHASES,
        labels=FIELD_LABELS,
    )


def _detail(study: Study, error: str | None = None, status: int = 200):
    page = render_template(
        "study.html",
        study=study,
        status=Status(study.status),
        next_statuses=allowed_next(Status(study.status)),
        labels=FIELD_LABELS,
        error=error,
    )
    return page, status


@bp.get("/")
def index():
    return redirect(url_for("main.study_list"))


@bp.route("/sign-in", methods=["GET", "POST"])
def sign_in():
    users = list(get_session().scalars(select(User).order_by(User.username)))
    if request.method == "POST":
        user = get_session().get(User, request.form.get("username", ""))
        if user is None:
            return render_template("sign_in.html", users=users, error="Choose a user."), 400
        session["username"] = user.username
        flash(f"Signed in as {user.display_name}.")
        return redirect(_safe_next(request.args.get("next")))
    return render_template("sign_in.html", users=users, error=None)


@bp.post("/sign-out")
def sign_out():
    session.pop("username", None)
    return redirect(url_for("main.sign_in"))


@bp.get("/studies")
@identified_user_required
def study_list():
    return render_template("studies.html", studies=services.list_studies(get_session()))


@bp.route("/studies/new", methods=["GET", "POST"])
@identified_user_required
def study_new():
    if request.method == "GET":
        return _form("new", {}, {})
    try:
        study = services.create_study(get_session(), current_user(), request.form)
    except ValidationError as exc:
        return _form("new", request.form, exc.errors), 400
    except services.RuleViolation as exc:
        return _form("new", request.form, {"study_id": str(exc)}), 409
    flash(f"Created study {study.study_id}.")
    return redirect(url_for("main.study_detail", study_id=study.study_id))


@bp.get("/studies/<study_id>")
@identified_user_required
def study_detail(study_id: str):
    return _detail(_get_or_404(study_id))


@bp.route("/studies/<study_id>/edit", methods=["GET", "POST"])
@identified_user_required
def study_edit(study_id: str):
    study = _get_or_404(study_id)
    if request.method == "GET":
        return _form("edit", {field: getattr(study, field) for field in EDITABLE_FIELDS}, {}, study)
    try:
        changed = services.edit_study(get_session(), current_user(), study.study_id, request.form)
    except ValidationError as exc:
        return _form("edit", request.form, exc.errors, study), 400
    except services.RuleViolation as exc:
        return _form("edit", request.form, {"_form": str(exc)}, study), 409
    flash("Saved changes to: " + ", ".join(FIELD_LABELS[field] for field in changed) + ".")
    return redirect(url_for("main.study_detail", study_id=study.study_id))


@bp.post("/studies/<study_id>/status")
@identified_user_required
def study_status(study_id: str):
    study = _get_or_404(study_id)
    try:
        services.change_status(
            get_session(),
            current_user(),
            study.study_id,
            request.form.get("status"),
            request.form.get("reason"),
        )
    except ValidationError as exc:
        return _detail(study, " ".join(exc.errors.values()), 400)
    except services.RuleViolation as exc:
        return _detail(study, str(exc), 409)
    flash(f"{study.study_id} is now {Status(study.status).label}.")
    return redirect(url_for("main.study_detail", study_id=study.study_id))


@bp.post("/studies/<study_id>/delete")
@identified_user_required
def study_delete(study_id: str):
    study = _get_or_404(study_id)
    try:
        services.delete_study(
            get_session(), current_user(), study.study_id, request.form.get("reason")
        )
    except ValidationError as exc:
        return _detail(study, " ".join(exc.errors.values()), 400)
    flash(f"Deleted {study.study_id}. Its audit history is kept.")
    return redirect(url_for("main.study_list"))


@bp.get("/studies/<study_id>/audit")
@identified_user_required
def study_audit(study_id: str):
    db = get_session()
    try:
        entries = services.study_history(db, study_id)
    except services.NotFound:
        abort(404)
    return render_template(
        "audit.html",
        study_id=normalize_study_id(study_id),
        entries=entries,
        deleted=services.is_deleted(db, study_id),
    )
