"""
Web UI blueprint — cookie-based auth wrapping the same JWT API.

The JWT is stored in a session cookie so the browser dashboard can
authenticate without the user manually managing tokens.
"""
from functools import wraps

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_jwt_extended import create_access_token, create_refresh_token, decode_token

from . import db
from .models import Timer, User

web_bp = Blueprint("web", __name__)


def _login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "jwt_token" not in session:
            return redirect(url_for("web.login_page"))
        try:
            decoded = decode_token(session["jwt_token"])
            request.current_user_id = int(decoded["sub"])
        except Exception:
            session.pop("jwt_token", None)
            return redirect(url_for("web.login_page"))
        return f(*args, **kwargs)

    return wrapper


@web_bp.route("/")
def index():
    if "jwt_token" in session:
        return redirect(url_for("web.dashboard"))
    return redirect(url_for("web.login_page"))


@web_bp.route("/login", methods=["GET", "POST"])
def login_page():
    if "jwt_token" in session:
        return redirect(url_for("web.dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            session["jwt_token"] = create_access_token(identity=str(user.id))
            session["refresh_token"] = create_refresh_token(identity=str(user.id))
            session["username"] = username
            flash("Login successful!", "success")
            return redirect(url_for("web.dashboard"))
        else:
            flash("Invalid username or password.", "error")

    return render_template("login.html")


@web_bp.route("/register", methods=["GET", "POST"])
def register_page():
    if "jwt_token" in session:
        return redirect(url_for("web.dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        errors = []
        if len(username) < 3:
            errors.append("Username must be at least 3 characters.")
        if len(password) < 8:
            errors.append("Password must be at least 8 characters.")
        if password != confirm:
            errors.append("Passwords do not match.")
        if User.query.filter_by(username=username).first():
            errors.append("Username already taken.")

        if errors:
            for e in errors:
                flash(e, "error")
        else:
            user = User(username=username)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            flash("Account created! Please log in.", "success")
            return redirect(url_for("web.login_page"))

    return render_template("register.html")


@web_bp.route("/dashboard")
@_login_required
def dashboard():
    user_id = request.current_user_id
    timers = (
        Timer.query.filter_by(user_id=user_id)
        .order_by(Timer.created_at.desc())
        .all()
    )
    return render_template(
        "dashboard.html",
        timers=timers,
        username=session.get("username", ""),
        jwt_token=session.get("jwt_token", ""),
        refresh_token=session.get("refresh_token", ""),
    )


@web_bp.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("web.login_page"))
