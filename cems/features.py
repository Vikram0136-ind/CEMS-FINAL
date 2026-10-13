"""Extended event-management modules for CEMS.

This module holds the data models and service functions behind the departmental
dashboards, date-range reports, wishlist, reminders, waitlist auto-promotion, team
registration, entry/exit tracking, rounds, judging, winners, achievement points,
leaderboards and the community Q&A / chatbot.

It deliberately does not import ``app``: the application hands over its own models and
helpers through :func:`init_features`, which avoids circular imports and keeps the
original schema untouched (new tables only; new columns are added by the app's
lightweight ``_add_missing_columns`` sync).
"""

import os
import re
import secrets
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy.exc import IntegrityError

from .extensions import db

ACTIVE = ("confirmed", "approved", "pending")
CANCELLED = ("cancelled", "rejected")

# Filled in by init_features() with the application's models and helpers.
ctx = SimpleNamespace()


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class WishlistItem(db.Model):
    __tablename__ = "wishlist_item"
    __table_args__ = (db.UniqueConstraint("user_id", "event_id", name="uq_wishlist_user_event"),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    event_id = db.Column(db.Integer, db.ForeignKey("event.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=utcnow)
    event = db.relationship("Event", backref=db.backref("wishlist_items", cascade="all, delete-orphan"))
    user = db.relationship("User")


class ReminderLog(db.Model):
    """One row per (user, event, reminder kind) so a reminder is only ever sent once."""
    __tablename__ = "reminder_log"
    __table_args__ = (db.UniqueConstraint("user_id", "event_id", "kind", name="uq_reminder_user_event_kind"),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey("event.id"), nullable=False, index=True)
    kind = db.Column(db.String(30), nullable=False)
    sent_at = db.Column(db.DateTime, default=utcnow)


class Team(db.Model):
    __tablename__ = "team"
    __table_args__ = (db.UniqueConstraint("event_id", "name", name="uq_team_event_name"),)

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("event.id"), nullable=False, index=True)
    name = db.Column(db.String(80), nullable=False)
    leader_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    invite_code = db.Column(db.String(16), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow)
    event = db.relationship("Event", backref=db.backref("teams", cascade="all, delete-orphan"))
    leader = db.relationship("User", foreign_keys=[leader_id])
    members = db.relationship("TeamMember", backref="team", cascade="all, delete-orphan",
                              order_by="TeamMember.id")


class TeamMember(db.Model):
    __tablename__ = "team_member"
    __table_args__ = (db.UniqueConstraint("team_id", "user_id", name="uq_team_member"),)

    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey("team.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    registration_id = db.Column(db.Integer, db.ForeignKey("registration.id"), nullable=False, unique=True)
    joined_at = db.Column(db.DateTime, default=utcnow)
    user = db.relationship("User")
    registration = db.relationship("Registration")


class AttendanceLog(db.Model):
    """Append-only trail of every attendance mark and every entry / exit."""
    __tablename__ = "attendance_log"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("event.id"), nullable=False, index=True)
    registration_id = db.Column(db.Integer, db.ForeignKey("registration.id"), nullable=False, index=True)
    action = db.Column(db.String(12), nullable=False)  # present / absent / late / in / out
    method = db.Column(db.String(30))
    actor_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    at = db.Column(db.DateTime, default=utcnow, index=True)
    registration = db.relationship("Registration")
    actor = db.relationship("User")
    event = db.relationship("Event")


class EventRound(db.Model):
    __tablename__ = "event_round"
    __table_args__ = (db.UniqueConstraint("event_id", "number", name="uq_round_event_number"),)

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("event.id"), nullable=False, index=True)
    number = db.Column(db.Integer, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    max_score = db.Column(db.Float, default=100)
    advance_count = db.Column(db.Integer)  # how many entries qualify for the next round
    status = db.Column(db.String(20), default="open")  # open / completed
    created_at = db.Column(db.DateTime, default=utcnow)
    event = db.relationship("Event", backref=db.backref("rounds", cascade="all, delete-orphan",
                                                       order_by="EventRound.number"))


class EventJudge(db.Model):
    __tablename__ = "event_judge"
    __table_args__ = (db.UniqueConstraint("event_id", "user_id", name="uq_event_judge"),)

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("event.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    assigned_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    assigned_at = db.Column(db.DateTime, default=utcnow)
    event = db.relationship("Event", backref=db.backref("judge_panel", cascade="all, delete-orphan"))
    user = db.relationship("User", foreign_keys=[user_id])


class JudgeScore(db.Model):
    __tablename__ = "judge_score"
    __table_args__ = (db.UniqueConstraint("round_id", "entry_id", "judge_id", name="uq_judge_score"),)

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("event.id"), nullable=False, index=True)
    round_id = db.Column(db.Integer, db.ForeignKey("event_round.id"), nullable=False, index=True)
    entry_id = db.Column(db.Integer, db.ForeignKey("registration.id"), nullable=False)  # individual or team-leader registration
    judge_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    score = db.Column(db.Float, nullable=False)
    remarks = db.Column(db.String(300))
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)
    round = db.relationship("EventRound", backref=db.backref("scores", cascade="all, delete-orphan"))
    judge = db.relationship("User")


class EventWinner(db.Model):
    __tablename__ = "event_winner"
    __table_args__ = (db.UniqueConstraint("event_id", "registration_id", "category", name="uq_event_winner"),)

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("event.id"), nullable=False, index=True)
    registration_id = db.Column(db.Integer, db.ForeignKey("registration.id"), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey("team.id"))
    category = db.Column(db.String(60), nullable=False)
    rank = db.Column(db.Integer, default=0)
    score = db.Column(db.Float)
    auto = db.Column(db.Boolean, default=False)
    published = db.Column(db.Boolean, default=False)
    declared_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    declared_at = db.Column(db.DateTime, default=utcnow)
    event = db.relationship("Event", backref=db.backref("winners", cascade="all, delete-orphan"))
    registration = db.relationship("Registration")
    team = db.relationship("Team")


class Congratulation(db.Model):
    """A wish sent by one user to a published winner (one per sender, recipient and event)."""
    __tablename__ = "congratulation"
    __table_args__ = (db.UniqueConstraint("event_id", "from_user_id", "to_user_id", name="uq_congratulation"),)

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("event.id"), nullable=False, index=True)
    winner_id = db.Column(db.Integer, db.ForeignKey("event_winner.id"))
    from_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    to_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    message = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=utcnow)


class AchievementPoint(db.Model):
    __tablename__ = "achievement_point"
    __table_args__ = (db.UniqueConstraint("user_id", "event_id", "kind", name="uq_achievement"),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    event_id = db.Column(db.Integer, db.ForeignKey("event.id"), nullable=False, index=True)
    kind = db.Column(db.String(80), nullable=False)
    points = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=utcnow)
    user = db.relationship("User")
    event = db.relationship("Event")


class CommunityQuestion(db.Model):
    __tablename__ = "community_question"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text)
    event_id = db.Column(db.Integer, db.ForeignKey("event.id"))
    is_resolved = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=utcnow, index=True)
    author = db.relationship("User")
    event = db.relationship("Event")
    answers = db.relationship("CommunityAnswer", backref="question", cascade="all, delete-orphan",
                              order_by="CommunityAnswer.created_at")


class CommunityAnswer(db.Model):
    __tablename__ = "community_answer"

    id = db.Column(db.Integer, primary_key=True)
    question_id = db.Column(db.Integer, db.ForeignKey("community_question.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    body = db.Column(db.Text, nullable=False)
    is_accepted = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=utcnow)
    author = db.relationship("User")


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------
def normalize_role(role):
    role = (role or "").strip().lower()
    return "faculty" if role == "teacher" else role


def pct(part, whole):
    return round(part * 100 / whole, 1) if whole else 0.0


def parse_date(value):
    try:
        return datetime.strptime((value or "").strip(), "%Y-%m-%d").date()
    except (ValueError, AttributeError):
        return None


def _clean_time(value):
    """Normalise user-entered times such as '14:00' or '2 PM' to '2:00 PM' (None if invalid)."""
    for fmt in ("%I:%M %p", "%I:%M%p", "%I %p", "%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime((value or "").strip(), fmt).strftime("%I:%M %p").lstrip("0")
        except ValueError:
            continue
    return None


def time_minutes(value):
    """'10:00 AM' / '14:30' -> minutes since midnight (None if unparsable)."""
    for fmt in ("%I:%M %p", "%I:%M%p", "%I %p", "%H:%M", "%H:%M:%S"):
        try:
            parsed = datetime.strptime((value or "").strip(), fmt)
            return parsed.hour * 60 + parsed.minute
        except ValueError:
            continue
    return None


def norm_dept(value):
    return " ".join((value or "").split()) or "Unassigned"


def norm_id(value):
    return re.sub(r"[\s\-_/.]", "", value or "").casefold()


def semester_no(value):
    match = re.search(r"\d+", str(value or ""))
    return int(match.group()) if match else None


def semester_parity(value):
    number = semester_no(value)
    return None if number is None else ("odd" if number % 2 else "even")


def student_profile(user):
    return getattr(user, "student_account_profile", None) if user else None


def user_dept(user):
    if user is None:
        return "Unassigned"
    profile = student_profile(user)
    return norm_dept((profile.department if profile and profile.department else None) or user.department)


def event_deadline_iso(event):
    """End of the registration-deadline day (UTC) for the JS countdown."""
    if not event or not event.registration_deadline:
        return ""
    return event.registration_deadline.strftime("%Y-%m-%dT23:59:59Z")


def deadline_label(event):
    """Short server-side countdown text ('3 days left'), used as a no-JS fallback."""
    if not event or not event.registration_deadline:
        return ""
    days = (event.registration_deadline - utcnow().date()).days
    if days < 0:
        return "Registration closed"
    if days == 0:
        return "Closes today"
    return f"{days} day{'s' if days != 1 else ''} left to register"


def active_count(event):
    return ctx.Registration.query.filter(ctx.Registration.event_id == event.id,
                                         ctx.Registration.status.in_(ACTIVE)).count()


def seats_left(event):
    return max((event.capacity or 0) - active_count(event), 0)


def notify(user_id, title, message, category="event", event_id=None, priority="normal", action_url=None):
    """Queue an in-app notification (the caller commits)."""
    db.session.add(ctx.Notification(user_id=user_id, title=title[:180], message=message, category=category,
                                    event_id=event_id, priority=priority, action_url=action_url))


def email_users(users, subject, body):
    """Best-effort e-mail; silently skipped unless SMTP is configured."""
    if not os.getenv("MAIL_SERVER"):
        return
    for user in users:
        if user and user.email:
            ctx.send_email(user.email, subject, body)


def new_ticket_code():
    while True:
        code = "AGC-" + secrets.token_hex(4).upper()
        if not ctx.Registration.query.filter_by(ticket_code=code).first():
            return code


def create_registration(event, user, status="confirmed", payment_status=None):
    if payment_status is None:
        payment_status = "pending" if (event.fee or 0) > 0 else "free"
    registration = ctx.Registration(ticket_code=new_ticket_code(), user_id=user.id, event_id=event.id,
                                    status=status, payment_status=payment_status)
    db.session.add(registration)
    db.session.flush()
    return registration


def profile_map():
    return {p.user_id: p for p in ctx.StudentAccountProfile.query.all()}


# ---------------------------------------------------------------------------
# Participant filters (department / batch / semester / odd-even)
# ---------------------------------------------------------------------------
class ParticipantFilter:
    def __init__(self, dept="", batch="", semester="", semester_type=""):
        self.dept = (dept or "").strip()
        self.batch = (batch or "").strip()
        self.semester = (semester or "").strip()
        self.semester_type = semester_type if semester_type in ("odd", "even") else ""

    @classmethod
    def from_args(cls, args):
        return cls(args.get("dept", ""), args.get("batch", ""), args.get("semester", ""), args.get("semester_type", ""))

    @property
    def active(self):
        return bool(self.dept or self.batch or self.semester or self.semester_type)

    def matches(self, user, profiles=None):
        if user is None:
            return False
        profile = (profiles or {}).get(user.id) if profiles is not None else student_profile(user)
        if self.dept and user_dept(user).casefold() != norm_dept(self.dept).casefold():
            return False
        if self.batch and (not profile or (profile.batch or "").strip().casefold() != self.batch.casefold()):
            return False
        semester = profile.semester if profile else None
        if self.semester and semester_no(semester) != semester_no(self.semester):
            return False
        if self.semester_type and semester_parity(semester) != self.semester_type:
            return False
        return True

    def as_params(self):
        return {k: v for k, v in (("dept", self.dept), ("batch", self.batch), ("semester", self.semester),
                                  ("semester_type", self.semester_type)) if v}


def filter_options():
    """Distinct values for the department / batch / semester dropdowns."""
    profiles = ctx.StudentAccountProfile.query.all()
    depts = {norm_dept(p.department or (p.user.department if p.user else "")) for p in profiles}
    depts |= {norm_dept(u.department) for u in ctx.User.query.filter(ctx.User.department.isnot(None)).all() if u.department}
    depts.discard("Unassigned")
    batches = sorted({(p.batch or "").strip() for p in profiles if (p.batch or "").strip()})
    semesters = sorted({semester_no(p.semester) for p in profiles if semester_no(p.semester) is not None})
    return SimpleNamespace(depts=sorted(depts, key=str.casefold), batches=batches, semesters=semesters)


def reg_stats(registrations):
    active = [r for r in registrations if r.status in ACTIVE]
    attended = sum(1 for r in active if r.attended)
    return SimpleNamespace(
        registered=len(active), attended=attended,
        absent=len(active) - attended,
        waitlisted=sum(1 for r in registrations if r.status == "waitlisted"),
        rate=pct(attended, len(active)), ratio=f"{len(active)} : {attended}",
    )


# ---------------------------------------------------------------------------
# Scoping of events by role
# ---------------------------------------------------------------------------
def assigned_event_ids(user):
    return [row.event_id for row in ctx.EventFaculty.query.filter_by(faculty_id=user.id).all()]


def scoped_events_query(user):
    """Events the user may analyse: admin all, organizer own, faculty assigned."""
    role = normalize_role(user.role)
    query = ctx.Event.query
    if role == "admin":
        return query
    if role == "organizer":
        return query.filter(ctx.Event.organizer_id == user.id)
    if role == "faculty":
        ids = assigned_event_ids(user)
        return query.filter(ctx.Event.id.in_(ids)) if ids else query.filter(db.false())
    return query.filter(db.false())


def can_manage_event(user, event):
    role = normalize_role(user.role)
    return role == "admin" or (role == "organizer" and event.organizer_id == user.id)


def can_operate_event(user, event):
    """Manage rights, or an assigned faculty coordinator."""
    if can_manage_event(user, event):
        return True
    return normalize_role(user.role) == "faculty" and bool(
        ctx.EventFaculty.query.filter_by(faculty_id=user.id, event_id=event.id).first())


# ---------------------------------------------------------------------------
# Date-to-date reports
# ---------------------------------------------------------------------------
REPORT_STATUSES = ("approved", "completed", "cancelled")


def build_date_report(user, args):
    today = utcnow().date()
    date_to = parse_date(args.get("to")) or today
    date_from = parse_date(args.get("from")) or (date_to - timedelta(days=30))
    if date_from > date_to:
        date_from, date_to = date_to, date_from
    from_min = time_minutes(args.get("from_time"))
    to_min = time_minutes(args.get("to_time"))
    category = (args.get("category") or "").strip()
    flt = ParticipantFilter.from_args(args)

    query = scoped_events_query(user).filter(ctx.Event.date >= date_from, ctx.Event.date <= date_to,
                                             ctx.Event.status.in_(REPORT_STATUSES))
    if category:
        query = query.filter(ctx.Event.category == category)
    events = query.order_by(ctx.Event.date.asc(), ctx.Event.id.asc()).all()
    if from_min is not None or to_min is not None:
        kept = []
        for event in events:
            minutes = time_minutes(event.start_time)
            if minutes is None:
                continue
            if from_min is not None and minutes < from_min:
                continue
            if to_min is not None and minutes > to_min:
                continue
            kept.append(event)
        events = kept

    profiles = profile_map()
    rows, participants = [], []
    by_dept, by_batch, by_sem = (defaultdict(lambda: [0, 0]) for _ in range(3))
    published = defaultdict(int)
    if events:
        for winner in EventWinner.query.filter(EventWinner.event_id.in_([e.id for e in events]),
                                               EventWinner.published.is_(True)).all():
            published[winner.event_id] += 1
    for event in events:
        regs = [r for r in event.registrations if flt.matches(r.user, profiles)] if flt.active else list(event.registrations)
        stats = reg_stats(regs)
        rows.append(SimpleNamespace(event=event, stats=stats, winners=published.get(event.id, 0)))
        for reg in regs:
            if reg.status not in ACTIVE:
                continue
            profile = profiles.get(reg.user_id)
            semester = profile.semester if profile else None
            participants.append(SimpleNamespace(reg=reg, event=event, profile=profile, dept=user_dept(reg.user)))
            for table, key in ((by_dept, user_dept(reg.user)),
                               (by_batch, (profile.batch if profile and profile.batch else "—")),
                               (by_sem, (f"Semester {semester_no(semester)} ({semester_parity(semester)})"
                                         if semester_no(semester) is not None else "—"))):
                table[key][0] += 1
                table[key][1] += 1 if reg.attended else 0

    def breakdown(table):
        return sorted((SimpleNamespace(label=k, registered=v[0], attended=v[1], rate=pct(v[1], v[0]))
                       for k, v in table.items()), key=lambda r: (-r.registered, r.label))

    live = [row for row in rows if row.event.status != "cancelled"]
    total = reg_stats([r for row in live for r in row.event.registrations
                       if not flt.active or flt.matches(r.user, profiles)])
    return SimpleNamespace(
        date_from=date_from, date_to=date_to, from_time=args.get("from_time", ""), to_time=args.get("to_time", ""),
        category=category, flt=flt, rows=rows, participants=participants, totals=total,
        events_count=len(live), cancelled=len(rows) - len(live),
        by_dept=breakdown(by_dept), by_batch=breakdown(by_batch), by_semester=breakdown(by_sem),
        categories=sorted({e[0] for e in db.session.query(ctx.Event.category).distinct().all() if e[0]}),
        options=filter_options(),
    )


# ---------------------------------------------------------------------------
# Department analytics, leaderboard
# ---------------------------------------------------------------------------
def points_by_user():
    totals = defaultdict(int)
    for row in AchievementPoint.query.all():
        totals[row.user_id] += row.points
    return totals


def build_department_board(args=None, include_events=True):
    """Aggregate registrations, attendance, winners and points per department."""
    args = args or {}
    date_from, date_to = parse_date(args.get("from")), parse_date(args.get("to"))
    flt = ParticipantFilter.from_args(args)
    profiles = profile_map()
    students = ctx.User.query.filter_by(role="student").all()
    points = points_by_user()
    depts = {}

    def row(name):
        return depts.setdefault(name, SimpleNamespace(
            name=name, students=0, registrations=0, attended=0, events=set(), winners=0, points=0,
            event_regs=defaultdict(int), event_winners=defaultdict(int), batches=set()))

    for student in students:
        if flt.active and not flt.matches(student, profiles):
            continue
        dept = row(user_dept(student))
        dept.students += 1
        dept.points += points.get(student.id, 0)
        profile = profiles.get(student.id)
        if profile and profile.batch:
            dept.batches.add(profile.batch)

    query = ctx.Registration.query.filter(ctx.Registration.status.in_(ACTIVE))
    regs = query.all()
    events = {e.id: e for e in ctx.Event.query.filter(ctx.Event.status.in_(("approved", "completed"))).all()}
    for reg in regs:
        event = events.get(reg.event_id)
        if event is None:
            continue
        if date_from and event.date < date_from or date_to and event.date > date_to:
            continue
        if flt.active and not flt.matches(reg.user, profiles):
            continue
        dept = row(user_dept(reg.user))
        dept.registrations += 1
        dept.attended += 1 if reg.attended else 0
        dept.events.add(event.id)
        dept.event_regs[event.id] += 1

    team_of = {tm.registration_id: tm.team_id for tm in TeamMember.query.all()}
    regs_by_id = {r.id: r for r in regs}
    for winner in EventWinner.query.filter_by(published=True).all():
        members = _winner_member_regs(winner, regs_by_id, team_of)
        counted = set()
        for reg in members:
            name = user_dept(reg.user)
            if (winner.id, name) in counted or reg.event_id not in events:
                continue
            counted.add((winner.id, name))
            if flt.active and not flt.matches(reg.user, profiles):
                continue
            row(name).winners += 1
            row(name).event_winners[reg.event_id] += 1

    result = sorted(depts.values(), key=lambda d: (-d.points, -d.registrations, d.name))
    for dept in result:
        dept.rate = pct(dept.attended, dept.registrations)
        dept.events_count = len(dept.events)
        top = max(dept.event_regs.items(), key=lambda kv: kv[1], default=None)
        dept.top_event = events[top[0]].title if top and top[0] in events else "—"
    return SimpleNamespace(rows=result, events=events, flt=flt, date_from=date_from, date_to=date_to,
                           options=filter_options() if include_events else None)


def _winner_member_regs(winner, regs_by_id=None, team_of=None):
    """Registrations (all team members for a team win) behind a winner row."""
    if winner.team_id:
        ids = [m.registration_id for m in TeamMember.query.filter_by(team_id=winner.team_id).all()]
        regs = [db.session.get(ctx.Registration, i) for i in ids] if regs_by_id is None else \
               [regs_by_id.get(i) or db.session.get(ctx.Registration, i) for i in ids]
        return [r for r in regs if r and r.status in ACTIVE]
    reg = (regs_by_id or {}).get(winner.registration_id) or db.session.get(ctx.Registration, winner.registration_id)
    return [reg] if reg and reg.status in ACTIVE else []


def build_leaderboard():
    board = build_department_board(include_events=False)
    regs = ctx.Registration.query.filter(ctx.Registration.status.in_(ACTIVE)).all()
    events = board.events
    per_event = defaultdict(list)
    for reg in regs:
        if reg.event_id in events:
            per_event[reg.event_id].append(reg)

    winner_depts = defaultdict(set)
    regs_by_id = {r.id: r for r in regs}
    team_of = {tm.registration_id: tm.team_id for tm in TeamMember.query.all()}
    for winner in EventWinner.query.filter_by(published=True).all():
        for reg in _winner_member_regs(winner, regs_by_id, team_of):
            winner_depts[winner.event_id].add(user_dept(reg.user))

    performance = []
    for event_id, event_regs in per_event.items():
        counts = defaultdict(int)
        for reg in event_regs:
            counts[user_dept(reg.user)] += 1
        stats = reg_stats(event_regs)
        top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        performance.append(SimpleNamespace(
            event=events[event_id], stats=stats, top_dept=top[0][0] if top else "—",
            dept_counts=top[:5], winner_depts=sorted(winner_depts.get(event_id, []))))
    most_registered = sorted(performance, key=lambda p: (-p.stats.registered, p.event.title))[:10]
    best_attendance = sorted((p for p in performance if p.stats.registered >= 3),
                             key=lambda p: (-p.stats.rate, -p.stats.registered))[:10]

    points = points_by_user()
    profiles = profile_map()
    top_students = []
    for user_id, total in sorted(points.items(), key=lambda kv: -kv[1])[:10]:
        user = db_get(ctx.User, user_id)
        if user and normalize_role(user.role) == "student":
            top_students.append(SimpleNamespace(user=user, points=total, dept=user_dept(user),
                                                profile=profiles.get(user.id)))
    return SimpleNamespace(departments=board.rows, most_registered=most_registered,
                           best_attendance=best_attendance, performance=sorted(
                               performance, key=lambda p: p.event.date, reverse=True)[:15],
                           top_students=top_students)


def db_get(model, pk):
    return db.session.get(model, pk)


# ---------------------------------------------------------------------------
# Wishlist
# ---------------------------------------------------------------------------
def wishlist_ids(user):
    if not user or not user.is_authenticated:
        return set()
    return {row.event_id for row in WishlistItem.query.filter_by(user_id=user.id).all()}


def toggle_wishlist(user, event):
    row = WishlistItem.query.filter_by(user_id=user.id, event_id=event.id).first()
    if row:
        db.session.delete(row)
        db.session.commit()
        return False
    db.session.add(WishlistItem(user_id=user.id, event_id=event.id))
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
    return True


# ---------------------------------------------------------------------------
# Duplicate-ID detection
# ---------------------------------------------------------------------------
def identity_keys(user):
    profile = student_profile(user)
    keys = {norm_id(user.roll_no)}
    if profile:
        keys |= {norm_id(profile.student_id), norm_id(profile.roll_no)}
    keys.discard("")
    return keys


def duplicate_conflict(event, user):
    """Another account already holding a seat in this event under the same student/roll ID."""
    keys = identity_keys(user)
    if not keys:
        return None
    rows = (db.session.query(ctx.Registration, ctx.User)
            .join(ctx.User, ctx.User.id == ctx.Registration.user_id)
            .filter(ctx.Registration.event_id == event.id, ctx.Registration.user_id != user.id,
                    ctx.Registration.status.in_(ACTIVE + ("waitlisted",))).all())
    for registration, other in rows:
        if keys & identity_keys(other):
            return registration
    return None


def duplicate_roll_account(user_id, student_id="", roll_no=""):
    """Another student account that already uses this student ID / roll number."""
    wanted = {norm_id(student_id), norm_id(roll_no)} - {""}
    if not wanted:
        return None
    for profile in ctx.StudentAccountProfile.query.filter(ctx.StudentAccountProfile.user_id != (user_id or 0)).all():
        if wanted & ({norm_id(profile.student_id), norm_id(profile.roll_no)} - {""}):
            return profile
    return None


def find_duplicates(events=None):
    """Return (account groups, event-level conflicts) for the duplicate-ID report."""
    groups = defaultdict(list)
    for profile in ctx.StudentAccountProfile.query.all():
        for kind, value in (("Student ID", profile.student_id), ("Roll number", profile.roll_no)):
            key = norm_id(value)
            if key:
                groups[(kind, key)].append(profile)
    account_groups = []
    for (kind, key), profiles in groups.items():
        users = {p.user_id: p for p in profiles}
        if len(users) > 1:
            account_groups.append(SimpleNamespace(kind=kind, value=profiles[0].student_id if kind == "Student ID"
                                                  else profiles[0].roll_no, profiles=list(users.values())))
    event_conflicts = []
    events = events if events is not None else ctx.Event.query.filter(
        ctx.Event.status.in_(("approved", "completed"))).all()
    for event in events:
        seen = {}
        for reg in event.registrations:
            if reg.status not in ACTIVE + ("waitlisted",):
                continue
            for key in identity_keys(reg.user):
                seen.setdefault(key, []).append(reg)
        flagged = {}
        for key, regs in seen.items():
            distinct = {r.user_id: r for r in regs}
            if len(distinct) > 1:
                flagged[key] = list(distinct.values())
        users_seen = set()
        for key, regs in flagged.items():
            ids = tuple(sorted(r.user_id for r in regs))
            if ids in users_seen:
                continue
            users_seen.add(ids)
            event_conflicts.append(SimpleNamespace(event=event, key=key, registrations=regs))
    return sorted(account_groups, key=lambda g: g.value or ""), event_conflicts


# ---------------------------------------------------------------------------
# Waitlist
# ---------------------------------------------------------------------------
def waitlist_queue(event):
    return (ctx.Registration.query.filter_by(event_id=event.id, status="waitlisted")
            .order_by(ctx.Registration.registered_at.asc(), ctx.Registration.id.asc()).all())


def waitlist_position(registration):
    queue = waitlist_queue(db.session.get(ctx.Event, registration.event_id))
    for index, row in enumerate(queue, 1):
        if row.id == registration.id:
            return index
    return None


def join_waitlist(event, user):
    registration = create_registration(event, user, status="waitlisted",
                                       payment_status="pending" if (event.fee or 0) > 0 else "free")
    notify(user.id, "Added to waitlist",
           f"{event.title} is full. You are on the waitlist and will be promoted automatically if a seat opens.",
           event_id=event.id)
    return registration


def promote_waitlist(event, commit=True):
    """Move waitlisted students into free seats, first come first served."""
    promoted = []
    today = utcnow().date()
    if event.status != "approved" or (event.date and event.date < today):
        return promoted
    for _ in range(1000):  # hard stop; capacity is small
        if seats_left(event) <= 0:
            break
        queue = [r for r in waitlist_queue(event) if r.user and r.user.is_active_account]
        if not queue:
            break
        registration = queue[0]
        registration.status = "confirmed"
        registration.payment_status = "pending" if (event.fee or 0) > 0 else "free"
        db.session.flush()
        promoted.append(registration)
        extra = " Complete the payment to secure your seat." if (event.fee or 0) > 0 else ""
        notify(registration.user_id, "Promoted from the waitlist",
               f"A seat opened up — you are now confirmed for {event.title}.{extra}", event_id=event.id,
               priority="high", action_url=f"/ticket/{registration.id}")
        notify(event.organizer_id, "Waitlist promotion",
               f"{registration.user.name} was automatically promoted from the waitlist for {event.title}.",
               event_id=event.id)
    if commit and promoted:
        db.session.commit()
    return promoted


def cancel_registration(registration, actor, reason="Cancelled by participant"):
    """Cancel one registration (handles team membership, refunds and waitlist promotion).

    Returns (ok, message)."""
    event = registration.event
    if registration.status in CANCELLED:
        return False, "This registration is already cancelled."
    member = TeamMember.query.filter_by(registration_id=registration.id).first()
    if member:
        team = member.team
        others = [m for m in team.members if m.id != member.id]
        if team.leader_id == registration.user_id and others:
            return False, "You lead this team. Transfer leadership or disband the team first."
        db.session.delete(member)
        if team.leader_id == registration.user_id and not others:
            db.session.flush()
            db.session.delete(team)
    was_waitlisted = registration.status == "waitlisted"
    registration.status = "cancelled"
    if registration.payment_status in ("paid", "successful"):
        registration.payment_status = "refund_pending"
    db.session.flush()
    if not was_waitlisted:
        notify(event.organizer_id, "Registration cancelled",
               f"{registration.user.name} cancelled their registration for {event.title}.", event_id=event.id)
    promote_waitlist(event, commit=False)
    db.session.commit()
    return True, "Registration cancelled."


# ---------------------------------------------------------------------------
# Event cancellation / reschedule notifications
# ---------------------------------------------------------------------------
CANCELLABLE = ("draft", "pending", "waiting", "approved")


def cancel_event(event, reason, actor):
    """Cancel an event and notify everyone affected. Returns the number of people notified."""
    if event.status not in CANCELLABLE:
        return None
    previous = event.status
    reason = (reason or "").strip()[:500] or "No reason provided"
    event.status = "cancelled"
    event.change_status = "cancelled"
    event.cancellation_reason = reason
    ctx.log_event_activity(event, "event_cancelled", f"Cancelled by {actor.name}: {reason}",
                           previous=previous, status="cancelled", reason=reason, actor=actor)
    recipients = {}
    for registration in event.registrations:
        if registration.status in ACTIVE + ("waitlisted",):
            recipients[registration.user_id] = registration.user
            registration.status = "cancelled"
            if registration.payment_status in ("paid", "successful"):
                registration.payment_status = "refund_pending"
    for item in WishlistItem.query.filter_by(event_id=event.id).all():
        recipients.setdefault(item.user_id, item.user)
    for assignment in event.faculty_assignments:
        recipients.setdefault(assignment.faculty_id, assignment.faculty)
    recipients.setdefault(event.organizer_id, event.organizer)
    for admin in ctx.User.query.filter_by(role="admin").all():
        recipients.setdefault(admin.id, admin)
    recipients.pop(actor.id, None)
    message = (f"{event.title} scheduled for {event.date.strftime('%d %b %Y') if event.date else 'TBA'} has been "
               f"cancelled. Reason: {reason}")
    for user_id in recipients:
        notify(user_id, "Event cancelled", message, category="event", event_id=event.id, priority="high")
    email_users(recipients.values(), f"Event cancelled: {event.title}", message)
    db.session.commit()
    return len(recipients)


def notify_event_rescheduled(event, actor, old_summary):
    recipients = {r.user_id: r.user for r in event.registrations if r.status in ACTIVE + ("waitlisted",)}
    for item in WishlistItem.query.filter_by(event_id=event.id).all():
        recipients.setdefault(item.user_id, item.user)
    for assignment in event.faculty_assignments:
        recipients.setdefault(assignment.faculty_id, assignment.faculty)
    recipients.pop(actor.id, None)
    message = (f"{event.title} has been rescheduled. Previously: {old_summary}. "
               f"Now: {event.date.strftime('%d %b %Y') if event.date else 'TBA'}, "
               f"{event.start_time} – {event.end_time} at {event.venue}.")
    for user_id in recipients:
        notify(user_id, "Event rescheduled", message, event_id=event.id, priority="high")
    email_users(recipients.values(), f"Event rescheduled: {event.title}", message)
    return len(recipients)


# ---------------------------------------------------------------------------
# Reminders
# ---------------------------------------------------------------------------
_last_reminder_run = None


def send_due_reminders():
    """Send event-day, 24-hour and registration-deadline reminders exactly once each."""
    today = utcnow().date()
    tomorrow = today + timedelta(days=1)
    sent = 0
    events = ctx.Event.query.filter(ctx.Event.status == "approved", ctx.Event.date.in_([today, tomorrow])).all()
    for event in events:
        kind = "event_today" if event.date == today else "event_24h"
        done = {r.user_id for r in ReminderLog.query.filter_by(event_id=event.id, kind=kind).all()}
        for registration in event.registrations:
            if registration.status not in ("confirmed", "approved") or registration.user_id in done:
                continue
            done.add(registration.user_id)
            db.session.add(ReminderLog(user_id=registration.user_id, event_id=event.id, kind=kind))
            when = "today" if kind == "event_today" else "tomorrow"
            notify(registration.user_id, f"Reminder: {event.title} is {when}",
                   f"{event.title} takes place {when} at {event.start_time}, {event.venue}. "
                   f"Bring your ticket ({registration.ticket_code}).", event_id=event.id,
                   priority="high", action_url=f"/ticket/{registration.id}")
            sent += 1
        _commit_reminders()

    closing = ctx.Event.query.filter(ctx.Event.status == "approved", ctx.Event.date >= today,
                                     ctx.Event.registration_deadline.in_([today, tomorrow])).all()
    for event in closing:
        kind = "deadline_today" if event.registration_deadline == today else "deadline_24h"
        done = {r.user_id for r in ReminderLog.query.filter_by(event_id=event.id, kind=kind).all()}
        holders = {r.user_id for r in event.registrations if r.status in ACTIVE + ("waitlisted",)}
        for item in WishlistItem.query.filter_by(event_id=event.id).all():
            if item.user_id in done or item.user_id in holders:
                continue
            done.add(item.user_id)
            db.session.add(ReminderLog(user_id=item.user_id, event_id=event.id, kind=kind))
            when = "today" if kind == "deadline_today" else "tomorrow"
            notify(item.user_id, f"Registration closes {when}: {event.title}",
                   f"You saved {event.title}. Registration closes {when} — register before you miss out.",
                   event_id=event.id, priority="high", action_url=f"/events/{event.id}")
            sent += 1
        _commit_reminders()

    for event in ctx.Event.query.filter(ctx.Event.status == "approved", ctx.Event.date >= today).all():
        if waitlist_queue(event) and seats_left(event) > 0:
            promote_waitlist(event)
    return sent


def _commit_reminders():
    try:
        db.session.commit()
    except IntegrityError:  # another worker sent these already
        db.session.rollback()


def maybe_run_reminders(interval_minutes=15):
    """Cheap, throttled trigger used from a before_request hook."""
    global _last_reminder_run
    now = utcnow()
    if _last_reminder_run and now - _last_reminder_run < timedelta(minutes=interval_minutes):
        return
    _last_reminder_run = now
    try:
        send_due_reminders()
    except Exception:  # never break a page view because of a reminder
        db.session.rollback()
        ctx.logger.exception("Reminder run failed")


# ---------------------------------------------------------------------------
# Entry / exit tracking and attendance history
# ---------------------------------------------------------------------------
def log_attendance(registration, action, actor=None, method=None):
    db.session.add(AttendanceLog(event_id=registration.event_id, registration_id=registration.id, action=action,
                                 method=method, actor_id=actor.id if actor is not None and
                                 getattr(actor, "is_authenticated", True) else None, at=utcnow()))


def presence_map(event_id):
    """registration_id -> SimpleNamespace(inside, first_in, last_out, seconds, visits)."""
    logs = (AttendanceLog.query.filter(AttendanceLog.event_id == event_id, AttendanceLog.action.in_(("in", "out")))
            .order_by(AttendanceLog.at.asc(), AttendanceLog.id.asc()).all())
    out = {}
    now = utcnow()
    open_since = {}
    for entry in logs:
        row = out.setdefault(entry.registration_id, SimpleNamespace(inside=False, first_in=None, last_out=None,
                                                                    seconds=0, visits=0))
        if entry.action == "in" and not row.inside:
            row.inside, row.visits = True, row.visits + 1
            row.first_in = row.first_in or entry.at
            open_since[entry.registration_id] = entry.at
        elif entry.action == "out" and row.inside:
            row.inside, row.last_out = False, entry.at
            row.seconds += max(int((entry.at - open_since.pop(entry.registration_id)).total_seconds()), 0)
    for reg_id, since in open_since.items():
        out[reg_id].seconds_live = max(int((now - since).total_seconds()), 0)
    return out


def format_duration(seconds):
    seconds = int(seconds or 0)
    hours, rest = divmod(seconds, 3600)
    minutes = rest // 60
    return f"{hours}h {minutes:02d}m" if hours else f"{minutes}m"


def record_entry(registration, actor, method="entry_desk"):
    """Check a participant in. Returns (status, message) where status is ok/duplicate/invalid."""
    state = presence_map(registration.event_id).get(registration.id)
    if state and state.inside:
        return "duplicate", "Already inside — record an exit first."
    if registration.status not in ("confirmed", "approved"):
        return "invalid", "Only confirmed registrations can enter."
    if not registration.attended:
        ctx.save_attendance(registration, "present", method=method)  # also logs the entry
    else:
        log_attendance(registration, "in", actor, method)
        registration.checkin_time = registration.checkin_time or utcnow()
    return "ok", f"{registration.user.name} checked in."


def record_exit(registration, actor, method="entry_desk"):
    state = presence_map(registration.event_id).get(registration.id)
    if not state or not state.inside:
        return "invalid", "This participant is not currently inside."
    now = utcnow()
    log_attendance(registration, "out", actor, method)
    registration.check_out_time = now
    record = ctx.AttendanceRecord.query.filter_by(registration_id=registration.id).first()
    if record:
        record.check_out_time = now
    return "ok", f"{registration.user.name} checked out."


def on_attendance_marked(registration, status, method, actor):
    """Hook called by the app whenever attendance is saved: history, entry/exit trail and points."""
    log_attendance(registration, status, actor, method)
    last = (AttendanceLog.query.filter(AttendanceLog.registration_id == registration.id,
                                       AttendanceLog.action.in_(("in", "out")))
            .order_by(AttendanceLog.at.desc(), AttendanceLog.id.desc()).first())
    inside = bool(last and last.action == "in")
    if status in ("present", "late") and not inside:
        log_attendance(registration, "in", actor, method)
    elif status == "absent" and inside:
        log_attendance(registration, "out", actor, method)
    award_participation_points(registration)


def award_participation_points(registration):
    """+10 achievement points once a registration is marked attended."""
    exists = AchievementPoint.query.filter_by(user_id=registration.user_id, event_id=registration.event_id,
                                              kind="participation").first()
    if registration.attended and not exists:
        db.session.add(AchievementPoint(user_id=registration.user_id, event_id=registration.event_id,
                                        kind="participation", points=PARTICIPATION_POINTS,
                                        reason=f"Attended {registration.event.title}"))
    elif not registration.attended and exists:
        db.session.delete(exists)


# ---------------------------------------------------------------------------
# Teams
# ---------------------------------------------------------------------------
def team_for_user(event, user):
    return (Team.query.join(TeamMember, TeamMember.team_id == Team.id)
            .filter(Team.event_id == event.id, TeamMember.user_id == user.id).first())


def team_of_registration(registration):
    member = TeamMember.query.filter_by(registration_id=registration.id).first()
    return member.team if member else None


def new_invite_code():
    while True:
        code = secrets.token_hex(3).upper()
        if not Team.query.filter_by(invite_code=code).first():
            return code


def team_limits(event):
    maximum = max(event.max_team_size or 4, 1)
    minimum = min(max(event.min_team_size or 1, 1), maximum)
    return minimum, maximum


# ---------------------------------------------------------------------------
# Competition: entries, rounds, scoring, winners, points
# ---------------------------------------------------------------------------
PARTICIPATION_POINTS = 10
WINNER_CATEGORIES = ["1st Place", "2nd Place", "3rd Place", "Best Performer", "Best Team", "Best Innovation",
                     "Audience Choice", "Special Mention"]
CATEGORY_RANK = {"1st Place": 1, "2nd Place": 2, "3rd Place": 3}
CATEGORY_POINTS = {"1st Place": 50, "2nd Place": 35, "3rd Place": 25}
DEFAULT_WINNER_POINTS = 20


def event_entries(event):
    """Scoring units: one per individual, or one per team (represented by the leader's registration)."""
    regs = (ctx.Registration.query.filter(ctx.Registration.event_id == event.id,
                                          ctx.Registration.status.in_(("confirmed", "approved")))
            .order_by(ctx.Registration.registered_at.asc(), ctx.Registration.id.asc()).all())
    team_by_reg = {}
    teams = {t.id: t for t in Team.query.filter_by(event_id=event.id).all()}
    for team in teams.values():
        for member in team.members:
            team_by_reg[member.registration_id] = team
    grouped = defaultdict(list)
    entries = []
    for reg in regs:
        team = team_by_reg.get(reg.id)
        if team is None:
            entries.append(SimpleNamespace(id=reg.id, label=reg.user.name, team=None, regs=[reg],
                                           members=[reg.user], rep=reg, dept=user_dept(reg.user)))
        else:
            grouped[team.id].append(reg)
    for team_id, member_regs in grouped.items():
        team = teams[team_id]
        rep = next((r for r in member_regs if r.user_id == team.leader_id), member_regs[0])
        entries.append(SimpleNamespace(id=rep.id, label=team.name, team=team, regs=member_regs,
                                       members=[r.user for r in member_regs], rep=rep, dept=user_dept(rep.user)))
    entries.sort(key=lambda e: (e.rep.registered_at or utcnow(), e.id))
    for entry in entries:
        entry.attended = any(r.attended for r in entry.regs)
    return entries


def competition_snapshot(event):
    rounds = EventRound.query.filter_by(event_id=event.id).order_by(EventRound.number).all()
    entries = event_entries(event)
    entry_by_id = {e.id: e for e in entries}
    judges = EventJudge.query.filter_by(event_id=event.id).all()
    by_key = defaultdict(list)
    for score in JudgeScore.query.filter_by(event_id=event.id).all():
        by_key[(score.round_id, score.entry_id)].append(score)

    def avg(round_id, entry_id):
        values = [s.score for s in by_key.get((round_id, entry_id), [])]
        return round(sum(values) / len(values), 2) if values else None

    participants, locked = {}, {}
    previous = None
    for rnd in rounds:
        locked[rnd.id] = False
        if previous is None:
            ids = [e.id for e in entries]
        elif previous.status != "completed":
            ids, locked[rnd.id] = [], True
        elif previous.advance_count:
            scored = sorted((i for i in participants[previous.id] if avg(previous.id, i) is not None),
                            key=lambda i: -avg(previous.id, i))
            if not scored:
                ids = list(participants[previous.id])
            elif len(scored) <= previous.advance_count:
                ids = scored
            else:
                cutoff = avg(previous.id, scored[previous.advance_count - 1])
                ids = [i for i in scored if avg(previous.id, i) >= cutoff]
        else:
            ids = list(participants[previous.id])
        participants[rnd.id] = ids
        previous = rnd

    rows = []
    for entry in entries:
        per_round = {rnd.id: avg(rnd.id, entry.id) for rnd in rounds}
        scored_rounds = [v for v in per_round.values() if v is not None]
        last = next((per_round[r.id] for r in reversed(rounds) if per_round[r.id] is not None), 0)
        rows.append(SimpleNamespace(entry=entry, per_round=per_round,
                                    total=round(sum(scored_rounds), 2), last=last or 0,
                                    scored=bool(scored_rounds)))
    rows.sort(key=lambda r: (-r.total, -r.last, r.entry.rep.registered_at or utcnow(), r.entry.id))
    rank, previous_key = 0, None
    for index, row in enumerate(rows, 1):
        key = (row.total, row.last)
        if key != previous_key:
            rank = index
            previous_key = key
        row.rank = rank if row.scored else None
    return SimpleNamespace(event=event, rounds=rounds, entries=entries, entry_by_id=entry_by_id, judges=judges,
                           participants=participants, locked=locked, rows=rows, avg=avg,
                           judges_scored={(rid, eid): len(v) for (rid, eid), v in by_key.items()})


def calculate_winners(event, actor):
    """Rank entries by total judge score and declare 1st/2nd/3rd (ties share a place)."""
    snap = competition_snapshot(event)
    ranked = [row for row in snap.rows if row.scored]
    if not ranked:
        return 0
    existing = EventWinner.query.filter_by(event_id=event.id).all()
    was_published = any(w.published for w in existing)
    for winner in existing:
        if winner.auto:
            db.session.delete(winner)
    db.session.flush()
    created = 0
    for row in ranked:
        if row.rank not in (1, 2, 3):
            continue
        category = {1: "1st Place", 2: "2nd Place", 3: "3rd Place"}[row.rank]
        db.session.add(EventWinner(event_id=event.id, registration_id=row.entry.id,
                                   team_id=row.entry.team.id if row.entry.team else None, category=category,
                                   rank=row.rank, score=row.total, auto=True, published=was_published,
                                   declared_by=actor.id))
        created += 1
    db.session.flush()
    sync_winner_points(event)
    return created


def announce_results(event, actor):
    """Notify every active user (once per event) that results are out. Caller commits."""
    already = {n.user_id for n in ctx.Notification.query.filter_by(event_id=event.id, category="result").all()}
    sent = 0
    for user in ctx.User.query.filter_by(is_active_account=True).all():
        if user.id in already or (actor is not None and user.id == actor.id):
            continue
        notify(user.id, f"Results announced: {event.title}",
               f"The results of {event.title} are out. See the winners and send them your congratulations!",
               category="result", event_id=event.id, priority="high", action_url=f"/events/{event.id}#winners")
        sent += 1
    return sent


def congratulate(event, winner, sender, message=""):
    """Send a wish to every member behind a published winner row. Returns (sent, skipped_reason)."""
    if not winner.published or winner.event_id != event.id:
        return 0, "Results are not published yet."
    recipients = {r.user_id for r in _winner_member_regs(winner)}
    recipients.discard(sender.id)
    if not recipients:
        return 0, "You can't congratulate yourself."
    note = (message or "").strip()[:200]
    sent = 0
    for user_id in recipients:
        if Congratulation.query.filter_by(event_id=event.id, from_user_id=sender.id, to_user_id=user_id).first():
            continue
        db.session.add(Congratulation(event_id=event.id, winner_id=winner.id, from_user_id=sender.id,
                                      to_user_id=user_id, message=note or None))
        notify(user_id, f"{sender.name} congratulated you 🎉",
               f"{sender.name} sends their best wishes on winning {winner.category} in {event.title}."
               + (f" “{note}”" if note else ""),
               category="event", event_id=event.id, priority="normal", action_url=f"/events/{event.id}#winners")
        sent += 1
    if not sent:
        return 0, "You have already congratulated them."
    return sent, None


def congratulated_user_ids(event, sender):
    return {c.to_user_id for c in Congratulation.query.filter_by(event_id=event.id, from_user_id=sender.id).all()}


def published_winners(event):
    return (EventWinner.query.filter_by(event_id=event.id, published=True)
            .order_by(db.case((EventWinner.rank == 0, 99), else_=EventWinner.rank), EventWinner.category).all())


def winner_for_registration(registration):
    member = TeamMember.query.filter_by(registration_id=registration.id).first()
    best = None
    for winner in EventWinner.query.filter_by(event_id=registration.event_id, published=True).all():
        if winner.registration_id == registration.id or (member and winner.team_id == member.team_id):
            if best is None or (winner.rank or 99) < (best.rank or 99):
                best = winner
    return best


def sync_winner_points(event):
    """Rebuild winner achievement points from the published winner rows."""
    for row in AchievementPoint.query.filter(AchievementPoint.event_id == event.id,
                                             AchievementPoint.kind.like("winner:%")).all():
        db.session.delete(row)
    db.session.flush()
    for winner in EventWinner.query.filter_by(event_id=event.id, published=True).all():
        points = CATEGORY_POINTS.get(winner.category, DEFAULT_WINNER_POINTS)
        for reg in _winner_member_regs(winner):
            kind = f"winner:{winner.category}"[:80]
            if not AchievementPoint.query.filter_by(user_id=reg.user_id, event_id=event.id, kind=kind).first():
                db.session.add(AchievementPoint(user_id=reg.user_id, event_id=event.id, kind=kind, points=points,
                                                reason=f"{winner.category} — {event.title}"))
    db.session.flush()


def bootstrap():
    """Backfill participation points for attendance recorded before this module existed."""
    existing = {(p.user_id, p.event_id) for p in AchievementPoint.query.filter_by(kind="participation").all()}
    for reg in ctx.Registration.query.filter_by(attended=True).all():
        if (reg.user_id, reg.event_id) not in existing and reg.status in ACTIVE:
            db.session.add(AchievementPoint(user_id=reg.user_id, event_id=reg.event_id, kind="participation",
                                            points=PARTICIPATION_POINTS, reason=f"Attended {reg.event.title}"))
    try:
        db.session.commit()
    except IntegrityError:  # another worker backfilled at the same moment
        db.session.rollback()


# ---------------------------------------------------------------------------
# Faculty reports
# ---------------------------------------------------------------------------
def build_faculty_report(user, args):
    role = normalize_role(user.role)
    query = ctx.User.query.filter(ctx.User.role.in_(("faculty", "teacher")))
    if role == "faculty":
        query = query.filter(ctx.User.id == user.id)
    date_from, date_to = parse_date(args.get("from")), parse_date(args.get("to"))
    rows = []
    for faculty in query.order_by(ctx.User.name).all():
        assignments = ctx.EventFaculty.query.filter_by(faculty_id=faculty.id).all()
        events = [a.event for a in assignments if a.event]
        if role == "organizer":
            events = [e for e in events if e.organizer_id == user.id]
            if not events:
                continue
        if date_from:
            events = [e for e in events if e.date >= date_from]
        if date_to:
            events = [e for e in events if e.date <= date_to]
        regs = [r for e in events if e.status != "cancelled" for r in e.registrations]
        stats = reg_stats(regs)
        ratings = [f.rating for r in regs for f in r.feedbacks]
        marks = AttendanceLog.query.filter(AttendanceLog.actor_id == faculty.id,
                                           AttendanceLog.action.in_(("present", "absent", "late"))).count()
        rows.append(SimpleNamespace(
            faculty=faculty, department=user_dept(faculty), events=events, stats=stats,
            completed=sum(1 for e in events if e.status == "completed"),
            upcoming=sum(1 for e in events if e.status == "approved" and e.date >= utcnow().date()),
            avg_rating=round(sum(ratings) / len(ratings), 2) if ratings else None, marks=marks,
            winners=EventWinner.query.filter(EventWinner.event_id.in_([e.id for e in events]),
                                             EventWinner.published.is_(True)).count() if events else 0))
    return SimpleNamespace(rows=rows, date_from=date_from, date_to=date_to)
