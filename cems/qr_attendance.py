"""Faculty-controlled dynamic QR attendance.

A faculty member opens a time-boxed attendance *session* for one of their events. One QR code
(pointing at ``/attend/<token>``) is shown for the whole session. Students scan it, log in with
the existing Flask-Login accounts and are marked present through the app's existing
attendance pipeline, so every existing report keeps working.

Every submission is validated on the server: token, session state, expiry, role, event
eligibility and duplicates. The browser countdown is cosmetic only.
"""

import secrets
from datetime import timedelta
from functools import wraps
from io import BytesIO
from types import SimpleNamespace

import qrcode
from flask import (Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request,
                   send_file, url_for)
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError

from .extensions import db, limiter
from .features import normalize_role, utcnow

DEFAULT_MINUTES = 10
MAX_MINUTES = 15
MIN_MINUTES = 1
ELIGIBLE_REGISTRATION = ("approved", "confirmed")
METHOD = "qr_session"

ctx = SimpleNamespace()
bp = Blueprint("qrattend", __name__)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class AttendanceSession(db.Model):
    __tablename__ = "attendance_session"
    id = db.Column(db.Integer, primary_key=True)
    ref = db.Column(db.String(20), unique=True, nullable=False, index=True)    # used in faculty URLs
    token = db.Column(db.String(64), unique=True, nullable=False, index=True)  # secret, only in the QR URL
    event_id = db.Column(db.Integer, db.ForeignKey("event.id"), nullable=False, index=True)
    faculty_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    closed_at = db.Column(db.DateTime)
    event = db.relationship("Event", backref=db.backref("attendance_sessions", lazy="dynamic"))
    faculty = db.relationship("User", foreign_keys=[faculty_id])
    marks = db.relationship("AttendanceSessionMark", backref="session", cascade="all, delete-orphan",
                            order_by="AttendanceSessionMark.marked_at")

    @property
    def status(self):
        """active | expired | closed — always derived from the clock, never trusted from the browser."""
        if not self.is_active:
            return "closed"
        if utcnow() >= self.expires_at:
            return "expired"
        return "active"

    @property
    def seconds_left(self):
        return max(int((self.expires_at - utcnow()).total_seconds()), 0) if self.status == "active" else 0


class AttendanceSessionMark(db.Model):
    __tablename__ = "attendance_session_mark"
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("attendance_session.id"), nullable=False, index=True)
    registration_id = db.Column(db.Integer, db.ForeignKey("registration.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    marked_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    __table_args__ = (db.UniqueConstraint("session_id", "user_id", name="uq_attendance_session_user"),)
    user = db.relationship("User", foreign_keys=[user_id])
    registration = db.relationship("Registration", foreign_keys=[registration_id])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def faculty_or_admin(fn):
    @wraps(fn)
    @login_required
    def wrapper(*args, **kwargs):
        if normalize_role(current_user.role) not in ("faculty", "admin"):
            flash("You do not have permission to access this page.", "danger")
            return redirect(url_for("dashboard"))
        return fn(*args, **kwargs)
    return wrapper


def _is_admin():
    return normalize_role(current_user.role) == "admin"


def _can_manage_event(event):
    if _is_admin():
        return True
    return ctx.EventFaculty.query.filter_by(faculty_id=current_user.id, event_id=event.id).first() is not None


def _manageable_events():
    query = ctx.Event.query.filter(ctx.Event.status.in_(("approved", "completed")))
    if not _is_admin():
        ids = [row.event_id for row in ctx.EventFaculty.query.filter_by(faculty_id=current_user.id).all()]
        if not ids:
            return []
        query = query.filter(ctx.Event.id.in_(ids))
    return query.order_by(ctx.Event.date.desc()).all()


def _own_session_or_404(ref):
    """Session by its public ref; 404 (not 403) for anyone not allowed, so refs reveal nothing."""
    session = AttendanceSession.query.filter_by(ref=ref).first_or_404()
    if not _is_admin() and session.faculty_id != current_user.id:
        abort(404)
    if not _can_manage_event(session.event):
        abort(404)
    return session


def _clamp_minutes(raw):
    try:
        minutes = int(raw)
    except (TypeError, ValueError):
        minutes = DEFAULT_MINUTES
    return min(max(minutes, MIN_MINUTES), MAX_MINUTES)


def _attend_url(session):
    base = (current_app.config.get("PUBLIC_BASE_URL") or "").rstrip("/")
    path = url_for("qrattend.attend", token=session.token)
    return base + path if base else url_for("qrattend.attend", token=session.token, _external=True)


def _iso(dt):
    return dt.isoformat() + "Z" if dt else None


def _close_stale_sessions(event_id):
    now = utcnow()
    for old in AttendanceSession.query.filter_by(event_id=event_id, is_active=True).all():
        old.is_active = False
        old.closed_at = min(now, old.expires_at)


def _session_rows(session, query=""):
    query = (query or "").strip().lower()
    rows = []
    for mark in session.marks:
        user = mark.user
        profile = getattr(user, "student_account_profile", None)
        roll = (profile.roll_no if profile else None) or user.roll_no or ""
        if query and query not in f"{user.name} {user.email} {roll}".lower():
            continue
        rows.append({
            "name": user.name, "roll_no": roll,
            "department": (profile.department if profile else None) or user.department or "",
            "status": "present", "checked_in": _iso(mark.marked_at),
            "checked_in_label": mark.marked_at.strftime("%d %b %Y, %I:%M:%S %p"),
        })
    return rows


def _state_payload(session):
    eligible = ctx.Registration.query.filter(
        ctx.Registration.event_id == session.event_id,
        ctx.Registration.status.in_(ELIGIBLE_REGISTRATION)).count()
    return {
        "status": session.status, "seconds_left": session.seconds_left,
        "expires_at": _iso(session.expires_at), "count": len(session.marks), "eligible": eligible,
    }


# ---------------------------------------------------------------------------
# Faculty / admin routes
# ---------------------------------------------------------------------------
@bp.route("/faculty/attendance-qr")
@faculty_or_admin
def generate():
    events = _manageable_events()
    selected = request.args.get("event_id", type=int)
    event_ids = [e.id for e in events]
    sessions = (AttendanceSession.query.filter(AttendanceSession.event_id.in_(event_ids))
                .order_by(AttendanceSession.created_at.desc()).limit(15).all()) if event_ids else []
    if not _is_admin():
        sessions = [s for s in sessions if s.faculty_id == current_user.id]
    return render_template("attendance_qr/generate.html", events=events, selected=selected, sessions=sessions,
                           default_minutes=DEFAULT_MINUTES, max_minutes=MAX_MINUTES)


@bp.route("/faculty/attendance-qr/start", methods=["POST"])
@faculty_or_admin
def start():
    event = ctx.Event.query.get(request.form.get("event_id", type=int) or 0)
    if event is None or not _can_manage_event(event):
        flash("You are not authorised to take attendance for that event.", "danger")
        return redirect(url_for("qrattend.generate"))
    if event.status not in ("approved", "completed"):
        flash("Attendance can only be taken for approved events.", "danger")
        return redirect(url_for("qrattend.generate"))
    minutes = _clamp_minutes(request.form.get("minutes"))
    _close_stale_sessions(event.id)
    now = utcnow()
    session = AttendanceSession(
        ref=secrets.token_hex(8), token=secrets.token_urlsafe(32), event_id=event.id, faculty_id=current_user.id,
        created_at=now, expires_at=now + timedelta(minutes=minutes), is_active=True)
    db.session.add(session)
    db.session.commit()
    flash(f"Attendance session started for {minutes} minute(s).", "success")
    return redirect(url_for("qrattend.view", ref=session.ref))


@bp.route("/faculty/attendance-qr/<ref>")
@faculty_or_admin
def view(ref):
    session = _own_session_or_404(ref)
    return render_template("attendance_qr/session.html", s=session, attend_url=_attend_url(session),
                           state=_state_payload(session), rows=_session_rows(session))


@bp.route("/faculty/attendance-qr/<ref>/qr.png")
@faculty_or_admin
def qr_image(ref):
    session = _own_session_or_404(ref)
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=12, border=3)
    qr.add_data(_attend_url(session))
    qr.make(fit=True)
    buffer = BytesIO()
    qr.make_image(fill_color="#9d174d", back_color="white").save(buffer, format="PNG")
    buffer.seek(0)
    response = send_file(buffer, mimetype="image/png")
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.route("/faculty/attendance-qr/<ref>/status")
@faculty_or_admin
def status(ref):
    session = _own_session_or_404(ref)
    payload = _state_payload(session)
    payload["rows"] = _session_rows(session, request.args.get("q", ""))
    response = jsonify(payload)
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.route("/faculty/attendance-qr/<ref>/close", methods=["POST"])
@faculty_or_admin
def close(ref):
    session = _own_session_or_404(ref)
    if session.is_active:
        session.is_active = False
        session.closed_at = min(utcnow(), session.expires_at)
        db.session.commit()
        flash("Attendance session ended. The QR code no longer accepts attendance.", "success")
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"success": True, **_state_payload(session)})
    return redirect(url_for("qrattend.view", ref=session.ref))


# ---------------------------------------------------------------------------
# Student routes
# ---------------------------------------------------------------------------
MESSAGES = {
    "success": ("Attendance recorded", "You have been marked present. Thank you!"),
    "duplicate": ("Already marked", "Your attendance for this event is already recorded."),
    "expired": ("Session expired", "This attendance session has expired. Ask your faculty to start a new one."),
    "closed": ("Session closed", "Your faculty has ended this attendance session."),
    "unauthorized": ("Not eligible", "Only students with a confirmed registration for this event can mark attendance here."),
    "invalid": ("Invalid QR code", "This attendance link is not valid. Please scan the code shown by your faculty."),
}


def _render_attend(state, session=None, status_code=200, **extra):
    title, message = MESSAGES[state]
    return render_template("attendance_qr/attend.html", state=state, title=title, message=message,
                           s=session, event=session.event if session else None, **extra), status_code


def _eligibility(session):
    """(registration, state) — registration is None unless the logged-in account may mark attendance."""
    if normalize_role(current_user.role) != "student":
        return None, "unauthorized"
    registration = ctx.Registration.query.filter(
        ctx.Registration.user_id == current_user.id, ctx.Registration.event_id == session.event_id,
        ctx.Registration.status.in_(ELIGIBLE_REGISTRATION)).first()
    if registration is None:
        return None, "unauthorized"
    already = (AttendanceSessionMark.query.filter_by(session_id=session.id, user_id=current_user.id).first()
               or registration.attended)
    return registration, "duplicate" if already else "ready"


@bp.route("/attend/<token>", methods=["GET", "POST"])
@limiter.limit("30 per minute", methods=["POST"])
@login_required   # anonymous users go to login and come back here via ?next=
def attend(token):
    session = AttendanceSession.query.filter_by(token=token).first() if 20 <= len(token) <= 64 else None
    if session is None:
        return _render_attend("invalid", status_code=404)

    if request.method == "GET":
        if session.status != "active":
            return _render_attend(session.status, session, 410)
        registration, state = _eligibility(session)
        if state == "ready":
            return render_template("attendance_qr/attend.html", state="ready", s=session, event=session.event,
                                   title="Confirm your attendance", message=None, seconds_left=session.seconds_left)
        return _render_attend(state, session, 403 if state == "unauthorized" else 200)

    return _submit(session)


def _submit(session):
    # Re-validated on every submission, regardless of what the page showed.
    if session.status != "active":
        return _render_attend(session.status, session, 410)
    registration, state = _eligibility(session)
    if state != "ready":
        return _render_attend(state, session, 403 if state == "unauthorized" else 200)
    try:
        db.session.add(AttendanceSessionMark(session_id=session.id, registration_id=registration.id,
                                             user_id=current_user.id))
        db.session.flush()
        ctx.save_attendance(registration, "present", method=METHOD)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return _render_attend("duplicate", session)
    return _render_attend("success", session)


def init_app(app, **objects):
    ctx.__dict__.update(objects)
    app.register_blueprint(bp)
