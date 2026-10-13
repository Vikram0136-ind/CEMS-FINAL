"""HTTP routes for the extended CEMS modules (see :mod:`cems.features`)."""

from datetime import timedelta
from functools import wraps
from types import SimpleNamespace

from flask import (Blueprint, abort, flash, g, jsonify, redirect, render_template, request, url_for)
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError

from . import chatbot
from . import features as f
from .extensions import db, limiter
from .features import ACTIVE, ctx, normalize_role, utcnow

bp = Blueprint("features", __name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def roles_required(*roles):
    allowed = {normalize_role(r) for r in roles}

    def decorator(fn):
        @wraps(fn)
        @login_required
        def wrapper(*args, **kwargs):
            if normalize_role(current_user.role) not in allowed:
                flash("You do not have permission to access this page.", "danger")
                return redirect(url_for("dashboard"))
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def wants_json():
    return request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json


def csv_download(filename, header, rows):
    return ctx.csv_response(filename, header, rows)


def back(default_endpoint, **values):
    target = request.form.get("next") or ""
    if target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return redirect(target)
    return redirect(url_for(default_endpoint, **values))


def get_event_or_404(event_id):
    return ctx.Event.query.get_or_404(event_id)


def clean(value, limit):
    return (value or "").strip()[:limit]


def to_float(value):
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


# ---------------------------------------------------------------------------
# Wishlist
# ---------------------------------------------------------------------------
@bp.route("/events/<int:event_id>/wishlist", methods=["POST"])
@login_required
def toggle_wishlist(event_id):
    event = get_event_or_404(event_id)
    if event.status not in ("approved", "completed"):
        abort(404)
    saved = f.toggle_wishlist(current_user, event)
    if wants_json():
        return jsonify({"success": True, "saved": saved})
    flash("Event saved to your wishlist." if saved else "Event removed from your wishlist.", "success")
    return back("event_details", event_id=event.id)


@bp.route("/wishlist")
@login_required
def wishlist():
    items = (f.WishlistItem.query.filter_by(user_id=current_user.id)
             .order_by(f.WishlistItem.created_at.desc()).all())
    registered = {r.event_id: r for r in ctx.Registration.query.filter(
        ctx.Registration.user_id == current_user.id, ctx.Registration.status.in_(ACTIVE + ("waitlisted",))).all()}
    return render_template("features/wishlist.html", items=items, registered=registered, today=utcnow().date(),
                           seats_left=f.seats_left)


# ---------------------------------------------------------------------------
# Leaderboard, achievements
# ---------------------------------------------------------------------------
@bp.route("/leaderboard")
@login_required
def leaderboard():
    return render_template("features/leaderboard.html", board=f.build_leaderboard())


@bp.route("/student/achievements")
@roles_required("student")
def achievements():
    rows = (f.AchievementPoint.query.filter_by(user_id=current_user.id)
            .order_by(f.AchievementPoint.created_at.desc()).all())
    totals = f.points_by_user()
    ranking = sorted(totals.items(), key=lambda kv: -kv[1])
    position = next((i for i, (uid, _) in enumerate(ranking, 1) if uid == current_user.id), None)
    dept_total = sum(points for uid, points in totals.items()
                     if (u := db.session.get(ctx.User, uid)) and f.user_dept(u) == f.user_dept(current_user))
    return render_template("features/achievements.html", rows=rows, total=totals.get(current_user.id, 0),
                           position=position, participants=len(ranking), dept=f.user_dept(current_user),
                           dept_total=dept_total)


# ---------------------------------------------------------------------------
# Department dashboard, reports
# ---------------------------------------------------------------------------
@bp.route("/dashboard/departments")
@roles_required("admin", "organizer", "faculty")
def department_dashboard():
    board = f.build_department_board(request.args)
    own = f.user_dept(current_user) if normalize_role(current_user.role) == "faculty" else None
    totals = SimpleNamespace(
        students=sum(d.students for d in board.rows), registrations=sum(d.registrations for d in board.rows),
        attended=sum(d.attended for d in board.rows), winners=sum(d.winners for d in board.rows))
    totals.rate = f.pct(totals.attended, totals.registrations)
    return render_template("features/department_dashboard.html", board=board, totals=totals, own_dept=own,
                           max_regs=max([d.registrations for d in board.rows] or [1]) or 1)


@bp.route("/dashboard/departments/detail")
@roles_required("admin", "organizer", "faculty")
def department_detail():
    dept = f.norm_dept(request.args.get("dept", ""))
    profiles = f.profile_map()
    students = [u for u in ctx.User.query.filter_by(role="student").all() if f.user_dept(u) == dept]
    if not students and dept != "Unassigned":
        flash("No students found for that department.", "warning")
        return redirect(url_for("features.department_dashboard"))
    points = f.points_by_user()
    ids = {s.id for s in students}
    regs = [r for r in ctx.Registration.query.filter(ctx.Registration.status.in_(ACTIVE)).all() if r.user_id in ids]
    by_event = {}
    for reg in regs:
        row = by_event.setdefault(reg.event_id, SimpleNamespace(event=reg.event, regs=[]))
        row.regs.append(reg)
    event_rows = sorted((SimpleNamespace(event=r.event, stats=f.reg_stats(r.regs)) for r in by_event.values()),
                        key=lambda r: r.event.date, reverse=True)
    student_rows = sorted((SimpleNamespace(user=s, profile=profiles.get(s.id), points=points.get(s.id, 0),
                                           events=sum(1 for r in regs if r.user_id == s.id),
                                           attended=sum(1 for r in regs if r.user_id == s.id and r.attended))
                           for s in students), key=lambda r: (-r.points, r.user.name))
    return render_template("features/department_detail.html", dept=dept, student_rows=student_rows,
                           event_rows=event_rows, stats=f.reg_stats(regs), total_points=sum(r.points for r in student_rows))


@bp.route("/reports/date-range")
@roles_required("admin", "organizer", "faculty")
def date_report():
    report = f.build_date_report(current_user, request.args)
    export = request.args.get("export")
    if export == "events":
        rows = [[r.event.title, r.event.category, r.event.date.isoformat(), r.event.start_time, r.event.venue,
                 r.event.status, r.stats.registered, r.stats.attended, r.stats.waitlisted, f"{r.stats.rate}%", r.winners]
                for r in report.rows]
        return csv_download(f"events-{report.date_from}-to-{report.date_to}.csv",
                            ["Event", "Category", "Date", "Start", "Venue", "Status", "Registered", "Attended",
                             "Waitlisted", "Attendance rate", "Winners published"], rows)
    if export == "participants":
        rows = []
        for p in report.participants:
            rows.append([p.reg.user.name, p.reg.user.email, p.profile.student_id if p.profile else "",
                         p.profile.roll_no if p.profile else "", p.dept, p.profile.batch if p.profile else "",
                         p.profile.semester if p.profile else "", f.semester_parity(p.profile.semester if p.profile else None) or "",
                         p.event.title, p.event.date.isoformat(), "Yes" if p.reg.attended else "No"])
        return csv_download(f"participants-{report.date_from}-to-{report.date_to}.csv",
                            ["Name", "Email", "Student ID", "Roll no", "Department", "Batch", "Semester",
                             "Odd/Even", "Event", "Event date", "Attended"], rows)
    today = utcnow().date()
    month_start = today.replace(day=1)
    presets = [("Today", today, today), ("Last 7 days", today - timedelta(days=6), today),
               ("Last 30 days", today - timedelta(days=29), today), ("This month", month_start, today),
               ("Next 30 days", today, today + timedelta(days=30))]
    return render_template("features/date_report.html", r=report, presets=presets)


@bp.route("/reports/faculty")
@roles_required("admin", "organizer", "faculty")
def faculty_report():
    report = f.build_faculty_report(current_user, request.args)
    selected = None
    faculty_id = request.args.get("faculty_id", type=int)
    if faculty_id:
        selected = next((row for row in report.rows if row.faculty.id == faculty_id), None)
    if normalize_role(current_user.role) == "faculty" and report.rows:
        selected = report.rows[0]
    if request.args.get("export") == "csv":
        rows = [[r.faculty.name, r.department, len(r.events), r.completed, r.upcoming, r.stats.registered,
                 r.stats.attended, f"{r.stats.rate}%", r.avg_rating if r.avg_rating is not None else "", r.marks, r.winners]
                for r in report.rows]
        return csv_download("faculty-event-report.csv",
                            ["Faculty", "Department", "Events", "Completed", "Upcoming", "Registered", "Attended",
                             "Attendance rate", "Avg rating", "Attendance marks", "Winners"], rows)
    return render_template("features/faculty_report.html", report=report, selected=selected)


@bp.route("/faculty/attendance-history")
@roles_required("faculty", "admin")
def attendance_history():
    role = normalize_role(current_user.role)
    faculty = current_user
    faculty_list = []
    if role == "admin":
        faculty_list = ctx.User.query.filter(ctx.User.role.in_(("faculty", "teacher"))).order_by(ctx.User.name).all()
        faculty = db.session.get(ctx.User, request.args.get("faculty_id", type=int) or 0) or (faculty_list[0] if faculty_list else None)
    if faculty is None:
        return render_template("features/attendance_history.html", faculty=None, faculty_list=faculty_list, summary=[],
                               logs=None, events=[], filters={})
    event_ids = f.assigned_event_ids(faculty)
    events = ctx.Event.query.filter(ctx.Event.id.in_(event_ids)).order_by(ctx.Event.date.desc()).all() if event_ids else []
    event_filter = request.args.get("event_id", type=int)
    action = request.args.get("action", "")
    date_from, date_to = f.parse_date(request.args.get("from")), f.parse_date(request.args.get("to"))
    query = f.AttendanceLog.query.filter(f.AttendanceLog.event_id.in_(event_ids or [0]))
    if event_filter and event_filter in event_ids:
        query = query.filter(f.AttendanceLog.event_id == event_filter)
    if action in ("present", "absent", "late", "in", "out"):
        query = query.filter(f.AttendanceLog.action == action)
    if date_from:
        query = query.filter(f.AttendanceLog.at >= date_from)
    if date_to:
        query = query.filter(f.AttendanceLog.at < date_to + timedelta(days=1))
    query = query.order_by(f.AttendanceLog.at.desc(), f.AttendanceLog.id.desc())

    if request.args.get("export") == "csv":
        rows = [[l.at.strftime("%Y-%m-%d %H:%M:%S"), l.event.title, l.registration.user.name,
                 l.registration.user.roll_no or "", l.action, l.method or "", l.actor.name if l.actor else ""]
                for l in query.limit(5000).all()]
        return csv_download(f"attendance-history-{faculty.id}.csv",
                            ["Time", "Event", "Student", "Roll no", "Action", "Method", "Marked by"], rows)

    summary = []
    for event in events:
        regs = [r for r in event.registrations if r.status in ("confirmed", "approved")]
        records = {rec.registration_id: rec for rec in ctx.AttendanceRecord.query.filter(
            ctx.AttendanceRecord.registration_id.in_([r.id for r in regs] or [0])).all()}
        counts = {"present": 0, "late": 0, "absent": 0}
        for reg in regs:
            rec = records.get(reg.id)
            status = rec.status if rec else ("present" if reg.attended else None)
            if status in counts:
                counts[status] += 1
        last = (f.AttendanceLog.query.filter(f.AttendanceLog.event_id == event.id,
                                             f.AttendanceLog.action.in_(("present", "absent", "late")))
                .order_by(f.AttendanceLog.at.desc()).first())
        summary.append(SimpleNamespace(event=event, registered=len(regs), counts=counts,
                                       unmarked=len(regs) - sum(counts.values()),
                                       rate=f.pct(counts["present"] + counts["late"], len(regs)),
                                       last=last.at if last else None,
                                       mine=f.AttendanceLog.query.filter(
                                           f.AttendanceLog.event_id == event.id, f.AttendanceLog.actor_id == faculty.id,
                                           f.AttendanceLog.action.in_(("present", "absent", "late"))).count()))
    page = max(request.args.get("page", 1, type=int), 1)
    logs = query.paginate(page=page, per_page=40, error_out=False)
    return render_template("features/attendance_history.html", faculty=faculty, faculty_list=faculty_list,
                           summary=summary, logs=logs, events=events,
                           filters=dict(event_id=event_filter, action=action, date_from=request.args.get("from", ""),
                                        date_to=request.args.get("to", "")))


# ---------------------------------------------------------------------------
# Entry / exit tracking
# ---------------------------------------------------------------------------
def operable_events():
    query = f.scoped_events_query(current_user).filter(ctx.Event.status.in_(("approved", "completed")))
    return query.order_by(ctx.Event.date.desc()).all()


@bp.route("/entry-exit")
@roles_required("admin", "organizer", "faculty")
def entry_exit_index():
    rows = []
    for event in operable_events():
        presence = f.presence_map(event.id)
        rows.append(SimpleNamespace(event=event, inside=sum(1 for p in presence.values() if p.inside),
                                    visited=len(presence), registered=f.active_count(event)))
    return render_template("features/entry_exit_index.html", rows=rows)


def entry_exit_event(event_id):
    event = get_event_or_404(event_id)
    if not f.can_operate_event(current_user, event):
        abort(403)
    return event


@bp.route("/events/<int:event_id>/entry-exit")
@roles_required("admin", "organizer", "faculty")
def entry_exit(event_id):
    event = entry_exit_event(event_id)
    regs = (ctx.Registration.query.filter(ctx.Registration.event_id == event.id,
                                          ctx.Registration.status.in_(("confirmed", "approved")))
            .order_by(ctx.Registration.registered_at.asc()).all())
    presence = f.presence_map(event.id)
    rows = []
    for reg in regs:
        state = presence.get(reg.id)
        live = getattr(state, "seconds_live", 0) if state else 0
        rows.append(SimpleNamespace(reg=reg, state=state, duration=f.format_duration((state.seconds if state else 0) + live)))
    if request.args.get("export") == "csv":
        data = [[r.reg.ticket_code, r.reg.user.name, r.reg.user.roll_no or "",
                 r.state.first_in.strftime("%Y-%m-%d %H:%M:%S") if r.state and r.state.first_in else "",
                 r.state.last_out.strftime("%Y-%m-%d %H:%M:%S") if r.state and r.state.last_out else "",
                 r.state.visits if r.state else 0, r.duration, "Inside" if r.state and r.state.inside else "Outside"]
                for r in rows]
        return csv_download(f"entry-exit-{event.id}.csv",
                            ["Ticket", "Name", "Roll no", "First entry", "Last exit", "Visits", "Time inside", "Now"], data)
    return render_template("features/entry_exit.html", event=event, rows=rows,
                           inside=sum(1 for r in rows if r.state and r.state.inside),
                           visited=sum(1 for r in rows if r.state))


@bp.route("/events/<int:event_id>/entry-exit/scan", methods=["POST"])
@roles_required("admin", "organizer", "faculty")
def entry_exit_scan(event_id):
    event = entry_exit_event(event_id)
    code = clean(request.form.get("ticket_code"), 30).upper()
    direction = "out" if request.form.get("direction") == "out" else "in"
    reg = ctx.Registration.query.filter_by(ticket_code=code, event_id=event.id).first() if code else None
    if reg is None:
        flash("Ticket not found for this event.", "danger")
    else:
        status, message = (f.record_exit if direction == "out" else f.record_entry)(reg, current_user, "entry_desk")
        if status == "ok":
            db.session.commit()
        else:
            db.session.rollback()
        flash(message, "success" if status == "ok" else "warning")
    return redirect(url_for("features.entry_exit", event_id=event.id))


@bp.route("/events/<int:event_id>/entry-exit/<int:registration_id>/<direction>", methods=["POST"])
@roles_required("admin", "organizer", "faculty")
def entry_exit_mark(event_id, registration_id, direction):
    event = entry_exit_event(event_id)
    if direction not in ("in", "out"):
        abort(404)
    reg = ctx.Registration.query.filter_by(id=registration_id, event_id=event.id).first_or_404()
    status, message = (f.record_exit if direction == "out" else f.record_entry)(reg, current_user, "entry_desk")
    if status == "ok":
        db.session.commit()
    else:
        db.session.rollback()
    flash(message, "success" if status == "ok" else "warning")
    return redirect(url_for("features.entry_exit", event_id=event.id))


# ---------------------------------------------------------------------------
# Waitlist + cancellation
# ---------------------------------------------------------------------------
@bp.route("/events/<int:event_id>/waitlist")
@roles_required("student")
def waitlist_status(event_id):
    event = get_event_or_404(event_id)
    registration = ctx.Registration.query.filter_by(user_id=current_user.id, event_id=event.id,
                                                    status="waitlisted").first()
    queue = f.waitlist_queue(event)
    student_waitlist = None
    position = f.waitlist_position(registration) if registration else None
    if registration:
        student_waitlist = SimpleNamespace(waitlist_position=position, status="waiting", registration=registration)
    return render_template("student/waitlist_status.html", event=event, student_waitlist=student_waitlist,
                           waitlist_ahead=(position - 1) if position else 0, waitlist_total=len(queue),
                           seats_available=f.seats_left(event))


@bp.route("/registration/<int:registration_id>/cancel", methods=["POST"])
@roles_required("student")
def student_cancel_registration(registration_id):
    registration = ctx.Registration.query.get_or_404(registration_id)
    if registration.user_id != current_user.id:
        abort(403)
    event = registration.event
    if event.date and event.date < utcnow().date():
        flash("Past events cannot be cancelled.", "warning")
        return redirect(url_for("my_registrations"))
    ok, message = f.cancel_registration(registration, current_user)
    flash(message, "success" if ok else "warning")
    return redirect(url_for("my_registrations"))


# ---------------------------------------------------------------------------
# Teams
# ---------------------------------------------------------------------------
def team_event_or_404(event_id):
    event = get_event_or_404(event_id)
    if not event.is_team_event:
        abort(404)
    return event


def _team_precheck(event):
    """Shared eligibility gate for creating / joining a team. Returns an error message or None."""
    eligibility, existing = ctx.registration_eligibility(event, current_user)
    if existing is not None:
        return "You are already registered for this event."
    if not eligibility["eligible"]:
        return eligibility["message"]
    if f.duplicate_conflict(event, current_user):
        return ("Another account with the same student / roll ID is already registered for this event. "
                "Contact the organizer if this is a mistake.")
    return None


def _after_team_join(event, registration):
    if (event.fee or 0) > 0:
        flash("Team registration saved. Complete the payment to confirm your seat.", "info")
        return redirect(url_for("demo_payment", event_id=event.id))
    return redirect(url_for("features.team_page", event_id=event.id))


@bp.route("/events/<int:event_id>/team")
@roles_required("student")
def team_page(event_id):
    event = team_event_or_404(event_id)
    team = f.team_for_user(event, current_user)
    minimum, maximum = f.team_limits(event)
    can_start = False
    if team is None:
        eligibility, existing = ctx.registration_eligibility(event, current_user)
        can_start = existing is None and eligibility["eligible"]
    return render_template("features/team.html", event=event, team=team, min_size=minimum, max_size=maximum,
                           is_leader=bool(team and team.leader_id == current_user.id), can_start=can_start)


@bp.route("/events/<int:event_id>/team/create", methods=["POST"])
@roles_required("student")
def team_create(event_id):
    event = team_event_or_404(event_id)
    if not request.form.get("terms_accepted"):
        flash("Please accept the event rules and cancellation policy to continue.", "danger")
        return redirect(url_for("register_event", event_id=event.id))
    name = clean(request.form.get("team_name"), 80)
    error = _team_precheck(event)
    if error is None and len(name) < 3:
        error = "Give your team a name (at least 3 characters)."
    if error is None and f.Team.query.filter(f.Team.event_id == event.id,
                                             db.func.lower(f.Team.name) == name.lower()).first():
        error = "That team name is already taken for this event."
    if error:
        flash(error, "danger")
        return redirect(url_for("register_event", event_id=event.id))
    try:
        registration = f.create_registration(event, current_user)
        team = f.Team(event_id=event.id, name=name, leader_id=current_user.id, invite_code=f.new_invite_code())
        db.session.add(team)
        db.session.flush()
        db.session.add(f.TeamMember(team_id=team.id, user_id=current_user.id, registration_id=registration.id))
        f.notify(current_user.id, "Team created",
                 f"You are the leader of “{team.name}” for {event.title}. Invite code: {team.invite_code}",
                 category="registration", event_id=event.id)
        f.notify(event.organizer_id, "New team registered", f"Team “{team.name}” (leader {current_user.name}) registered for {event.title}.",
                 category="registration", event_id=event.id)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("Could not create the team. Please try again.", "danger")
        return redirect(url_for("register_event", event_id=event.id))
    flash(f"Team “{team.name}” created. Share the invite code with your teammates.", "success")
    return _after_team_join(event, registration)


@bp.route("/events/<int:event_id>/team/join", methods=["POST"])
@roles_required("student")
def team_join(event_id):
    event = team_event_or_404(event_id)
    code = clean(request.form.get("invite_code"), 16).upper()
    team = f.Team.query.filter_by(event_id=event.id, invite_code=code).first() if code else None
    error = None
    if team is None:
        error = "That invite code does not match any team for this event."
    else:
        error = _team_precheck(event)
    if error is None and len(team.members) >= f.team_limits(event)[1]:
        error = f"This team is full (maximum {f.team_limits(event)[1]} members)."
    if error:
        flash(error, "danger")
        return redirect(url_for("register_event", event_id=event.id))
    try:
        registration = f.create_registration(event, current_user)
        db.session.add(f.TeamMember(team_id=team.id, user_id=current_user.id, registration_id=registration.id))
        f.notify(team.leader_id, "New team member", f"{current_user.name} joined “{team.name}”.", category="registration",
                 event_id=event.id)
        f.notify(current_user.id, "Joined team", f"You joined “{team.name}” for {event.title}.", category="registration",
                 event_id=event.id)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("Could not join the team. Please try again.", "danger")
        return redirect(url_for("register_event", event_id=event.id))
    flash(f"You joined “{team.name}”.", "success")
    return _after_team_join(event, registration)


def _own_team(team_id, leader_only=True):
    team = f.Team.query.get_or_404(team_id)
    member = next((m for m in team.members if m.user_id == current_user.id), None)
    if member is None or (leader_only and team.leader_id != current_user.id):
        abort(403)
    return team


@bp.route("/team/<int:team_id>/remove/<int:user_id>", methods=["POST"])
@roles_required("student")
def team_remove(team_id, user_id):
    team = _own_team(team_id)
    member = next((m for m in team.members if m.user_id == user_id), None)
    if member is None or user_id == team.leader_id:
        flash("Choose a team member to remove (the leader cannot be removed).", "warning")
    else:
        registration = member.registration
        user_name = member.user.name
        db.session.delete(member)
        db.session.flush()
        registration.status = "cancelled"
        if registration.payment_status in ("paid", "successful"):
            registration.payment_status = "refund_pending"
        f.notify(user_id, "Removed from team", f"You were removed from “{team.name}” by the team leader. "
                 "Your registration for this event was cancelled.", category="registration", event_id=team.event_id)
        f.promote_waitlist(team.event, commit=False)
        db.session.commit()
        flash(f"{user_name} removed from the team.", "success")
    return redirect(url_for("features.team_page", event_id=team.event_id))


@bp.route("/team/<int:team_id>/transfer", methods=["POST"])
@roles_required("student")
def team_transfer(team_id):
    team = _own_team(team_id)
    target = request.form.get("user_id", type=int)
    member = next((m for m in team.members if m.user_id == target), None)
    if member is None or target == team.leader_id:
        flash("Choose another team member to become the leader.", "warning")
    else:
        team.leader_id = target
        f.notify(target, "You are now team leader", f"{current_user.name} made you the leader of “{team.name}”.",
                 category="registration", event_id=team.event_id)
        db.session.commit()
        flash(f"{member.user.name} is now the team leader.", "success")
    return redirect(url_for("features.team_page", event_id=team.event_id))


@bp.route("/team/<int:team_id>/regenerate-code", methods=["POST"])
@roles_required("student")
def team_regenerate_code(team_id):
    team = _own_team(team_id)
    team.invite_code = f.new_invite_code()
    db.session.commit()
    flash("A new invite code was generated. The old one no longer works.", "success")
    return redirect(url_for("features.team_page", event_id=team.event_id))


@bp.route("/team/<int:team_id>/leave", methods=["POST"])
@roles_required("student")
def team_leave(team_id):
    team = _own_team(team_id, leader_only=False)
    registration = next(m.registration for m in team.members if m.user_id == current_user.id)
    event_id = team.event_id
    ok, message = f.cancel_registration(registration, current_user, "Left the team")
    flash(message if not ok else "You left the team and your registration was cancelled.", "success" if ok else "warning")
    return redirect(url_for("features.team_page", event_id=event_id) if not ok else url_for("my_registrations"))


@bp.route("/team/<int:team_id>/disband", methods=["POST"])
@roles_required("student")
def team_disband(team_id):
    team = _own_team(team_id)
    event = team.event
    for member in list(team.members):
        registration = member.registration
        registration.status = "cancelled"
        if registration.payment_status in ("paid", "successful"):
            registration.payment_status = "refund_pending"
        if member.user_id != current_user.id:
            f.notify(member.user_id, "Team disbanded", f"“{team.name}” was disbanded by the team leader.",
                     category="registration", event_id=event.id)
    db.session.delete(team)      # members are removed by the delete-orphan cascade
    db.session.flush()
    f.promote_waitlist(event, commit=False)
    db.session.commit()
    flash("Team disbanded and all registrations cancelled.", "success")
    return redirect(url_for("my_registrations"))


# ---------------------------------------------------------------------------
# Competition hub (organizer / admin): rounds, judges, winners
# ---------------------------------------------------------------------------
def managed_event(event_id):
    event = get_event_or_404(event_id)
    if not f.can_manage_event(current_user, event):
        abort(403)
    return event


@bp.route("/events/<int:event_id>/competition")
@roles_required("admin", "organizer", "faculty")
def competition(event_id):
    event = get_event_or_404(event_id)
    if not f.can_operate_event(current_user, event):
        abort(403)
    snap = f.competition_snapshot(event)
    judge_ids = {j.user_id for j in snap.judges}
    candidates = [u for u in ctx.User.query.filter(ctx.User.role.in_(("faculty", "teacher")),
                                                   ctx.User.is_active_account.is_(True)).order_by(ctx.User.name).all()
                  if u.id not in judge_ids]
    winners = f.EventWinner.query.filter_by(event_id=event.id).order_by(
        db.case((f.EventWinner.rank == 0, 99), else_=f.EventWinner.rank), f.EventWinner.category).all()
    return render_template("features/competition.html", event=event, snap=snap, candidates=candidates, winners=winners,
                           can_manage=f.can_manage_event(current_user, event), categories=f.WINNER_CATEGORIES,
                           published=any(w.published for w in winners), min_size=f.team_limits(event)[0],
                           max_size=f.team_limits(event)[1])


@bp.route("/events/<int:event_id>/competition/rounds", methods=["POST"])
@roles_required("admin", "organizer")
def competition_rounds(event_id):
    event = managed_event(event_id)
    action = request.form.get("action", "add")
    rnd = f.EventRound.query.filter_by(id=request.form.get("round_id", type=int), event_id=event.id).first() \
        if request.form.get("round_id") else None
    if action == "add":
        name = clean(request.form.get("name"), 100)
        max_score = to_float(request.form.get("max_score") or 100)
        advance = request.form.get("advance_count", type=int)
        if not name or max_score is None or max_score <= 0 or max_score > 1000:
            flash("Give the round a name and a maximum score between 1 and 1000.", "danger")
        else:
            number = (db.session.query(db.func.max(f.EventRound.number)).filter_by(event_id=event.id).scalar() or 0) + 1
            db.session.add(f.EventRound(event_id=event.id, number=number, name=name,
                                        description=clean(request.form.get("description"), 500) or None,
                                        max_score=max_score, advance_count=advance if advance and advance > 0 else None))
            db.session.commit()
            flash(f"Round {number} added.", "success")
    elif rnd is None:
        flash("Round not found.", "danger")
    elif action == "update":
        max_score = to_float(request.form.get("max_score"))
        advance = request.form.get("advance_count", type=int)
        if max_score is None or max_score <= 0 or max_score > 1000:
            flash("Maximum score must be between 1 and 1000.", "danger")
        else:
            rnd.name = clean(request.form.get("name"), 100) or rnd.name
            rnd.max_score = max_score
            rnd.advance_count = advance if advance and advance > 0 else None
            db.session.commit()
            flash("Round updated.", "success")
    elif action == "delete":
        db.session.delete(rnd)
        db.session.flush()
        for number, row in enumerate(f.EventRound.query.filter_by(event_id=event.id).order_by(f.EventRound.number), 1):
            row.number = number + 1000  # avoid unique clashes while renumbering
        db.session.flush()
        for number, row in enumerate(f.EventRound.query.filter_by(event_id=event.id).order_by(f.EventRound.number), 1):
            row.number = number
        db.session.commit()
        flash("Round deleted.", "success")
    elif action in ("complete", "reopen"):
        rnd.status = "completed" if action == "complete" else "open"
        db.session.flush()
        if action == "complete":
            snap = f.competition_snapshot(event)
            nxt = next((r for r in snap.rounds if r.number == rnd.number + 1), None)
            if nxt:
                for entry_id in snap.participants.get(nxt.id, []):
                    for user in snap.entry_by_id[entry_id].members:
                        f.notify(user.id, f"Advanced to {nxt.name}",
                                 f"Congratulations! You advanced to {nxt.name} of {event.title}.", event_id=event.id,
                                 priority="high")
        db.session.commit()
        flash(f"Round marked {rnd.status}.", "success")
    else:
        abort(400)
    return redirect(url_for("features.competition", event_id=event.id) + "#rounds")


@bp.route("/events/<int:event_id>/competition/judges", methods=["POST"])
@roles_required("admin", "organizer")
def competition_judges(event_id):
    event = managed_event(event_id)
    if request.form.get("action") == "remove":
        row = f.EventJudge.query.filter_by(id=request.form.get("judge_id", type=int), event_id=event.id).first()
        if row:
            db.session.delete(row)
            db.session.commit()
            flash("Judge removed from the panel.", "success")
    else:
        user = db.session.get(ctx.User, request.form.get("user_id", type=int) or 0)
        if user is None or normalize_role(user.role) != "faculty" or not user.is_active_account:
            flash("Choose a faculty member to add to the judge panel.", "danger")
        elif f.EventJudge.query.filter_by(event_id=event.id, user_id=user.id).first():
            flash(f"{user.name} is already on the panel.", "info")
        else:
            db.session.add(f.EventJudge(event_id=event.id, user_id=user.id, assigned_by=current_user.id))
            f.notify(user.id, "Judge panel assignment", f"You were added to the judge panel for {event.title}.",
                     event_id=event.id, action_url="/judge")
            db.session.commit()
            flash(f"{user.name} added to the judge panel.", "success")
    return redirect(url_for("features.competition", event_id=event.id) + "#judges")


@bp.route("/events/<int:event_id>/competition/winners/calculate", methods=["POST"])
@roles_required("admin", "organizer")
def competition_calculate(event_id):
    event = managed_event(event_id)
    created = f.calculate_winners(event, current_user)
    db.session.commit()
    flash(f"Winners calculated automatically ({created} place(s) assigned). Review them, then publish."
          if created else "No scores have been entered yet, so no winners could be calculated.",
          "success" if created else "warning")
    return redirect(url_for("features.competition", event_id=event.id) + "#winners")


@bp.route("/events/<int:event_id>/competition/winners/add", methods=["POST"])
@roles_required("admin", "organizer")
def competition_winner_add(event_id):
    event = managed_event(event_id)
    entry_id = request.form.get("entry_id", type=int)
    category = clean(request.form.get("category"), 60)
    custom = clean(request.form.get("custom_category"), 60)
    category = custom or category
    entries = {e.id: e for e in f.event_entries(event)}
    entry = entries.get(entry_id)
    if entry is None or not category:
        flash("Choose a participant (or team) and a winner category.", "danger")
    elif f.EventWinner.query.filter_by(event_id=event.id, registration_id=entry.id, category=category).first():
        flash("That participant already holds this category.", "info")
    else:
        published = f.EventWinner.query.filter_by(event_id=event.id, published=True).first() is not None
        db.session.add(f.EventWinner(event_id=event.id, registration_id=entry.id,
                                     team_id=entry.team.id if entry.team else None, category=category,
                                     rank=f.CATEGORY_RANK.get(category, 0), auto=False, published=published,
                                     declared_by=current_user.id))
        db.session.flush()
        f.sync_winner_points(event)
        db.session.commit()
        flash(f"{entry.label} added as {category}.", "success")
    return redirect(url_for("features.competition", event_id=event.id) + "#winners")


@bp.route("/events/<int:event_id>/competition/winners/<int:winner_id>/delete", methods=["POST"])
@roles_required("admin", "organizer")
def competition_winner_delete(event_id, winner_id):
    event = managed_event(event_id)
    winner = f.EventWinner.query.filter_by(id=winner_id, event_id=event.id).first_or_404()
    db.session.delete(winner)
    db.session.flush()
    f.sync_winner_points(event)
    db.session.commit()
    flash("Winner removed.", "success")
    return redirect(url_for("features.competition", event_id=event.id) + "#winners")


@bp.route("/events/<int:event_id>/competition/winners/publish", methods=["POST"])
@roles_required("admin", "organizer")
def competition_publish(event_id):
    event = managed_event(event_id)
    publish = request.form.get("mode", "publish") == "publish"
    winners = f.EventWinner.query.filter_by(event_id=event.id).all()
    if not winners:
        flash("Declare at least one winner before publishing.", "warning")
        return redirect(url_for("features.competition", event_id=event.id) + "#winners")
    newly = [w for w in winners if publish and not w.published]
    for winner in winners:
        winner.published = publish
    db.session.flush()
    f.sync_winner_points(event)
    for winner in newly:
        for reg in f._winner_member_regs(winner):
            f.notify(reg.user_id, f"You won: {winner.category}",
                     f"Congratulations! You secured {winner.category} in {event.title}. Your winner certificate is ready.",
                     category="event", event_id=event.id, priority="high", action_url="/student/certificates")
    if publish and newly:
        f.announce_results(event, current_user)
    db.session.commit()
    flash("Results published. Everyone was notified and winners can now be congratulated." if publish
          else "Results unpublished.", "success")
    return redirect(url_for("features.competition", event_id=event.id) + "#winners")


@bp.route("/events/<int:event_id>/winners/<int:winner_id>/congratulate", methods=["POST"])
@login_required
@limiter.limit("30 per minute")
def congratulate_winner(event_id, winner_id):
    event = get_event_or_404(event_id)
    winner = f.EventWinner.query.filter_by(id=winner_id, event_id=event.id).first_or_404()
    sent, problem = f.congratulate(event, winner, current_user, request.form.get("message", ""))
    db.session.commit()
    if wants_json():
        return jsonify({"success": not problem, "sent": sent, "message": problem or "Your wishes were sent!"}), (400 if problem else 200)
    flash(problem or "Your congratulations were sent! 🎉", "warning" if problem else "success")
    return redirect(url_for("event_details", event_id=event.id) + "#winners")


# ---------------------------------------------------------------------------
# Judge panel
# ---------------------------------------------------------------------------
@bp.route("/judge")
@roles_required("faculty")
def judge_index():
    rows = []
    for assignment in f.EventJudge.query.filter_by(user_id=current_user.id).all():
        event = assignment.event
        if event is None:
            continue
        snap = f.competition_snapshot(event)
        mine = f.JudgeScore.query.filter_by(event_id=event.id, judge_id=current_user.id).count()
        expected = sum(len(ids) for rid, ids in snap.participants.items()
                       if next((r for r in snap.rounds if r.id == rid and r.status == "open"), None))
        rows.append(SimpleNamespace(event=event, rounds=snap.rounds, scored=mine, expected=expected))
    rows.sort(key=lambda r: r.event.date, reverse=True)
    return render_template("features/judge_index.html", rows=rows)


def judge_event(event_id):
    event = get_event_or_404(event_id)
    if not f.EventJudge.query.filter_by(event_id=event.id, user_id=current_user.id).first():
        abort(403)
    return event


@bp.route("/judge/events/<int:event_id>")
@roles_required("faculty")
def judge_scoring(event_id):
    event = judge_event(event_id)
    snap = f.competition_snapshot(event)
    rid = request.args.get("round", type=int)
    rnd = next((r for r in snap.rounds if r.id == rid), snap.rounds[0] if snap.rounds else None)
    rows = []
    if rnd is not None:
        mine = {s.entry_id: s for s in f.JudgeScore.query.filter_by(event_id=event.id, round_id=rnd.id,
                                                                    judge_id=current_user.id).all()}
        for entry_id in snap.participants.get(rnd.id, []):
            rows.append(SimpleNamespace(entry=snap.entry_by_id[entry_id], score=mine.get(entry_id),
                                        avg=snap.avg(rnd.id, entry_id)))
    return render_template("features/judge_scoring.html", event=event, snap=snap, rnd=rnd, rows=rows)


@bp.route("/judge/events/<int:event_id>/scores", methods=["POST"])
@roles_required("faculty")
def judge_save_scores(event_id):
    event = judge_event(event_id)
    snap = f.competition_snapshot(event)
    rnd = next((r for r in snap.rounds if r.id == request.form.get("round_id", type=int)), None)
    if rnd is None:
        abort(404)
    if rnd.status != "open":
        flash("This round is closed for scoring.", "warning")
        return redirect(url_for("features.judge_scoring", event_id=event.id, round=rnd.id))
    allowed = snap.participants.get(rnd.id, [])
    updates, errors = [], []
    for entry_id in allowed:
        raw = (request.form.get(f"score_{entry_id}") or "").strip()
        remarks = clean(request.form.get(f"remarks_{entry_id}"), 300)
        if raw == "":
            updates.append((entry_id, None, remarks))
            continue
        value = to_float(raw)
        if value is None or value < 0 or value > (rnd.max_score or 100):
            errors.append(snap.entry_by_id[entry_id].label)
        else:
            updates.append((entry_id, round(value, 2), remarks))
    if errors:
        flash(f"Scores must be between 0 and {rnd.max_score:g}. Fix: " + ", ".join(errors[:5]), "danger")
        return redirect(url_for("features.judge_scoring", event_id=event.id, round=rnd.id))
    saved = 0
    for entry_id, value, remarks in updates:
        existing = f.JudgeScore.query.filter_by(round_id=rnd.id, entry_id=entry_id, judge_id=current_user.id).first()
        if value is None:
            if existing:
                db.session.delete(existing)
            continue
        if existing:
            existing.score, existing.remarks = value, remarks or None
        else:
            db.session.add(f.JudgeScore(event_id=event.id, round_id=rnd.id, entry_id=entry_id, judge_id=current_user.id,
                                        score=value, remarks=remarks or None))
        saved += 1
    db.session.commit()
    flash(f"Scores saved for {saved} entr{'y' if saved == 1 else 'ies'}.", "success")
    return redirect(url_for("features.judge_scoring", event_id=event.id, round=rnd.id))


# ---------------------------------------------------------------------------
# Organizer participant management API (used by organizer/participants.html)
# ---------------------------------------------------------------------------
def participant_event(event_id):
    event = get_event_or_404(event_id)
    if not f.can_manage_event(current_user, event):
        abort(403)
    return event


def participant_payload(reg):
    profile = f.student_profile(reg.user)
    return {
        "id": reg.id, "student_name": reg.user.name, "email": reg.user.email,
        "roll_no": (profile.roll_no if profile and profile.roll_no else reg.user.roll_no) or "—",
        "ticket_code": reg.ticket_code, "status": reg.status, "payment_status": reg.payment_status or "free",
        "attended": bool(reg.attended),
        "registered_at": reg.registered_at.strftime("%d %b %Y %H:%M") if reg.registered_at else "—",
    }


@bp.route("/api/organizer/<int:event_id>/participants")
@roles_required("organizer", "admin")
def api_participants(event_id):
    event = participant_event(event_id)
    regs = (ctx.Registration.query.filter_by(event_id=event.id)
            .order_by(ctx.Registration.registered_at.desc(), ctx.Registration.id.desc()).all())
    stats = {
        "total": len(regs),
        "approved": sum(1 for r in regs if r.status in ("approved", "confirmed")),
        "pending": sum(1 for r in regs if r.status == "pending"),
        "attended": sum(1 for r in regs if r.attended),
        "rejected": sum(1 for r in regs if r.status in CANCELLED_STATES),
        "waitlisted": sum(1 for r in regs if r.status == "waitlisted"),
    }
    query = clean(request.args.get("q"), 100).lower()
    status = clean(request.args.get("status"), 20).lower()
    rows = []
    for reg in regs:
        if status and reg.status != status:
            continue
        data = participant_payload(reg)
        if query and query not in " ".join((data["student_name"], data["email"], data["roll_no"], data["ticket_code"])).lower():
            continue
        rows.append(data)
    return jsonify({"success": True, "stats": stats, "registrations": rows})


CANCELLED_STATES = ("cancelled", "rejected")


def participant_action(event_id, registration_id):
    event = participant_event(event_id)
    reg = ctx.Registration.query.filter_by(id=registration_id, event_id=event.id).first_or_404()
    return event, reg


@bp.route("/api/organizer/<int:event_id>/approve-registration/<int:registration_id>", methods=["POST"])
@roles_required("organizer", "admin")
def api_approve_registration(event_id, registration_id):
    event, reg = participant_action(event_id, registration_id)
    if reg.status not in ("pending", "waitlisted"):
        return jsonify({"success": False, "message": "Only pending or waitlisted registrations can be approved."}), 400
    if reg.status == "waitlisted" and f.seats_left(event) <= 0:
        return jsonify({"success": False, "message": "No free seats. Increase the capacity or cancel a registration first."}), 400
    reg.status = "confirmed"
    f.notify(reg.user_id, "Registration approved", f"Your registration for {event.title} was approved.",
             category="registration", event_id=event.id, action_url=f"/ticket/{reg.id}")
    db.session.commit()
    return jsonify({"success": True, "message": f"{reg.user.name} approved."})


@bp.route("/api/organizer/<int:event_id>/reject-registration/<int:registration_id>", methods=["POST"])
@roles_required("organizer", "admin")
def api_reject_registration(event_id, registration_id):
    event, reg = participant_action(event_id, registration_id)
    if reg.status not in ("pending", "waitlisted"):
        return jsonify({"success": False, "message": "Only pending or waitlisted registrations can be rejected."}), 400
    reason = clean(request.form.get("reason"), 300)
    member = f.TeamMember.query.filter_by(registration_id=reg.id).first()
    if member:
        db.session.delete(member)
    reg.status = "rejected"
    f.notify(reg.user_id, "Registration rejected",
             f"Your registration for {event.title} was rejected." + (f" Reason: {reason}" if reason else ""),
             category="registration", event_id=event.id)
    f.promote_waitlist(event, commit=False)
    db.session.commit()
    return jsonify({"success": True, "message": f"{reg.user.name} rejected."})


@bp.route("/api/organizer/<int:event_id>/cancel-registration/<int:registration_id>", methods=["POST"])
@roles_required("organizer", "admin")
def api_cancel_registration(event_id, registration_id):
    event, reg = participant_action(event_id, registration_id)
    if reg.status in CANCELLED_STATES:
        return jsonify({"success": False, "message": "This registration is already closed."}), 400
    reason = clean(request.form.get("reason"), 300)
    member = f.TeamMember.query.filter_by(registration_id=reg.id).first()
    if member:
        team = member.team
        if team.leader_id == reg.user_id and len(team.members) > 1:
            return jsonify({"success": False, "message": "This student leads a team. Ask them to transfer leadership first."}), 400
        db.session.delete(member)
        if team.leader_id == reg.user_id:
            db.session.flush()
            db.session.delete(team)
    reg.status = "cancelled"
    if reg.payment_status in ("paid", "successful"):
        reg.payment_status = "refund_pending"
    f.notify(reg.user_id, "Registration cancelled",
             f"Your registration for {event.title} was cancelled by the organizer." + (f" Reason: {reason}" if reason else ""),
             category="registration", event_id=event.id)
    db.session.flush()
    f.promote_waitlist(event, commit=False)
    db.session.commit()
    return jsonify({"success": True, "message": f"{reg.user.name}'s registration was cancelled."})


@bp.route("/api/organizer/<int:event_id>/mark-attendance/<int:registration_id>", methods=["POST"])
@roles_required("organizer", "admin")
def api_mark_attendance(event_id, registration_id):
    event, reg = participant_action(event_id, registration_id)
    if reg.status not in ("confirmed", "approved"):
        return jsonify({"success": False, "message": "Only confirmed participants can be checked in."}), 400
    already = bool(reg.attended)
    if not already:
        ctx.save_attendance(reg, "present", method="organizer_manual")
        f.notify(reg.user_id, "Check-in successful", f"You checked in for {event.title}.", category="event", event_id=event.id)
    db.session.commit()
    return jsonify({"success": True, "already_attended": already,
                    "message": f"{reg.user.name} was already checked in." if already else f"{reg.user.name} checked in."})


# ---------------------------------------------------------------------------
# Scheduling conflict check (used live on the reschedule form)
# ---------------------------------------------------------------------------
def _overlaps(start_a, end_a, start_b, end_b):
    a0, a1, b0, b1 = (f.time_minutes(v) for v in (start_a, end_a, start_b, end_b))
    return None not in (a0, a1, b0, b1) and a0 < b1 and b0 < a1


@bp.route("/api/events/<int:event_id>/conflicts")
@roles_required("organizer", "admin")
def api_event_conflicts(event_id):
    event = participant_event(event_id)
    day = f.parse_date(request.args.get("date"))
    start = f._clean_time(request.args.get("start_time"))
    end = f._clean_time(request.args.get("end_time"))
    venue = clean(request.args.get("venue"), 160)
    if not day or not start or not end or not venue:
        return jsonify({"success": False, "message": "Enter a valid date, start/end time and venue."}), 400
    if f.time_minutes(start) >= f.time_minutes(end):
        return jsonify({"success": False, "message": "The end time must be after the start time."}), 400

    others = ctx.Event.query.filter(ctx.Event.id != event.id, ctx.Event.date == day,
                                    ctx.Event.status.in_(("approved", "pending", "waiting"))).all()
    clash = [e for e in others if _overlaps(start, end, e.start_time, e.end_time)]

    def describe(rows):
        return [{"title": e.title, "date": e.date.isoformat(), "start_time": e.start_time, "end_time": e.end_time,
                 "venue": e.venue} for e in rows]

    venue_rows = [e for e in clash if e.venue.strip().lower() == venue.lower()]
    organizer_rows = [e for e in clash if e.organizer_id == event.organizer_id]
    capacity = request.args.get("capacity", type=int)
    registered = f.active_count(event)
    venue_row = ctx.Venue.query.filter(db.func.lower(ctx.Venue.name) == venue.lower()).first()
    capacity_problem = ""
    if capacity is not None and capacity < registered:
        capacity_problem = f"Capacity {capacity} is below the {registered} students already registered."
    elif venue_row is not None and (capacity or event.capacity or 0) > (venue_row.capacity or 0):
        capacity_problem = f"{venue_row.name} holds only {venue_row.capacity} people."
    checks = {
        "venue_conflict": {"passed": not venue_rows, "conflicts": describe(venue_rows),
                           "message": f"{venue} is already booked at that time." if venue_rows else ""},
        "organizer_conflict": {"passed": not organizer_rows, "conflicts": describe(organizer_rows),
                               "message": "The organizer has another event at that time." if organizer_rows else ""},
        "resource_conflict": {"passed": not (venue_rows or organizer_rows), "conflicts": [],
                              "message": "Venue or organizer resources overlap." if (venue_rows or organizer_rows) else ""},
        "capacity": {"passed": not capacity_problem, "message": capacity_problem},
    }
    return jsonify({"success": True, "all_passed": all(c["passed"] for c in checks.values()), "checks": checks})


# ---------------------------------------------------------------------------
# Duplicate IDs, reminders, admin cancellation
# ---------------------------------------------------------------------------
@bp.route("/duplicates")
@roles_required("admin", "organizer")
def duplicates():
    admin = normalize_role(current_user.role) == "admin"
    events = None if admin else f.scoped_events_query(current_user).all()
    accounts, conflicts = f.find_duplicates(events)
    return render_template("features/duplicates.html", accounts=accounts if admin else [], conflicts=conflicts, admin=admin)


@bp.route("/admin/reminders/run", methods=["POST"])
@roles_required("admin")
def run_reminders():
    sent = f.send_due_reminders()
    flash(f"Reminders processed — {sent} notification(s) sent.", "success")
    return redirect(request.referrer if (request.referrer or "").startswith(request.host_url) else url_for("admin_dashboard"))


@bp.route("/admin/events/<int:event_id>/cancel", methods=["POST"])
@roles_required("admin")
def admin_cancel_event(event_id):
    event = get_event_or_404(event_id)
    notified = f.cancel_event(event, request.form.get("reason"), current_user)
    if notified is None:
        flash("Only draft, pending or approved events can be cancelled.", "warning")
    else:
        flash(f"Event cancelled. {notified} people were notified.", "success")
    return redirect(url_for("admin_events"))


# ---------------------------------------------------------------------------
# Community Q&A
# ---------------------------------------------------------------------------
COMMUNITY_ROLES = ("student", "organizer", "faculty", "admin")


@bp.route("/community")
@roles_required(*COMMUNITY_ROLES)
def community():
    q = clean(request.args.get("q"), 100)
    view = request.args.get("view", "all")
    query = f.CommunityQuestion.query
    if q:
        like = f"%{q}%"
        query = query.filter(db.or_(f.CommunityQuestion.title.ilike(like), f.CommunityQuestion.body.ilike(like)))
    if view == "open":
        query = query.filter(f.CommunityQuestion.is_resolved.is_(False))
    elif view == "solved":
        query = query.filter(f.CommunityQuestion.is_resolved.is_(True))
    elif view == "mine":
        query = query.filter(f.CommunityQuestion.user_id == current_user.id)
    page = max(request.args.get("page", 1, type=int), 1)
    questions = query.order_by(f.CommunityQuestion.created_at.desc()).paginate(page=page, per_page=15, error_out=False)
    events = ctx.Event.query.filter(ctx.Event.status.in_(("approved", "completed"))).order_by(ctx.Event.date.desc()).limit(100).all()
    return render_template("features/community.html", questions=questions, q=q, view=view, events=events,
                           prefill=clean(request.args.get("ask"), 200))


@bp.route("/community/ask", methods=["POST"])
@roles_required(*COMMUNITY_ROLES)
@limiter.limit("10 per minute", methods=["POST"])
def community_ask():
    title = clean(request.form.get("title"), 200)
    body = clean(request.form.get("body"), 3000)
    if len(title) < 5:
        flash("Please write a question of at least 5 characters.", "danger")
        return redirect(url_for("features.community"))
    event = db.session.get(ctx.Event, request.form.get("event_id", type=int)) if request.form.get("event_id") else None
    question = f.CommunityQuestion(user_id=current_user.id, title=title, body=body or None,
                                   event_id=event.id if event and event.status in ("approved", "completed") else None)
    db.session.add(question)
    db.session.commit()
    flash("Your question was posted. Anyone in the community can answer it.", "success")
    return redirect(url_for("features.community_detail", question_id=question.id))


@bp.route("/community/<int:question_id>")
@roles_required(*COMMUNITY_ROLES)
def community_detail(question_id):
    question = f.CommunityQuestion.query.get_or_404(question_id)
    return render_template("features/community_detail.html", q=question)


@bp.route("/community/<int:question_id>/answer", methods=["POST"])
@roles_required(*COMMUNITY_ROLES)
@limiter.limit("15 per minute", methods=["POST"])
def community_answer(question_id):
    question = f.CommunityQuestion.query.get_or_404(question_id)
    body = clean(request.form.get("body"), 3000)
    if len(body) < 2:
        flash("Write an answer first.", "danger")
    else:
        db.session.add(f.CommunityAnswer(question_id=question.id, user_id=current_user.id, body=body))
        if question.user_id != current_user.id:
            f.notify(question.user_id, "New answer to your question",
                     f"{current_user.name} answered “{question.title[:80]}”.", category="general",
                     action_url=f"/community/{question.id}")
        db.session.commit()
        flash("Answer posted.", "success")
    return redirect(url_for("features.community_detail", question_id=question.id))


@bp.route("/community/<int:question_id>/accept/<int:answer_id>", methods=["POST"])
@roles_required(*COMMUNITY_ROLES)
def community_accept(question_id, answer_id):
    question = f.CommunityQuestion.query.get_or_404(question_id)
    answer = f.CommunityAnswer.query.filter_by(id=answer_id, question_id=question.id).first_or_404()
    if question.user_id != current_user.id and normalize_role(current_user.role) != "admin":
        abort(403)
    for row in question.answers:
        row.is_accepted = row.id == answer.id and not answer.is_accepted
    question.is_resolved = answer.is_accepted
    if answer.is_accepted and answer.user_id != current_user.id:
        f.notify(answer.user_id, "Your answer was accepted", f"Your answer to “{question.title[:80]}” solved it.",
                 action_url=f"/community/{question.id}")
    db.session.commit()
    flash("Marked as solved." if question.is_resolved else "Answer un-accepted.", "success")
    return redirect(url_for("features.community_detail", question_id=question.id))


@bp.route("/community/<int:question_id>/delete", methods=["POST"])
@roles_required(*COMMUNITY_ROLES)
def community_delete(question_id):
    question = f.CommunityQuestion.query.get_or_404(question_id)
    if question.user_id != current_user.id and normalize_role(current_user.role) != "admin":
        abort(403)
    db.session.delete(question)
    db.session.commit()
    flash("Question deleted.", "success")
    return redirect(url_for("features.community"))


@bp.route("/community/answers/<int:answer_id>/delete", methods=["POST"])
@roles_required(*COMMUNITY_ROLES)
def community_answer_delete(answer_id):
    answer = f.CommunityAnswer.query.get_or_404(answer_id)
    if answer.user_id != current_user.id and normalize_role(current_user.role) != "admin":
        abort(403)
    question_id = answer.question_id
    question = answer.question
    was_accepted = answer.is_accepted
    db.session.delete(answer)
    if was_accepted:
        question.is_resolved = False
    db.session.commit()
    flash("Answer deleted.", "success")
    return redirect(url_for("features.community_detail", question_id=question_id))


# ---------------------------------------------------------------------------
# Chatbot (floating widget + /assistant page)
# ---------------------------------------------------------------------------
@bp.route("/assistant")
@roles_required(*COMMUNITY_ROLES)
def assistant():
    return render_template("assistant.html")


@bp.route("/api/assistant/status")
@login_required
def assistant_status():
    return jsonify({"success": True, "status_message": "Campus assistant online — ask about events, deadlines, teams and more."})


@bp.route("/api/assistant/chat", methods=["POST"])
@login_required
@limiter.limit("40 per minute", methods=["POST"])
def assistant_chat():
    payload = request.get_json(silent=True) or {}
    message = payload.get("message")
    if not isinstance(message, str) or not message.strip():
        return jsonify({"success": False, "error": "Please type a question."}), 400
    result = chatbot.reply(current_user, message)
    return jsonify({"success": True, "response": result["reply"], "reply": result["reply"], "links": result["links"],
                    "suggestions": result["suggestions"], "ask_community": result["ask_community"]})


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------
def init_app(app, **objects):
    """Attach the feature set to the Flask app. ``objects`` are the app's models/helpers."""
    ctx.__dict__.update(objects)
    ctx.logger = app.logger
    app.register_blueprint(bp)

    def is_wishlisted(event_id):
        if not current_user.is_authenticated:
            return False
        if not hasattr(g, "_wishlist_ids"):
            g._wishlist_ids = f.wishlist_ids(current_user)
        return event_id in g._wishlist_ids

    def winners_for(event):
        return f.published_winners(event)

    app.jinja_env.globals.update(
        is_wishlisted=is_wishlisted, deadline_iso=f.event_deadline_iso, deadline_label=f.deadline_label,
        winners_for=winners_for, congratulated_ids=lambda event: f.congratulated_user_ids(event, current_user) if current_user.is_authenticated else set(), winner_user_ids=lambda w: {r.user_id for r in f._winner_member_regs(w)}, format_duration=f.format_duration, team_limits=f.team_limits,
        waitlist_position=f.waitlist_position, user_dept=f.user_dept, semester_parity=f.semester_parity,
        chat_suggestions=lambda role: chatbot.SUGGESTIONS.get(role, chatbot.SUGGESTIONS["student"]),
    )

    @app.template_filter("initials")
    def initials(value):
        """Alphanumeric-only initials, safe to drop into inline JS/HTML snippets."""
        return "".join(ch for ch in str(value or "")[:2] if ch.isalnum()).upper()

    @app.cli.command("send-reminders")
    def send_reminders_command():
        """Send due event / registration-deadline reminders and promote waitlisted students (cron-friendly)."""
        print(f"{f.send_due_reminders()} reminder notification(s) sent.")

    @app.before_request
    def _scheduled_reminders():
        if app.config.get("TESTING") or request.endpoint in (None, "static"):
            return
        f.maybe_run_reminders()
