"""User identification (REQ-010) and protection against cross-site request forgery.

Users identify themselves by choosing a username; there are no passwords. A validated
system would authenticate users and capture electronic signatures (21 CFR 11.100 to
11.300), which is out of scope (see docs/requirements.md).
"""

import hmac
import secrets
from collections.abc import Callable
from functools import wraps

from flask import Flask, abort, flash, g, redirect, request, session, url_for

from .db import get_session
from .models import User


def current_user() -> User | None:
    if "user" not in g:
        username = session.get("username")
        g.user = get_session().get(User, username) if username else None
    return g.user


def identified_user_required(view: Callable) -> Callable:
    """Send anyone who hasn't identified themselves to the sign-in page. A change they
    were attempting is not made."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            flash("Choose who you are before viewing or changing studies.")
            target = request.full_path.rstrip("?") if request.method == "GET" else None
            return redirect(url_for("main.sign_in", next=target))
        return view(*args, **kwargs)

    return wrapped


def csrf_token() -> str:
    """A random token tied to the session, included in every form and checked on POST."""
    token = session.get("csrf_token")
    if token is None:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def _check_csrf() -> None:
    if request.method != "POST":
        return
    expected = session.get("csrf_token")
    submitted = request.form.get("csrf_token", "")
    if not expected or not hmac.compare_digest(expected, submitted):
        abort(400, description="The form's security token was missing or wrong. Reload the page.")


def init_app(app: Flask) -> None:
    app.before_request(_check_csrf)
    app.jinja_env.globals["csrf_token"] = csrf_token
    app.context_processor(lambda: {"current_user": current_user()})
