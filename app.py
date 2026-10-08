
from datetime import datetime, timedelta, timezone
import csv
import hashlib
from io import BytesIO
from io import StringIO
from functools import wraps
import os
import re
import secrets
from types import SimpleNamespace
from uuid import uuid4
import qrcode
from dotenv import load_dotenv
from flask import Flask, render_template, redirect, url_for, request, flash, send_file, abort, jsonify, session
from flask_wtf.csrf import generate_csrf
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_sqlalchemy import SQLAlchemy
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from markupsafe import Markup, escape

from cems.extensions import csrf, limiter, migrate

load_dotenv()


def utcnow():
    """Naive UTC timestamp (datetime.utcnow() is deprecated)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _env_flag(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


IS_PRODUCTION = os.getenv("FLASK_ENV", "").lower() == "production" or bool(os.getenv("RENDER"))

app = Flask(__name__)


CATEGORY_BANNERS = {
    "academic": "event-academic.svg",
    "technical": "event-technical.svg",
    "cultural": "event-cultural.svg",
    "sports": "event-sports.svg",
    "workshop": "event-workshop.svg",
    "entrepreneurship": "event-entrepreneurship.svg",
    "social": "event-social.svg",
}


def category_banner_url(category):
    """Static banner artwork for an event/notice category."""
    name = CATEGORY_BANNERS.get((category or "").strip().lower())
    return f"/static/images/{name}" if name else "/static/images/placeholder.svg"


def event_banner_url(event):
    if not event:
        return category_banner_url("")
    banner = getattr(event, "banner", None)
    if banner:
        return banner
    return category_banner_url(getattr(event, "category", ""))


def event_image_url(event):
    return event_banner_url(event)


def image_url(path):
    """Resolve an uploaded/static image path to a URL usable in templates."""
    if not path:
        return category_banner_url("")
    if path.startswith(("http://", "https://", "/")):
        return path
    return f"/static/{path}"


# ==============================
# AGC CAMPUS ECOSYSTEM DATA
# ==============================

AGC_INFO = {
    "about": {
        "title": "About AGC",
        "description": """
        Amritsar Group of Colleges (AGC) is an autonomous institution
        focused on quality education, innovation, entrepreneurship,
        research, industry exposure and global opportunities.
        """
    },

    "naac": {
        "title": "NAAC A Grade",
        "description": """
        AGC has been conferred with NAAC 'A' Grade accreditation,
        reflecting its commitment to academic quality and institutional excellence.
        """
    },

    "aicte": {
        "title": "AICTE Approval",
        "description": """
        AGC offers programs aligned with applicable AICTE requirements
        and academic standards.
        """
    },

    "pci": {
        "title": "PCI Approval",
        "description": """
        Pharmacy programs at AGC are aligned with Pharmacy Council
        of India requirements.
        """
    },

    "ikgptu": {
        "title": "IKGPTU Affiliation",
        "description": """
        AGC has academic association with I.K. Gujral Punjab Technical University
        for applicable programs.
        """
    },

    "iqac": {
        "title": "IQAC",
        "description": """
        Internal Quality Assurance Cell works towards continuous
        improvement of academic and institutional quality.
        """
    },

    "aqar": {
        "title": "AQAR Reports",
        "description": """
        Annual Quality Assurance Reports provide information about
        institutional quality initiatives and academic development.
        """
    },

    "aishe": {
        "title": "AISHE",
        "description": """
        All India Survey on Higher Education related institutional information.
        """
    },

    "iso": {
        "title": "ISO",
        "description": """
        AGC follows quality-oriented institutional processes and standards.
        """
    },

    "nptel": {
        "title": "NPTEL",
        "description": """
        Students can benefit from NPTEL courses, certifications and
        digital learning opportunities.
        """
    }
}


AGC_MODULES = {
    "academics": {
        "title": "Academics",
        "icon": "📚",
        "description": "Courses, departments, programs, academic information and learning resources."
    },

    "admissions": {
        "title": "Admissions",
        "icon": "🎓",
        "description": "Admission information, courses, eligibility and enquiry support."
    },

    "examination": {
        "title": "Examination",
        "icon": "📝",
        "description": "Date sheets, examination forms, results, re-appear information and notices."
    },

    "research": {
        "title": "Research",
        "icon": "🔬",
        "description": "Research, innovation, publications, conferences and development activities."
    },

    "placement": {
        "title": "Placement",
        "icon": "💼",
        "description": "Placement opportunities, companies, drives and student career support."
    },

    "alumni": {
        "title": "Alumni",
        "icon": "👥",
        "description": "Connect with AGC alumni, success stories and alumni activities."
    },

    "edc": {
        "title": "Entrepreneurship Development Cell",
        "icon": "🚀",
        "description": "Entrepreneurship, startup ideas, innovation and business development activities."
    },

    "grievance": {
        "title": "Grievance Redressal",
        "icon": "🛡️",
        "description": "Submit and track student grievances through the campus system."
    },

    "infrastructure": {
        "title": "Infrastructure",
        "icon": "🏫",
        "description": "Campus facilities, laboratories, library, hostel, sports and other infrastructure."
    },

    "life": {
        "title": "Life @ AGC",
        "icon": "🌟",
        "description": "Campus life, cultural activities, events, clubs, sports and student experiences."
    },

    "contact": {
        "title": "Contact Us",
        "icon": "📞",
        "description": "Find important AGC contact information and campus directory."
    }
}


# ==============================
# AGC STATISTICS
# ==============================

AGC_STATS = [
    {
        "number": "1475+",
        "title": "Students",
        "description": "Students connected with the AGC academic ecosystem."
    },
    {
        "number": "20+",
        "title": "Years",
        "description": "More than two decades of academic and professional education."
    },
    {
        "number": "25",
        "title": "Programs",
        "description": "Professional undergraduate and postgraduate programs."
    },
    {
        "number": "425+",
        "title": "Jobs",
        "description": "Students secured opportunities through campus placements."
    }
]


# ==============================
# LATEST AGC NOTICES
# ==============================

AGC_NOTICES = [
    "Final Re-appear Date sheet for May-2026 End Semester Examinations",
    "Revised Re-appear Date sheet for Nov-2025 End Semester Examinations",
    "Regular 1st year Date sheet for Nov-2025 End Semester Examinations",
    "Final Re-appear Date sheet for Nov-2025 End Semester Examinations",
    "Proposed Re-appear Date sheet for Nov-2025 End Semester Examinations",
    "Regular Date sheet for Nov-2025 End Semester Examinations",
    "Examination Forms (Re-appear) for Nov-2025 Session",
    "Commencement of Classes session (July-Dec 2025)",
    "AGC NEST 2026",
    "AICTE VAANI Seminar"
]
_secret_key = os.getenv("SECRET_KEY")
if not _secret_key or _secret_key.startswith("change-this"):
    if IS_PRODUCTION:
        raise RuntimeError("SECRET_KEY must be set to a long random value in production.")
    _secret_key = secrets.token_hex(32)  # dev only: sessions reset on restart
app.config["SECRET_KEY"] = _secret_key
app.config["WTF_CSRF_ENABLED"] = True
app.config["WTF_CSRF_TIME_LIMIT"] = 3600
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SECURE"] = _env_flag("SESSION_COOKIE_SECURE", IS_PRODUCTION)
app.config["REMEMBER_COOKIE_HTTPONLY"] = True
app.config["REMEMBER_COOKIE_SAMESITE"] = "Lax"
app.config["REMEMBER_COOKIE_SECURE"] = _env_flag("REMEMBER_COOKIE_SECURE", IS_PRODUCTION)
app.config["RATELIMIT_ENABLED"] = _env_flag("RATELIMIT_ENABLED", True)
db_url = os.getenv("DATABASE_URL", "sqlite:///cems.db")
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024

app.jinja_env.globals["event_banner_url"] = event_banner_url
app.jinja_env.globals["event_image_url"] = event_image_url
app.jinja_env.globals["image_url"] = image_url
app.jinja_env.globals["category_banner_url"] = category_banner_url


def workflow_status(event):
    status = (event.status or "").lower()
    if status == "cancelled":
        return "Cancelled"
    if status == "completed":
        return "Completed"
    if status in ("cancellation_requested", "reschedule_requested"):
        return status.replace("_", " ").title()
    if getattr(event, "change_status", None) == "rescheduled":
        return "Rescheduled"
    return status.title() or "Pending"


def is_event_completed(event):
    return (event.status or "").lower() == "completed"


def event_display_status(event):
    """Human-readable status shown on event pages."""
    status = (event.status or "").lower()
    if status in ("cancelled", "rejected", "draft", "pending", "waiting"):
        return {"waiting": "Pending"}.get(status, status.title())
    if status in ("cancellation_requested", "reschedule_requested"):
        return status.replace("_", " ").title()
    if status == "completed" or (event.date and event.date < utcnow().date()):
        return "Completed"
    return "Approved"


PAYMENT_LABELS = {
    "paid": "Paid", "successful": "Paid", "success": "Paid", "pending": "Pending",
    "free": "Free", "failed": "Failed", "refunded": "Refunded",
}


def payment_display_status(payment_status):
    return PAYMENT_LABELS.get((payment_status or "").lower(), (payment_status or "—").title())


def registration_display_status(registration):
    """Label for a registration row (status column on My Registrations / My Tickets)."""
    if registration.attended:
        return "Attended"
    return (registration.status or "pending").replace("_", " ").title()


app.jinja_env.globals["event_display_status"] = event_display_status
app.jinja_env.globals["payment_display_status"] = payment_display_status
app.jinja_env.globals["registration_display_status"] = registration_display_status
app.jinja_env.globals["workflow_status"] = workflow_status
app.jinja_env.globals["is_event_completed"] = is_event_completed


@app.template_filter("nl2br")
def nl2br(value):
    return Markup("<br>".join(escape(line) for line in str(value or "").splitlines()))

csrf.init_app(app)
limiter.init_app(app)
db = SQLAlchemy(app)
migrate.init_app(app, db)
login_manager = LoginManager(app)
login_manager.login_view = "login"

COLLEGE = os.getenv("COLLEGE_NAME", "Amritsar Group of Colleges")
SHORT = os.getenv("COLLEGE_SHORT", "AGC")
AGC_PROFILE = {
    "tagline": "Autonomous Institution • Amritsar, Punjab",
    "status": "Autonomous",
    "naac": "NAAC A Grade",
    "approvals": ["AICTE", "PCI"],
    "affiliation": "IKGPTU",
    "quality": ["IQAC", "ISO", "NPTEL", "AISHE"],
    "years": "20+ Years",
    "students": "1475+ Students",
    "programs": "25 Programs",
    "placement_highlight": "425+ Jobs reported in the supplied AGC profile content",
    "address": "12 Km Stone, Amritsar-Jalandhar, G.T. Road, Amritsar-143001 (PB), India",
    "phone_primary": "+91 88720 09951",
    "phone_support": "+91 88720 09950",
    "support_line": "24/7 Support Line",
    "email": "info@agc.edu.in",
    "whatsapp": "https://wa.me/918872009950?text=Hello%20AGC%20Support%2C%20I%20need%20help%20with%20campus%20events%20and%20admissions.",
}

AGC_UPDATES = [
    "Final Re-appear Date Sheet for May-2026 End Semester Examinations",
    "AGC NEST 2026 — Scholarship opportunity",
    "AI Centre of Excellence — upcoming initiatives",
    "Certification Course in Artificial Intelligence and Machine Learning",
    "Campus placements and industry-integrated learning updates",
]

ACADEMIC_SESSIONS = [
    "2024-2025",
    "2025-2026",
    "2026-2027",
]

COURSES = ["B.Tech", "M.Tech", "BCA", "MCA", "B.Sc", "B.Com", "BBA", "MBA", "B.Pharmacy", "Diploma", "Other"]
SEMESTERS = [str(n) for n in range(1, 9)]
ORGANIZER_TYPES = ["General", "Student Club / Society", "Department", "Cultural Committee", "Technical Committee", "Sports Committee", "Student Affairs"]

FACULTY_ROLES = [
    "Faculty Member",
    "Club Advisor",
    "Head of Department",
    "Event Coordinator",
    "Judge",
]

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)

    name = db.Column(db.String(120), nullable=False)

    email = db.Column(
        db.String(160),
        unique=True,
        nullable=False
    )

    mobile = db.Column(db.String(20))

    password_hash = db.Column(
        db.String(255),
        nullable=False
    )

    role = db.Column(
        db.String(30),
        default="student"
    )

    department = db.Column(
        db.String(100)
    )

    roll_no = db.Column(
        db.String(50)
    )

    is_active_account = db.Column(
        db.Boolean,
        default=True
    )

    reset_token = db.Column(
        db.String(100)
    )

    reset_token_expires = db.Column(
        db.DateTime
    )

    account_state = db.Column(
        db.String(20),
        default="active"
    )

    created_at = db.Column(
        db.DateTime,
        default=utcnow
    )

    @property
    def student_id(self):
        profile = getattr(self, "student_account_profile", None)
        return profile.student_id if profile else None

    @property
    def account_status(self):
        state = self.account_state or ("active" if self.is_active_account else "disabled")
        if not self.is_active_account and state == "active":
            state = "disabled"
        return SimpleNamespace(value=state)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(
            self.password_hash,
            password
        )


class StudentAccountProfile(db.Model):
    __tablename__ = "student_account_profile"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), unique=True, nullable=False)
    student_id = db.Column(db.String(80), unique=True, nullable=False)
    roll_no = db.Column(db.String(50), nullable=False)
    course = db.Column(db.String(120))
    semester = db.Column(db.String(30))
    academic_session = db.Column(db.String(20))
    batch = db.Column(db.String(30))
    department = db.Column(db.String(120))
    graduation_year = db.Column(db.Integer)
    section = db.Column(db.String(20))
    date_of_birth = db.Column(db.Date)
    profile_image = db.Column(db.String(255))
    linkedin_url = db.Column(db.String(255))
    github_url = db.Column(db.String(255))
    interests = db.Column(db.String(500))
    bio = db.Column(db.Text)
    user = db.relationship("User", backref=db.backref("student_account_profile", uselist=False))


class OrganizerAccountProfile(db.Model):
    __tablename__ = "organizer_account_profile"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), unique=True, nullable=False)
    employee_id = db.Column(db.String(80), unique=True, nullable=False)
    department = db.Column(db.String(120))
    organizer_type = db.Column(db.String(80), default="General")
    designation = db.Column(db.String(120))
    profile_image = db.Column(db.String(255))
    bio = db.Column(db.Text)
    authority_level = db.Column(db.String(80), default="Organizer")
    user = db.relationship("User", backref=db.backref("organizer_account_profile", uselist=False))


class FacultyAccountProfile(db.Model):
    __tablename__ = "faculty_account_profile"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), unique=True, nullable=False)
    employee_id = db.Column(db.String(80), unique=True, nullable=False)
    department = db.Column(db.String(120))
    designation = db.Column(db.String(120))
    faculty_role = db.Column(db.String(80), nullable=False)
    academic_session = db.Column(db.String(20))
    profile_image = db.Column(db.String(255))
    bio = db.Column(db.Text)
    user = db.relationship("User", backref=db.backref("faculty_account_profile", uselist=False))


class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(180), nullable=False)
    category = db.Column(db.String(80), nullable=False)
    event_type = db.Column(db.String(30), default="free")
    date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.String(20), nullable=False)
    end_time = db.Column(db.String(20), nullable=False)
    venue = db.Column(db.String(160), nullable=False)
    description = db.Column(db.Text)
    highlights = db.Column(db.Text)
    banner = db.Column(db.String(255))
    
    capacity = db.Column(db.Integer, default=100)
    registration_deadline = db.Column(db.Date)
    fee = db.Column(db.Float, default=0)
    status = db.Column(db.String(30), default="pending")
    organizer_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow)
    completion_notes = db.Column(db.Text)
    completed_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    completed_at = db.Column(db.DateTime)
    rejection_reason = db.Column(db.Text)
    cancellation_reason = db.Column(db.Text)
    change_status = db.Column(db.String(30))
    rules = db.Column(db.Text)
    eligibility = db.Column(db.Text)
    contact_info = db.Column(db.String(255))
    main_guest = db.Column(db.String(150))
    chief_guest = db.Column(db.String(150))
    target_department = db.Column(db.String(120))
    target_semester = db.Column(db.String(30))
    registration_start = db.Column(db.Date)
    payment_qr = db.Column(db.String(255))
    published_at = db.Column(db.DateTime)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)
    proposed_date = db.Column(db.Date)
    proposed_start_time = db.Column(db.String(20))
    proposed_end_time = db.Column(db.String(20))
    proposed_venue = db.Column(db.String(160))
    proposed_capacity = db.Column(db.Integer)
    reschedule_reason = db.Column(db.Text)
    original_data = db.Column(db.Text)
    organizer = db.relationship("User", foreign_keys=[organizer_id], backref="organized_events")

class EventActivity(db.Model):
    __tablename__ = "event_activity"
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("event.id"), nullable=False)
    actor_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    action = db.Column(db.String(60), nullable=False)
    description = db.Column(db.Text)
    previous_status = db.Column(db.String(30))
    status = db.Column(db.String(30))
    change_reason = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=utcnow)
    event = db.relationship("Event", backref=db.backref("activity_log", order_by="EventActivity.created_at.desc()"))
    actor = db.relationship("User", foreign_keys=[actor_id])


def log_event_activity(event, action, description="", previous=None, status=None, reason=None, actor=None):
    actor = actor or (current_user if current_user and current_user.is_authenticated else None)
    db.session.add(EventActivity(event_id=event.id, actor_id=actor.id if actor else None, action=action,
                                 description=description, previous_status=previous, status=status, change_reason=reason))


class EventFaculty(db.Model):
    __tablename__ = "event_faculty"
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("event.id"), nullable=False)
    faculty_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    assigned_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    assigned_at = db.Column(db.DateTime, default=utcnow)
    event = db.relationship("Event", backref="faculty_assignments")
    faculty = db.relationship("User", foreign_keys=[faculty_id], backref="assigned_events")
    assigner = db.relationship("User", foreign_keys=[assigned_by])

class Attendance(db.Model):
    __tablename__ = "attendance"
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("event.id"), nullable=False)
    registration_id = db.Column(db.Integer, db.ForeignKey("registration.id"), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    status = db.Column(db.String(30), default="present")
    method = db.Column(db.String(30), default="manual")
    marked_at = db.Column(db.DateTime, default=utcnow)

class AttendanceRecord(db.Model):
    __tablename__ = "attendance_record"
    id = db.Column(db.Integer, primary_key=True)
    registration_id = db.Column(db.Integer, db.ForeignKey("registration.id"), unique=True, nullable=False)
    status = db.Column(db.String(30), default="present")
    method = db.Column(db.String(30), default="manual")
    recorded_at = db.Column(db.DateTime, default=utcnow)
    check_in_time = db.Column(db.DateTime)

class DigitalCertificate(db.Model):
    __tablename__ = "digital_certificate"
    id = db.Column(db.Integer, primary_key=True)
    registration_id = db.Column(db.Integer, db.ForeignKey("registration.id"), nullable=False)
    file_name = db.Column(db.String(200))
    issued_at = db.Column(db.DateTime, default=utcnow)
    status = db.Column(db.String(30), default="issued")

class Registration(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ticket_code = db.Column(db.String(30), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey("event.id"), nullable=False)
    status = db.Column(db.String(30), default="confirmed")
    payment_status = db.Column(db.String(30), default="free")
    attended = db.Column(db.Boolean, default=False)
    checkin_time = db.Column(db.DateTime)
    registered_at = db.Column(db.DateTime, default=utcnow)
    user = db.relationship("User", backref="registrations")
    event = db.relationship("Event", backref="registrations")
    feedbacks = db.relationship("Feedback", backref="registration", cascade="all, delete-orphan")

    @property
    def ticket_record(self):
        revoked = (self.status or "") in ("cancelled", "rejected")
        return SimpleNamespace(id=self.id, status="revoked" if revoked else "active", code=self.ticket_code)

    @property
    def payment_record(self):
        if (self.payment_status or "") not in ("paid", "successful"):
            return None
        return SimpleNamespace(transaction_id=f"TXN-{self.ticket_code}", status=self.payment_status)

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    title = db.Column(db.String(180), nullable=False)
    message = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    is_archived = db.Column(db.Boolean, default=False)
    category = db.Column(db.String(30), default="general")
    priority = db.Column(db.String(20), default="normal")
    action_url = db.Column(db.String(255))
    event_id = db.Column(db.Integer, db.ForeignKey("event.id"))
    created_at = db.Column(db.DateTime, default=utcnow)
    user = db.relationship("User", backref="notifications")

class Notice(db.Model):
    __tablename__ = "notice"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(60), nullable=False, default="General")
    description = db.Column(db.Text, nullable=False)
    image = db.Column(db.String(255))
    attachment = db.Column(db.String(255))
    author_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    event_id = db.Column(db.Integer, db.ForeignKey("event.id"))
    published_at = db.Column(db.DateTime, default=utcnow)
    author = db.relationship("User", foreign_keys=[author_id])
    event = db.relationship("Event", foreign_keys=[event_id])


class Feedback(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    registration_id = db.Column(db.Integer, db.ForeignKey("registration.id"), nullable=False)
    rating = db.Column(db.Integer, nullable=False)
    comment = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=utcnow)

    def __repr__(self):
        return f"<Feedback {self.id} for registration {self.registration_id}>"

class Venue(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    location = db.Column(db.String(200))
    capacity = db.Column(db.Integer, default=100)
    available = db.Column(db.Boolean, default=True)

class Volunteer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(160))
    event_id = db.Column(db.Integer, db.ForeignKey("event.id"))
    task = db.Column(db.String(160))
    status = db.Column(db.String(30), default="Assigned")

class Judge(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(160))
    event_id = db.Column(db.Integer, db.ForeignKey("event.id"))
    criteria = db.Column(db.String(250))

class Sponsor(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    contact = db.Column(db.String(160))
    event_id = db.Column(db.Integer, db.ForeignKey("event.id"))
    contribution = db.Column(db.Float, default=0)

class VolunteerRole(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("event.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)
    required_count = db.Column(db.Integer, default=1)
    active = db.Column(db.Boolean, default=True)
    event = db.relationship("Event", backref="volunteer_roles")


class VolunteerApplication(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    role_id = db.Column(db.Integer, db.ForeignKey("volunteer_role.id"), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    status = db.Column(db.String(30), default="pending")
    notes = db.Column(db.Text)
    shift_start = db.Column(db.DateTime)
    shift_end = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=utcnow)
    role = db.relationship("VolunteerRole", backref="applications")
    student = db.relationship("User")


class VolunteerAssignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    role_id = db.Column(db.Integer, db.ForeignKey("volunteer_role.id"), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    status = db.Column(db.String(30), default="assigned")
    notes = db.Column(db.Text)
    shift_start = db.Column(db.DateTime)
    shift_end = db.Column(db.DateTime)
    role = db.relationship("VolunteerRole", backref="assignments")
    student = db.relationship("User")


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

@app.context_processor
def inject_globals():
    unread = 0
    if current_user.is_authenticated:
        unread = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()

    return {
        "college_name": COLLEGE,
        "college_short": SHORT,
        "unread_notifications": unread,
        "current_role": normalize_role(current_user.role) if current_user.is_authenticated else "",
        "agc_profile": AGC_PROFILE,
        "agc_updates": AGC_UPDATES,
        "now": utcnow,
        "current_year": utcnow().year,
        "event_banner_url": event_banner_url,
        "event_image_url": event_image_url,
    }

def normalize_role(role_name):
    if not role_name:
        return ""
    role_name = str(role_name).strip().lower()
    if role_name == "teacher":
        return "faculty"
    return role_name


def get_role_dashboard_route(role_name):
    role = normalize_role(role_name)
    if role == "admin":
        return "admin_dashboard"
    if role == "organizer":
        return "organizer_dashboard"
    if role == "faculty":
        return "faculty_dashboard"
    return "student_dashboard"


def role_required(*roles):
    allowed = {normalize_role(role) for role in roles}

    def decorator(fn):
        @wraps(fn)
        @login_required
        def wrapper(*args, **kwargs):
            user_role = normalize_role(current_user.role)
            if user_role not in allowed:
                flash("You do not have permission to access this page.", "danger")
                return redirect(url_for(get_role_dashboard_route(current_user.role)))
            return fn(*args, **kwargs)
        return wrapper
    return decorator

       
def create_notification(user_id, title, message):
    db.session.add(Notification(user_id=user_id, title=title, message=message))
    db.session.commit()

def send_email(to, subject, body):
    """Send via SMTP when MAIL_SERVER is configured; otherwise log the message (development)."""
    server = os.getenv("MAIL_SERVER")
    if not server:
        app.logger.warning("MAIL_SERVER not set; email to %s not sent.\nSubject: %s\n%s", to, subject, body)
        return False
    import smtplib
    from email.message import EmailMessage
    message = EmailMessage()
    message["From"] = os.getenv("MAIL_FROM", os.getenv("MAIL_USERNAME", "no-reply@localhost"))
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    try:
        with smtplib.SMTP(server, int(os.getenv("MAIL_PORT", 587)), timeout=15) as smtp:
            if _env_flag("MAIL_USE_TLS", True):
                smtp.starttls()
            if os.getenv("MAIL_USERNAME"):
                smtp.login(os.getenv("MAIL_USERNAME"), os.getenv("MAIL_PASSWORD", ""))
            smtp.send_message(message)
        return True
    except Exception:
        app.logger.exception("Failed to send email to %s", to)
        return False


def _add_missing_columns():
    """Lightweight schema sync: add columns that models define but the database lacks."""
    from sqlalchemy import inspect, text
    inspector = inspect(db.engine)
    for table in db.metadata.sorted_tables:
        if not inspector.has_table(table.name):
            continue
        existing = {col["name"] for col in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in existing:
                continue
            col_type = column.type.compile(db.engine.dialect)
            with db.engine.begin() as conn:
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}'))


ALLOW_DEMO_PAYMENTS = _env_flag("ALLOW_DEMO_PAYMENTS", not IS_PRODUCTION)
SEED_DEMO_DATA = _env_flag("SEED_DEMO_DATA", not IS_PRODUCTION)
_seeded = False


def seed_data():
    """Create tables; load demo accounts/events once, only when SEED_DEMO_DATA is on."""
    global _seeded
    if _seeded:
        return
    db.create_all()
    _add_missing_columns()
    _seeded = True
    if not SEED_DEMO_DATA:
        return

    demo_users = [
        {
            "email": "admin@agc.local",
            "name": "AGC Admin",
            "role": "admin",
            "department": "Administration",
            "password": "Admin@123",
        },
        {
            "email": "organizer@agc.local",
            "name": "AGC Event Organizer",
            "role": "organizer",
            "department": "Student Affairs",
            "password": "Organizer@123",
        },
        {
            "email": "teacher@agc.local",
            "name": "Dr. Meera Kapoor",
            "role": "teacher",
            "department": "Computer Science",
            "password": "Teacher@123",
        },
        {
            "email": "student@agc.local",
            "name": "Rahul Sharma",
            "role": "student",
            "department": "Computer Science",
            "roll_no": "21CS1001",
            "mobile": "9876543210",
            "password": "Student@123",
        },
    ]

    for user_data in demo_users:
        user = User.query.filter_by(email=user_data["email"]).first()
        if user is None:
            user = User(
                name=user_data["name"],
                email=user_data["email"],
                role=user_data["role"],
                department=user_data["department"],
                roll_no=user_data.get("roll_no"),
                mobile=user_data.get("mobile"),
            )
            user.set_password(user_data["password"])
            db.session.add(user)

    db.session.commit()

    organizer = User.query.filter_by(email="organizer@agc.local").one()
    teacher = User.query.filter_by(email="teacher@agc.local").one()
    admin = User.query.filter_by(email="admin@agc.local").one()

    if Venue.query.count() == 0:
        venues = [
            Venue(name="Main Auditorium", location="AGC Campus", capacity=500),
            Venue(name="Open Ground", location="AGC Campus", capacity=1000),
            Venue(name="Seminar Hall", location="Computer Science Block", capacity=250),
            Venue(name="Innovation Lab", location="Engineering Block", capacity=120),
        ]
        db.session.add_all(venues)
        db.session.flush()

    if Event.query.count() == 0:
        sample = [
            # Academic Events
            ("AI & Machine Learning Seminar", "Academic", "free", 2026, 9, 5, "10:00 AM", "12:00 PM", "Seminar Hall", 150, 0),
            ("Research Paper Writing Workshop", "Academic", "free", 2026, 9, 12, "2:00 PM", "4:00 PM", "Seminar Hall", 100, 0),
            ("NPTEL & Digital Learning Orientation", "Academic", "free", 2026, 9, 18, "11:00 AM", "1:00 PM", "Seminar Hall", 250, 0),
            ("Industrial Research Trends 2026", "Academic", "free", 2026, 9, 25, "10:00 AM", "2:00 PM", "Main Auditorium", 300, 0),
            ("Entrepreneurship & Innovation Lecture", "Academic", "paid", 2026, 10, 2, "3:00 PM", "5:00 PM", "Innovation Lab", 120, 99),
            
            # Technical Events
            ("AGC Tech Fest 2026", "Technical", "free", 2026, 9, 12, "10:00 AM", "5:00 PM", "Main Auditorium", 500, 0),
            ("Coding Hackathon - 24 Hours", "Technical", "free", 2026, 9, 28, "10:00 AM", "10:00 AM", "Innovation Lab", 200, 0),
            ("Web Development Bootcamp", "Technical", "paid", 2026, 10, 5, "9:00 AM", "5:00 PM", "Computer Lab", 80, 299),
            ("Mobile App Development Challenge", "Technical", "free", 2026, 10, 15, "2:00 PM", "6:00 PM", "Innovation Lab", 100, 0),
            ("Cybersecurity Workshop & Hands-on", "Technical", "paid", 2026, 10, 22, "10:00 AM", "4:00 PM", "Computer Lab", 60, 199),
            ("Cloud Computing Fundamentals", "Technical", "free", 2026, 11, 3, "11:00 AM", "1:00 PM", "Seminar Hall", 150, 0),
            ("Data Science & Analytics Masterclass", "Technical", "paid", 2026, 11, 10, "10:00 AM", "5:00 PM", "Computer Lab", 100, 249),
            
            # Cultural Events
            ("AGC Cultural Fiesta 2026", "Cultural", "free", 2026, 9, 19, "11:00 AM", "5:00 PM", "Open Ground", 1000, 0),
            ("Classical Music Concert", "Cultural", "free", 2026, 10, 8, "6:00 PM", "9:00 PM", "Main Auditorium", 500, 0),
            ("Contemporary Dance Performance", "Cultural", "free", 2026, 10, 16, "7:00 PM", "9:30 PM", "Open Ground", 800, 0),
            ("Art Exhibition & Painting Workshop", "Cultural", "free", 2026, 10, 24, "10:00 AM", "4:00 PM", "Innovation Lab", 200, 0),
            ("Theater & Dramatics Play", "Cultural", "free", 2026, 11, 5, "7:00 PM", "9:30 PM", "Main Auditorium", 600, 0),
            ("Poetry & Creative Writing Festival", "Cultural", "free", 2026, 11, 12, "5:00 PM", "8:00 PM", "Seminar Hall", 300, 0),
            
            # Sports Events
            ("AGC Sports & Athletic Meet", "Sports", "free", 2026, 11, 7, "9:00 AM", "5:00 PM", "Open Ground", 1000, 0),
            ("Cricket Tournament Finals", "Sports", "free", 2026, 9, 20, "3:00 PM", "6:00 PM", "Open Ground", 500, 0),
            ("Football League Championship", "Sports", "free", 2026, 10, 12, "4:00 PM", "7:00 PM", "Open Ground", 800, 0),
            ("Badminton Singles & Doubles", "Sports", "free", 2026, 10, 28, "9:00 AM", "5:00 PM", "Sports Complex", 150, 0),
            ("Basketball 3-on-3 Tournament", "Sports", "free", 2026, 11, 14, "10:00 AM", "4:00 PM", "Sports Complex", 200, 0),
            ("Volleyball Championship", "Sports", "free", 2026, 11, 21, "3:00 PM", "7:00 PM", "Sports Complex", 250, 0),
            
            # Workshop Events
            ("AI & Emerging Technologies Workshop", "Workshop", "free", 2026, 10, 2, "10:00 AM", "2:00 PM", "Seminar Hall", 250, 0),
            ("Digital Marketing & Social Media", "Workshop", "paid", 2026, 10, 9, "2:00 PM", "5:00 PM", "Innovation Lab", 100, 149),
            ("Leadership & Team Management", "Workshop", "free", 2026, 10, 16, "10:00 AM", "1:00 PM", "Main Auditorium", 300, 0),
            ("Public Speaking & Presentation Skills", "Workshop", "free", 2026, 10, 23, "3:00 PM", "5:00 PM", "Seminar Hall", 200, 0),
            ("Graphic Design & UI/UX Basics", "Workshop", "paid", 2026, 11, 1, "10:00 AM", "4:00 PM", "Computer Lab", 80, 199),
            ("Environmental Awareness & Sustainability", "Workshop", "free", 2026, 11, 8, "2:00 PM", "4:00 PM", "Main Auditorium", 400, 0),
            
            # Entrepreneurship Events
            ("AGC Innovation & Entrepreneurship Summit", "Entrepreneurship", "paid", 2026, 10, 10, "10:00 AM", "4:00 PM", "Innovation Lab", 120, 199),
            ("Startup Pitch Competition", "Entrepreneurship", "free", 2026, 10, 25, "3:00 PM", "6:00 PM", "Main Auditorium", 500, 0),
            ("Business Model Canvas Workshop", "Entrepreneurship", "free", 2026, 11, 2, "10:00 AM", "12:30 PM", "Innovation Lab", 150, 0),
            ("Funding & Investor Pitching Session", "Entrepreneurship", "paid", 2026, 11, 9, "2:00 PM", "5:00 PM", "Innovation Lab", 100, 249),
            ("Social Enterprise & Impact Startup", "Entrepreneurship", "free", 2026, 11, 15, "11:00 AM", "1:00 PM", "Seminar Hall", 200, 0),
        ]
        # Demo dates are authored around 20 Sep 2026; shift them so the data always
        # has upcoming and past events relative to the day the app first runs.
        shift = utcnow().date() - datetime(2026, 9, 20).date()
        for title, cat, typ, y, m, d, st, et, venue, cap, fee in sample:
            event_date = datetime(y, m, d).date() + shift
            e = Event(title=title, category=cat, event_type=typ, date=event_date,
                      start_time=st, end_time=et, venue=venue,
                      description=f"{title} is a campus event at {COLLEGE}, designed for students, faculty, clubs and invited guests to learn, participate, collaborate and showcase talent. This event features industry experts, peer learning, and hands-on experience.",
                      highlights="Student participation\nIndustry interaction\nCompetitions & activities\nNetworking & learning\nCertificates\nRefreshments",
                      capacity=cap, registration_deadline=event_date-timedelta(days=2),
                      fee=fee, status="approved", organizer_id=organizer.id)
            db.session.add(e)
        db.session.flush()

        assigned_events = Event.query.order_by(Event.date.asc()).limit(3).all()
        for event in assigned_events:
            db.session.add(EventFaculty(event_id=event.id, faculty_id=teacher.id, assigned_by=admin.id))
        db.session.commit()

    if Notice.query.count() == 0:
        notice_rows = [
            ("AGC Cultural Fiesta 2026 - Participants Required", "Cultural", "The Annual AGC Cultural Fiesta will be held on 19th September 2026. Students interested in participating in music, dance, drama, and literary events can register through the CEMS portal before the deadline.", 2),
            ("Library Timings - Extended for End Semester", "Academic", "In view of the upcoming end semester examinations, the Central Library will remain open from 7:00 AM to 11:00 PM daily until 30th November 2026. Students are advised to utilize the extended hours for preparation.", 3),
            ("Blood Donation Camp - 12th November 2026", "Social", "The NSS unit is organizing a voluntary blood donation camp on 12th November 2026 from 9:00 AM to 4:00 PM at the Health Center. All willing students, faculty, and staff are encouraged to participate.", 4),
            ("Hackathon Registrations Open", "Technical", "Registrations for the 24-hour Coding Hackathon are now open. Form teams of up to four members and register on the events page. Seats are limited.", 5),
            ("Annual Sports Meet - Volunteers Needed", "Sports", "The Sports Department needs student volunteers for the Annual Sports & Athletic Meet. Interested students can contact the organizing committee.", 6),
            ("NPTEL Enrollment Reminder", "Academic", "Students enrolling for NPTEL certification courses this semester must complete registration before the deadline announced by the examination cell.", 7),
        ]
        for title, category, description, days_ago in notice_rows:
            db.session.add(Notice(title=title, category=category, description=description, author_id=admin.id,
                                  published_at=utcnow() - timedelta(days=days_ago)))
        db.session.commit()

# ==============================
# AGC HOME
# ==============================

# ==============================
# ABOUT AGC
# ==============================

@app.route("/about")
def about():
    return render_template(
        "agc_info.html",
        info=AGC_INFO["about"]
    )


# ==============================
# CONTACT
# ==============================

@app.route("/contact")
def contact():
    return render_template(
        "contact.html"
    )


# ==============================
# AGC INFORMATION
# ==============================

@app.route("/agc-info/<slug>")
def agc_info(slug):

    if slug not in AGC_INFO:
        abort(404)

    return render_template(
        "agc_info.html",
        info=AGC_INFO[slug]
    )


# ==============================
# AGC MODULE
# ==============================

@app.route("/module/<slug>")
def agc_module(slug):

    if slug not in AGC_MODULES:
        abort(404)

    return render_template(
        "module.html",
        module=AGC_MODULES[slug]
    )


# ==============================
# NOTICE DETAILS
# ==============================

@app.route("/notice/<int:index>")
def notice_detail(index):

    if index < 0 or index >= len(AGC_NOTICES):
        abort(404)

    return render_template(
        "notice.html",
        notice=AGC_NOTICES[index]
    )


NOTICE_CATEGORIES = [
    "General", "Academic", "Technical", "Cultural", "Sports", "Workshop",
    "Entrepreneurship", "Social", "Important Notice", "Campus Update",
]


def _prepare_image_upload(field, folder, max_bytes=2 * 1024 * 1024, label="Image"):
    upload = request.files.get(field)
    if not upload or not upload.filename:
        return None, None, None
    extension = os.path.splitext(secure_filename(upload.filename))[1].lower()
    if extension not in {".jpg", ".jpeg", ".png", ".webp"}:
        return None, None, "Choose a JPG, PNG, or WEBP image."
    upload.stream.seek(0, os.SEEK_END)
    size = upload.stream.tell()
    upload.stream.seek(0)
    if size > max_bytes:
        return None, None, f"{label} must be {max_bytes // (1024 * 1024)} MB or smaller."
    return upload, f"/static/uploads/{folder}/{uuid4().hex}{extension}", None


def _notice_listing(per_page=12):
    q = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    page = request.args.get("page", 1, type=int)
    query = Notice.query
    if q:
        query = query.filter(db.or_(Notice.title.ilike(f"%{q}%"), Notice.description.ilike(f"%{q}%")))
    if category:
        query = query.filter(Notice.category == category)
    pagination = query.order_by(Notice.published_at.desc(), Notice.id.desc()).paginate(page=page, per_page=per_page, error_out=False)
    categories = sorted({row[0] for row in db.session.query(Notice.category).distinct().all() if row[0]})
    return dict(notices=pagination.items, pagination=pagination, q=q, category=category, categories=categories)


def _can_manage_notice(notice):
    return current_user.is_authenticated and (
        normalize_role(current_user.role) == "admin" or notice.author_id == current_user.id
    )


app.jinja_env.globals["can_manage_notice"] = _can_manage_notice


@app.route("/notices")
def notices():
    return render_template("notices.html", **_notice_listing())


@app.route("/notices/<int:notice_id>")
def board_notice_detail(notice_id):
    notice = Notice.query.get_or_404(notice_id)
    related = Notice.query.filter(Notice.id != notice.id, Notice.category == notice.category).order_by(Notice.published_at.desc()).limit(3).all()
    return render_template("notice_detail.html", notice=notice, related=related)


def _save_notice_from_form(notice):
    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    category = request.form.get("category", "General").strip() or "General"
    if not title or not description:
        flash("Title and description are required.", "danger")
        return False
    upload, image_path, error = _prepare_image_upload("image", "notices", label="Notice image")
    if error:
        flash(error, "danger")
        return False
    notice.title = title[:200]
    notice.description = description
    notice.category = category[:60]
    if image_path:
        _store_event_banner(upload, image_path)
        notice.image = image_path
    return True


@app.route("/faculty/notices", methods=["GET", "POST"])
@role_required("faculty", "organizer", "admin")
def faculty_notices():
    if request.method == "POST":
        notice = Notice(author_id=current_user.id, title="", description="")
        if _save_notice_from_form(notice):
            db.session.add(notice)
            db.session.commit()
            flash("Notice posted.", "success")
        return redirect(url_for("faculty_notices"))
    return render_template("faculty/notices.html", note_categories=NOTICE_CATEGORIES, **_notice_listing())


@app.route("/faculty/notices/<int:notice_id>/edit")
@role_required("faculty", "organizer", "admin")
def faculty_notice_edit_form(notice_id):
    notice = Notice.query.get_or_404(notice_id)
    if not _can_manage_notice(notice):
        flash("You can only edit notices you posted.", "danger")
        return redirect(url_for("faculty_notices"))
    return render_template("faculty/notice_edit.html", notice=notice, categories=NOTICE_CATEGORIES)


@app.route("/faculty/notices/<int:notice_id>/update", methods=["POST"])
@role_required("faculty", "organizer", "admin")
def faculty_notice_edit(notice_id):
    notice = Notice.query.get_or_404(notice_id)
    if not _can_manage_notice(notice):
        abort(403)
    if _save_notice_from_form(notice):
        db.session.commit()
        flash("Notice updated.", "success")
        return redirect(url_for("faculty_notices"))
    return redirect(url_for("faculty_notice_edit_form", notice_id=notice.id))


@app.route("/faculty/notices/<int:notice_id>/delete", methods=["POST"])
@role_required("faculty", "organizer", "admin")
def faculty_notice_delete(notice_id):
    notice = Notice.query.get_or_404(notice_id)
    if not _can_manage_notice(notice):
        abort(403)
    db.session.delete(notice)
    db.session.commit()
    flash("Notice deleted.", "success")
    return redirect(request.form.get("next") or url_for("faculty_notices"))


@app.route("/admin/notices", methods=["GET", "POST"])
@role_required("admin")
def admin_notices():
    if request.method == "POST":
        notice = Notice(author_id=current_user.id, title="", description="")
        if _save_notice_from_form(notice):
            event_id = request.form.get("event_id", type=int)
            notice.event_id = event_id if event_id and db.session.get(Event, event_id) else None
            db.session.add(notice)
            db.session.commit()
            flash("Notice published.", "success")
        return redirect(url_for("admin_notices"))
    events = Event.query.order_by(Event.date.desc()).all()
    return render_template("admin/notices.html", events=events, note_categories=NOTICE_CATEGORIES, **_notice_listing(per_page=15))


@app.route("/admin/notices/<int:notice_id>/delete", methods=["POST"])
@role_required("admin")
def delete_notice(notice_id):
    notice = Notice.query.get_or_404(notice_id)
    db.session.delete(notice)
    db.session.commit()
    flash("Notice deleted.", "success")
    return redirect(url_for("admin_notices"))


@app.route("/")
def landing():
    events = Event.query.filter_by(status="approved").order_by(Event.date.asc()).limit(4).all()
    return render_template("landing.html", events=events)


def _registration_payload():
    if request.is_json:
        payload = request.get_json(silent=True) or {}
    else:
        payload = request.form.to_dict()
    return payload


def _prepare_profile_photo():
    upload = request.files.get("profile_photo")
    if not upload or not upload.filename:
        return None, None, None

    filename = secure_filename(upload.filename)
    extension = os.path.splitext(filename)[1].lower()
    if extension not in {".jpg", ".jpeg", ".png", ".webp"}:
        return None, None, "Choose a JPG, PNG, or WEBP image."

    upload.stream.seek(0, os.SEEK_END)
    size = upload.stream.tell()
    upload.stream.seek(0)
    if size > 2 * 1024 * 1024:
        return None, None, "Profile photos must be 2 MB or smaller."

    relative_path = f"uploads/profiles/{uuid4().hex}{extension}"
    return upload, relative_path, None


def _store_profile_photo(upload, relative_path):
    if not upload or not relative_path:
        return
    destination = os.path.join(app.static_folder, relative_path)
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    upload.save(destination)


def _delete_profile_photo(relative_path):
    if not relative_path:
        return
    try:
        os.remove(os.path.join(app.static_folder, relative_path))
    except FileNotFoundError:
        pass


def _prepare_event_banner():
    upload = request.files.get("banner")
    if not upload or not upload.filename:
        return None, None, None
    filename = secure_filename(upload.filename)
    extension = os.path.splitext(filename)[1].lower()
    if extension not in {".jpg", ".jpeg", ".png", ".webp"}:
        return None, None, "Choose a JPG, PNG, or WEBP event banner."
    upload.stream.seek(0, os.SEEK_END)
    size = upload.stream.tell()
    upload.stream.seek(0)
    if size > 4 * 1024 * 1024:
        return None, None, "Event banners must be 4 MB or smaller."
    return upload, f"/static/uploads/events/{uuid4().hex}{extension}", None


def _store_event_banner(upload, public_path):
    if not upload or not public_path:
        return
    relative_path = public_path.removeprefix("/static/")
    destination = os.path.join(app.static_folder, relative_path)
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    upload.save(destination)


def _parse_dob(value):
    try:
        parsed = datetime.strptime((value or "").strip(), "%Y-%m-%d").date()
    except ValueError:
        return None
    return parsed if parsed <= utcnow().date() else None


def _registration_success(login_endpoint, message):
    redirect_url = url_for(login_endpoint)
    flash(message, "success")
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"success": True, "message": message, "redirect": redirect_url})
    return redirect(redirect_url)


def _validate_registration_step(role, step, payload):
    role = (role or "").strip().lower()
    step = str(step or "").strip()
    errors = {}
    valid_roles = {"student", "organizer", "faculty"}
    if role not in valid_roles:
        return {"role": "Invalid role."}, 400
    allowed_steps = {
        "student": {"1", "2", "3", "4"},
        "organizer": {"1", "2", "3"},
        "faculty": {"1", "2", "3"},
    }
    if step not in allowed_steps.get(role, set()):
        return {"step": "Invalid step for this role."}, 400

    if step == "1":
        name = (payload.get("name") or "").strip()
        email = (payload.get("email") or "").strip().lower()
        mobile = (payload.get("mobile") or "").strip()
        if not name:
            errors["name"] = "Full name is required."
        if not email:
            errors["email"] = "Email address is required."
        elif "@" not in email:
            errors["email"] = "Enter a valid email address."
        if mobile and len("".join(ch for ch in mobile if ch.isdigit())) < 10:
            errors["mobile"] = "Enter a valid mobile number."
    elif step == "2":
        if role == "student":
            student_id = (payload.get("student_id") or "").strip()
            roll_no = (payload.get("roll_no") or "").strip()
            if not student_id:
                errors["student_id"] = "Student ID is required."
            if not roll_no:
                errors["roll_no"] = "Roll number is required."
        elif role == "organizer":
            employee_id = (payload.get("employee_id") or "").strip()
            if not employee_id:
                errors["employee_id"] = "Employee ID is required."
        else:
            employee_id = (payload.get("employee_id") or "").strip()
            faculty_role = (payload.get("faculty_role") or "").strip()
            academic_session = (payload.get("academic_session") or "").strip()
            if not employee_id:
                errors["employee_id"] = "Faculty ID is required."
            if not faculty_role:
                errors["faculty_role"] = "Select a faculty role."
            if academic_session and academic_session not in ACADEMIC_SESSIONS:
                errors["academic_session"] = "Select a valid academic session."
    elif step == "3":
        if role == "student":
            course = (payload.get("course") or "").strip()
            semester = (payload.get("semester") or "").strip()
            academic_session = (payload.get("academic_session") or "").strip()
            batch = (payload.get("batch") or "").strip()
            if not course:
                errors["course"] = "Course is required."
            if not semester:
                errors["semester"] = "Semester is required."
            if not academic_session:
                errors["academic_session"] = "Academic session is required."
        elif role in {"organizer", "faculty"}:
            password = payload.get("password") or ""
            confirm = payload.get("confirm_password") or ""
            if not password:
                errors["password"] = "Password is required."
            elif len(password) < 8:
                errors["password"] = "Password must be at least 8 characters long."
            if not confirm:
                errors["confirm_password"] = "Please confirm the password."
            elif password != confirm:
                errors["confirm_password"] = "Passwords do not match."
    elif step == "4":
        password = payload.get("password") or ""
        confirm = payload.get("confirm_password") or ""
        if not password:
            errors["password"] = "Password is required."
        elif len(password) < 8:
            errors["password"] = "Password must be at least 8 characters long."
        if not confirm:
            errors["confirm_password"] = "Please confirm the password."
        elif password != confirm:
            errors["confirm_password"] = "Passwords do not match."

    return errors, 200 if not errors else 400


@app.route("/api/register/validate-step", methods=["POST"])
def api_validate_registration_step():
    payload = _registration_payload()
    role = (payload.get("role") or request.args.get("role") or "").strip().lower()
    step = str(payload.get("step") or request.args.get("step") or "").strip()
    errors, status = _validate_registration_step(role, step, payload)
    if status == 400:
        return jsonify({"success": False, "errors": errors}), 400
    return jsonify({"success": True, "message": "Validation passed."}), 200


@app.route("/api/register/save-step", methods=["POST"])
def api_register_save_step():
    payload = _registration_payload()
    role = (payload.get("role") or "").strip().lower()
    if not role:
        return jsonify({"success": False, "errors": {"role": "Role is required."}}), 400
    session_data = session.get("registration_data", {})
    session_data.setdefault(role, {})
    for key, value in payload.items():
        if key != "role":
            session_data[role][key] = value
    session["registration_data"] = session_data
    return jsonify({"success": True, "data": session_data.get(role, {})}), 200


@app.route("/api/register/restore-step", methods=["POST"])
def api_register_restore_step():
    payload = _registration_payload()
    role = (payload.get("role") or "").strip().lower()
    step = str(payload.get("step") or "").strip()
    session_data = session.get("registration_data", {})
    data = session_data.get(role, {}) if role else {}
    if step and step != "all":
        data = {key: value for key, value in data.items() if key.startswith(f"step_{step}") or key not in {"step"}}
    return jsonify({"success": True, "data": data}), 200


@app.route("/api/register/clear-session", methods=["POST"])
def api_register_clear_session():
    session.pop("registration_data", None)
    return jsonify({"success": True, "message": "Registration session cleared."}), 200


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    return render_template("auth/account_type.html")


@app.route("/register/student", methods=["GET", "POST"])
def student_register_page():
    if request.method == "GET" and current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        payload = _registration_payload()
        email = (payload.get("email") or "").strip().lower()
        if email and User.query.filter_by(email=email).first():
            return jsonify({"success": False, "errors": {"email": "An account with this email already exists."}}), 400
        errors, status = _validate_registration_step("student", "1", payload)
        if status != 200:
            return jsonify({"success": False, "errors": errors}), 400
        errors, status = _validate_registration_step("student", "2", payload)
        if status != 200:
            return jsonify({"success": False, "errors": errors}), 400
        errors, status = _validate_registration_step("student", "3", payload)
        if status != 200:
            return jsonify({"success": False, "errors": errors}), 400
        errors, status = _validate_registration_step("student", "4", payload)
        if status != 200:
            return jsonify({"success": False, "errors": errors}), 400
        student_id = (payload.get("student_id") or "").strip()
        if StudentAccountProfile.query.filter_by(student_id=student_id).first():
            return jsonify({"success": False, "errors": {"student_id": "This student ID is already registered."}}), 400
        upload, profile_image, photo_error = _prepare_profile_photo()
        if photo_error:
            return jsonify({"success": False, "errors": {"profile_photo": photo_error}}), 400
        password = payload.get("password") or ""
        user = User(
            name=(payload.get("name") or "").strip(),
            email=email,
            mobile=(payload.get("mobile") or "").strip(),
            role="student",
            department=(payload.get("department") or "").strip(),
            roll_no=(payload.get("roll_no") or "").strip(),
        )
        user.set_password(password)
        db.session.add(user)
        profile = StudentAccountProfile(
            user=user,
            student_id=student_id,
            roll_no=(payload.get("roll_no") or "").strip(),
            course=(payload.get("course") or "").strip(),
            semester=(payload.get("semester") or "").strip(),
            academic_session=(payload.get("academic_session") or "").strip(),
            batch=((payload.get("batch") or "").strip() or (payload.get("academic_session") or "").strip()),
            section=(payload.get("section") or "").strip(),
            date_of_birth=_parse_dob(payload.get("date_of_birth")),
            department=(payload.get("department") or "").strip(),
            profile_image=profile_image,
        )
        db.session.add(profile)
        try:
            _store_profile_photo(upload, profile_image)
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            _delete_profile_photo(profile_image)
            return jsonify({"success": False, "errors": {"account": "An account with this email or student ID already exists."}}), 400
        return _registration_success("login", "Student account created successfully. Please sign in.")
    return render_template("auth/student_register.html", today_iso=utcnow().date().isoformat(), academic_sessions=ACADEMIC_SESSIONS, courses=COURSES, semesters=SEMESTERS)


@app.route("/register/organizer", methods=["GET", "POST"])
def organizer_register_page():
    if request.method == "GET" and current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        payload = _registration_payload()
        email = (payload.get("email") or "").strip().lower()
        if email and User.query.filter_by(email=email).first():
            return jsonify({"success": False, "errors": {"email": "An account with this email already exists."}}), 400
        for step in ("1", "2"):
            errors, status = _validate_registration_step("organizer", step, payload)
            if status != 200:
                return jsonify({"success": False, "errors": errors}), 400
        errors, status = _validate_registration_step("organizer", "3", payload)
        if status != 200:
            return jsonify({"success": False, "errors": errors}), 400
        employee_id = (payload.get("employee_id") or "").strip()
        if OrganizerAccountProfile.query.filter_by(employee_id=employee_id).first():
            return jsonify({"success": False, "errors": {"employee_id": "This organizer ID is already registered."}}), 400
        upload, profile_image, photo_error = _prepare_profile_photo()
        if photo_error:
            return jsonify({"success": False, "errors": {"profile_photo": photo_error}}), 400
        user = User(name=(payload.get("name") or "").strip(), email=email, mobile=(payload.get("mobile") or "").strip(), role="organizer", department=(payload.get("department") or "").strip())
        user.set_password(payload.get("password") or "")
        db.session.add(user)
        db.session.add(OrganizerAccountProfile(
            user=user,
            employee_id=employee_id,
            department=(payload.get("department") or "").strip(),
            organizer_type=(payload.get("organizer_type") or "General").strip(),
            designation=(payload.get("designation") or "").strip(),
            profile_image=profile_image,
        ))
        try:
            _store_profile_photo(upload, profile_image)
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            _delete_profile_photo(profile_image)
            return jsonify({"success": False, "errors": {"account": "An account with this email or organizer ID already exists."}}), 400
        return _registration_success("login", "Organizer account created successfully. Please sign in.")
    return render_template("auth/organizer_register.html", today_iso=utcnow().date().isoformat(), organizer_types=ORGANIZER_TYPES)


@app.route("/register/faculty", methods=["GET", "POST"])
def faculty_register_page():
    if request.method == "GET" and current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        payload = _registration_payload()
        email = (payload.get("email") or "").strip().lower()
        if email and User.query.filter_by(email=email).first():
            return jsonify({"success": False, "errors": {"email": "An account with this email already exists."}}), 400
        for step in ("1", "2"):
            errors, status = _validate_registration_step("faculty", step, payload)
            if status != 200:
                return jsonify({"success": False, "errors": errors}), 400
        errors, status = _validate_registration_step("faculty", "3", payload)
        if status != 200:
            return jsonify({"success": False, "errors": errors}), 400
        employee_id = (payload.get("employee_id") or "").strip()
        if FacultyAccountProfile.query.filter_by(employee_id=employee_id).first():
            return jsonify({"success": False, "errors": {"employee_id": "This faculty ID is already registered."}}), 400
        upload, profile_image, photo_error = _prepare_profile_photo()
        if photo_error:
            return jsonify({"success": False, "errors": {"profile_photo": photo_error}}), 400
        user = User(name=(payload.get("name") or "").strip(), email=email, mobile=(payload.get("mobile") or "").strip(), role="faculty", department=(payload.get("department") or "").strip())
        user.set_password(payload.get("password") or "")
        db.session.add(user)
        db.session.add(FacultyAccountProfile(
            user=user,
            employee_id=employee_id,
            department=(payload.get("department") or "").strip(),
            designation=(payload.get("designation") or "").strip(),
            faculty_role=(payload.get("faculty_role") or "").strip(),
            academic_session=(payload.get("academic_session") or "").strip() or ACADEMIC_SESSIONS[1],
            profile_image=profile_image,
        ))
        try:
            _store_profile_photo(upload, profile_image)
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            _delete_profile_photo(profile_image)
            return jsonify({"success": False, "errors": {"account": "An account with this email or faculty ID already exists."}}), 400
        return _registration_success("login", "Faculty account created successfully. Please sign in.")
    return render_template("auth/faculty_register.html", today_iso=utcnow().date().isoformat(), academic_sessions=ACADEMIC_SESSIONS, faculty_roles=FACULTY_ROLES)


def _demo_accounts():
    if IS_PRODUCTION or not SEED_DEMO_DATA:
        return []
    return [
        ("Admin", "admin@agc.local", "Admin@123"),
        ("Organizer", "organizer@agc.local", "Organizer@123"),
        ("Faculty", "teacher@agc.local", "Teacher@123"),
        ("Student", "student@agc.local", "Student@123"),
    ]


def _safe_next_url(target):
    """Only follow same-site relative redirects after login."""
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return None


def _login_view():
    if current_user.is_authenticated:
        return redirect(url_for(get_role_dashboard_route(current_user.role)))

    next_url = _safe_next_url(request.values.get("next"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()
        error = None

        if not user or not user.check_password(password):
            error = ("Invalid email or password.", "credentials")
        elif not user.is_active_account:
            error = ("Your account has been blocked by admin.", "account")

        if error:
            message, field = error
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify({"success": False, "message": message, "errors": {field: message}}), 400
            flash(message, "danger")
            return render_template("auth/login.html", demo_accounts=_demo_accounts(), next_url=next_url), 401

        login_user(user, remember=bool(request.form.get("remember")))
        destination = next_url or url_for(get_role_dashboard_route(user.role))
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": True, "redirect": destination})
        return redirect(destination)

    return render_template("auth/login.html", demo_accounts=_demo_accounts(), next_url=next_url)


@app.route("/login", methods=["GET", "POST"])
def login():
    return _login_view()


# Role-specific sign-in URLs all use the same unified sign-in screen.
@app.route("/login/student", methods=["GET", "POST"])
def student_login():
    return _login_view()


@app.route("/login/student-alt", methods=["GET", "POST"])
def student_login_page():
    return _login_view()


@app.route("/faculty/login", methods=["GET", "POST"])
def faculty_login_page():
    return _login_view()


@app.route("/organizer/login", methods=["GET", "POST"])
def organizer_login():
    return _login_view()


@app.route("/organizer/login-alt", methods=["GET", "POST"])
def organizer_login_page():
    return _login_view()


def _hash_reset_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


@app.route("/forgot-password", methods=["GET", "POST"])
@limiter.limit("5 per hour", methods=["POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email","").strip().lower()
        user = User.query.filter_by(email=email).first()
        if user:
            token = secrets.token_urlsafe(32)
            user.reset_token = _hash_reset_token(token)
            user.reset_token_expires = utcnow() + timedelta(hours=1)
            db.session.commit()
            reset_url = url_for("reset_password", token=token, _external=True)
            send_email(email, "CEMS password reset", f"Reset your password:\n{reset_url}")
        flash("If the account exists, a reset link has been generated.", "info")
        return redirect(url_for("login"))
    return render_template("auth/forgot.html")

@app.route("/reset-password/<token>", methods=["GET", "POST"])
@limiter.limit("10 per hour", methods=["POST"])
def reset_password(token):
    user = User.query.filter_by(reset_token=_hash_reset_token(token)).first()
    if user is None or not user.reset_token_expires or user.reset_token_expires < utcnow():
        flash("This password reset link is invalid or has expired.", "danger")
        return redirect(url_for("forgot_password"))
    if request.method == "POST":
        password = request.form.get("password","")
        confirm = request.form.get("confirm_password","")
        if len(password) < 8 or password != confirm:
            flash("Use matching passwords of at least 8 characters.", "danger")
        else:
            user.set_password(password)
            user.reset_token = None
            user.reset_token_expires = None
            db.session.commit()
            flash("Password updated. Please log in.", "success")
            return redirect(url_for("login"))
    return render_template("auth/reset.html")

@app.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return redirect(url_for("landing"))

@app.route("/dashboard")
@login_required
def dashboard():
    role = normalize_role(current_user.role)
    return redirect(url_for(get_role_dashboard_route(current_user.role)))


@app.route("/faculty/dashboard")
@role_required("faculty", "teacher")
def faculty_dashboard():
    today = utcnow().date()
    assigned_ids = _faculty_assigned_event_ids()
    assigned_events = Event.query.filter(Event.id.in_(assigned_ids)).order_by(Event.date.asc()).all() if assigned_ids else []

    registrations = [reg for event in assigned_events for reg in event.registrations]
    stats = {
        "total_assigned": len(assigned_events),
        "upcoming": sum(1 for e in assigned_events if e.date and e.date >= today and e.status == "approved"),
        "completed": sum(1 for e in assigned_events if e.status == "completed"),
        "total_registrations": len(registrations),
        "pending_registrations": sum(1 for r in registrations if r.status == "pending"),
        "approved_students": sum(1 for r in registrations if r.status in ("confirmed", "approved")),
        "total_attendance": sum(1 for r in registrations if r.attended),
    }
    open_events = Event.query.filter(Event.status == "approved", Event.date >= today)
    if assigned_ids:
        open_events = open_events.filter(~Event.id.in_(assigned_ids))
    open_events = open_events.order_by(Event.date.asc()).limit(6).all()
    recent_notices = Notice.query.order_by(Notice.published_at.desc()).limit(3).all()
    return render_template("teacher/dashboard.html", assigned_events=assigned_events, open_events=open_events,
                           recent_notices=recent_notices, today=today, **stats)


@app.route("/faculty/event/<int:event_id>/join", methods=["POST"])
@role_required("faculty", "teacher")
def faculty_join_event(event_id):
    event = Event.query.get_or_404(event_id)
    if event.status != "approved" or (event.date and event.date < utcnow().date()):
        flash("Only upcoming approved events can be coordinated.", "danger")
        return redirect(url_for("faculty_dashboard"))
    if EventFaculty.query.filter_by(faculty_id=current_user.id, event_id=event.id).first():
        flash("You are already coordinating this event.", "info")
    else:
        db.session.add(EventFaculty(event_id=event.id, faculty_id=current_user.id, assigned_by=current_user.id))
        db.session.commit()
        create_notification(event.organizer_id, "Faculty coordinator joined",
                            f"{current_user.name} is now coordinating {event.title}.")
        flash(f"You are now coordinating {event.title}.", "success")
    return redirect(url_for("faculty_dashboard"))


@app.route("/faculty/event/<int:event_id>/leave", methods=["POST"])
@role_required("faculty", "teacher")
def faculty_leave_event(event_id):
    assignment = EventFaculty.query.filter_by(faculty_id=current_user.id, event_id=event_id).first_or_404()
    db.session.delete(assignment)
    db.session.commit()
    flash("You are no longer coordinating this event.", "success")
    return redirect(url_for("faculty_assigned_events"))


@app.route("/teacher/dashboard")
@role_required("faculty", "teacher")
def teacher_dashboard():
    return faculty_dashboard()


@app.route("/faculty/assigned-events")
@role_required("faculty", "teacher")
def faculty_assigned_events():
    assigned = EventFaculty.query.filter_by(faculty_id=current_user.id).all()
    assigned_ids = [row.event_id for row in assigned]
    events = Event.query.filter(Event.id.in_(assigned_ids)).order_by(Event.date.desc()).all() if assigned_ids else []
    return render_template("teacher/assigned_events.html", events=events)


def _faculty_assigned_event_ids():
    return [row.event_id for row in EventFaculty.query.filter_by(faculty_id=current_user.id).all()]


def _faculty_assigned_event(event_id):
    event = Event.query.get(event_id)
    if event is None or not EventFaculty.query.filter_by(faculty_id=current_user.id, event_id=event_id).first():
        return None
    return event


def _faculty_attendance_rows(event):
    registrations = Registration.query.filter(
        Registration.event_id == event.id,
        Registration.status.in_(("approved", "confirmed")),
    ).order_by(Registration.registered_at.asc()).all()
    rows = []
    for registration in registrations:
        attendance = AttendanceRecord.query.filter_by(registration_id=registration.id).first()
        profile = getattr(registration.user, "student_account_profile", None)
        status = (attendance.status if attendance else ("present" if registration.attended else "not_marked")).lower()
        check_in = (attendance.check_in_time if attendance else None) or registration.checkin_time
        rows.append({
            "registration_id": registration.id,
            "student_name": registration.user.name if registration.user else "Unknown student",
            "email": registration.user.email if registration.user else "",
            "roll_no": (profile.roll_no if profile else None) or (registration.user.roll_no if registration.user else ""),
            "course": profile.course if profile else "",
            "department": (profile.department if profile else None) or (registration.user.department if registration.user else ""),
            "semester": profile.semester if profile else "",
            "registration_status": registration.status,
            "attendance_status": status,
            "check_in_time": check_in.isoformat() if check_in else None,
        })
    return rows


def _attendance_stats(rows):
    counts = {status: sum(1 for row in rows if row["attendance_status"] == status)
              for status in ("present", "absent", "late", "not_marked")}
    total = len(rows)
    counts.update({
        "total": total,
        "attendance_percentage": round((counts["present"] + counts["late"]) * 100 / total) if total else 0,
    })
    return counts


@app.route("/teacher/attendance")
@role_required("faculty", "teacher")
def teacher_attendance():
    event_ids = _faculty_assigned_event_ids()
    events = Event.query.filter(Event.id.in_(event_ids)).order_by(Event.date.desc()).all() if event_ids else []
    selected_id = request.args.get("event_id", type=int)
    selected_event = _faculty_assigned_event(selected_id) if selected_id else None
    return render_template("teacher/attendance.html", events=events, selected_event=selected_event)


@app.route("/api/teacher/attendance")
@role_required("faculty", "teacher")
def teacher_attendance_events_api():
    event_ids = _faculty_assigned_event_ids()
    events = Event.query.filter(Event.id.in_(event_ids)).order_by(Event.date.desc()).all() if event_ids else []
    return jsonify({"success": True, "events": [{"id": event.id, "title": event.title} for event in events]})


@app.route("/api/teacher/attendance/<int:event_id>")
@role_required("faculty", "teacher")
def teacher_attendance_api(event_id):
    event = _faculty_assigned_event(event_id)
    if event is None:
        return jsonify({"success": False, "message": "This event is not assigned to your faculty account."}), 403

    rows = _faculty_attendance_rows(event)
    all_stats = _attendance_stats(rows)
    search = request.args.get("search", request.args.get("q", "")).strip().lower()
    status_filter = request.args.get("status", request.args.get("attendance_status", "")).strip().lower()
    filtered = [row for row in rows if (
        not search or search in " ".join((row["student_name"], row["email"], row["roll_no"] or "")).lower()
    ) and (not status_filter or row["attendance_status"] == status_filter)]
    page = max(request.args.get("page", 1, type=int), 1)
    per_page = min(max(request.args.get("per_page", 15, type=int), 1), 100)
    pages = max((len(filtered) + per_page - 1) // per_page, 1)
    page = min(page, pages)
    start = (page - 1) * per_page
    return jsonify({
        "success": True,
        "event": {"id": event.id, "title": event.title, "date": event.date.isoformat() if event.date else None},
        "students": filtered[start:start + per_page],
        "stats": all_stats,
        "total": len(filtered),
        "page": page,
        "pages": pages,
    })


def _save_faculty_attendance(registration, status, method="faculty_manual"):
    now = utcnow()
    attendance = AttendanceRecord.query.filter_by(registration_id=registration.id).first()
    if attendance is None:
        attendance = AttendanceRecord(registration_id=registration.id)
        db.session.add(attendance)
    attendance.status = status
    attendance.method = method
    attendance.recorded_at = now
    attendance.check_in_time = now if status in ("present", "late") else None
    registration.attended = status in ("present", "late")
    registration.checkin_time = attendance.check_in_time
    return attendance


@app.route("/api/teacher/attendance/<int:event_id>/<int:registration_id>/mark", methods=["POST"])
@role_required("faculty", "teacher")
def teacher_mark_attendance_api(event_id, registration_id):
    event = _faculty_assigned_event(event_id)
    if event is None:
        return jsonify({"success": False, "message": "This event is not assigned to your faculty account."}), 403
    registration = Registration.query.filter_by(id=registration_id, event_id=event.id).first_or_404()
    status = (request.get_json(silent=True) or {}).get("status", "").strip().lower()
    if status not in {"present", "absent", "late"}:
        return jsonify({"success": False, "message": "Choose Present, Absent, or Late."}), 400
    _save_faculty_attendance(registration, status)
    db.session.commit()
    return jsonify({"success": True, "message": f"Attendance marked {status}.", "status": status})


@app.route("/api/teacher/attendance/<int:event_id>/bulk", methods=["POST"])
@role_required("faculty", "teacher")
def teacher_bulk_attendance_api(event_id):
    event = _faculty_assigned_event(event_id)
    if event is None:
        return jsonify({"success": False, "message": "This event is not assigned to your faculty account."}), 403
    status = (request.get_json(silent=True) or {}).get("status", "present").strip().lower()
    if status not in {"present", "absent", "late"}:
        return jsonify({"success": False, "message": "Choose Present, Absent, or Late."}), 400
    registrations = Registration.query.filter(
        Registration.event_id == event.id,
        Registration.status.in_(("approved", "confirmed")),
    ).all()
    for registration in registrations:
        _save_faculty_attendance(registration, status)
    db.session.commit()
    return jsonify({"success": True, "message": f"Attendance updated for {len(registrations)} students.", "updated": len(registrations)})


@app.route("/teacher/attendance/export")
@role_required("faculty", "teacher")
def teacher_attendance_export():
    event_id = request.args.get("event_id", type=int)
    event = _faculty_assigned_event(event_id) if event_id else None
    if event is None:
        abort(403)
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Student", "Email", "Roll Number", "Department", "Semester", "Registration Status", "Attendance", "Check-in Time"])
    for row in _faculty_attendance_rows(event):
        writer.writerow([row["student_name"], row["email"], row["roll_no"], row["department"], row["semester"], row["registration_status"], row["attendance_status"], row["check_in_time"] or ""])
    return send_file(BytesIO(output.getvalue().encode("utf-8-sig")), mimetype="text/csv", as_attachment=True, download_name=f"attendance-{event.id}.csv")


@app.route("/teacher/assigned-events")
@role_required("faculty", "teacher")
def teacher_assigned_events():
    return faculty_assigned_events()


@app.route("/faculty/event/<int:event_id>")
@app.route("/teacher/event/<int:event_id>")
@role_required("faculty", "teacher")
def teacher_event_details(event_id):
    event = Event.query.get_or_404(event_id)
    assigned = EventFaculty.query.filter_by(faculty_id=current_user.id, event_id=event.id).first()
    if not assigned:
        abort(403)
    registrations = event.registrations
    total_registrations = len(registrations)
    pending_registrations = sum(1 for reg in registrations if reg.status == "pending")
    approved_students = sum(1 for reg in registrations if reg.status in ("confirmed", "approved"))
    attendance_count = sum(1 for reg in registrations if reg.attended)
    certificates_count = sum(1 for reg in registrations if reg.attended)
    return render_template("teacher/event_details.html", event=event, organizer=event.organizer,
                           total_registrations=total_registrations, pending_registrations=pending_registrations,
                           approved_students=approved_students, attendance_count=attendance_count,
                           certificates_count=certificates_count, registrations=registrations)


@app.route("/events")
def events():
    q = request.args.get("q","").strip()
    category = request.args.get("category","").strip()
    status = request.args.get("status","").strip()
    query = Event.query.filter_by(status="approved")
    if q:
        query = query.filter(Event.title.ilike(f"%{q}%"))
    if category:
        query = query.filter_by(category=category)
    today = utcnow().date()
    if status == "upcoming":
        query = query.filter(Event.date >= today)
    elif status == "completed":
        query = query.filter(Event.date < today)
    event_list = query.order_by(Event.date.asc()).all()
    categories = [r[0] for r in db.session.query(Event.category).distinct().all()]
    registration_status_map = {}
    if current_user.is_authenticated:
        registration_status_map = {
            reg.event_id: reg.status for reg in Registration.query.filter_by(user_id=current_user.id).all()
        }
    return render_template("events.html", events=event_list, categories=categories, q=q, category=category, status=status,
                           registration_status_map=registration_status_map)


@app.route("/past-events")
def past_events():
    q = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    venue = request.args.get("venue", "").strip()
    page = request.args.get("page", 1, type=int)
    today = utcnow().date()

    query = Event.query.filter(Event.status.in_(("approved", "completed")), Event.date < today)
    if q:
        query = query.filter(Event.title.ilike(f"%{q}%"))
    if category:
        query = query.filter_by(category=category)
    if venue:
        query = query.filter(Event.venue.ilike(f"%{venue}%"))

    pagination = query.order_by(Event.date.desc()).paginate(page=page, per_page=12, error_out=False)
    categories = [r[0] for r in db.session.query(Event.category).distinct().all()]
    venues = [r[0] for r in db.session.query(Event.venue).distinct().all()]

    results_map = {event.id: bool(event.completion_notes) for event in pagination.items}
    return render_template("past_events.html", events=pagination.items, categories=categories, venues=venues,
                           q=q, category=category, venue=venue, pagination=pagination, results_map=results_map)


@app.route("/past-events/<int:event_id>")
def past_event_detail(event_id):
    event = Event.query.get_or_404(event_id)
    if event.date >= utcnow().date() or event.status not in ("approved", "completed"):
        abort(404)
    regs = [r for r in event.registrations if r.status not in ("cancelled", "rejected")]
    present = sum(1 for r in regs if r.attended)
    summary = SimpleNamespace(
        total=len(regs), present=present, absent=len(regs) - present,
        attendance_percentage=round(present * 100 / len(regs)) if regs else 0,
    )
    return render_template("past_event_detail.html", event=event, summary=summary,
                           results_text=event.completion_notes, gallery=[], documents=[], past_record=None)

@app.route("/events/<int:event_id>")
def event_details(event_id):
    event = Event.query.get_or_404(event_id)
    if event.status != "approved":
        allowed = current_user.is_authenticated and (
            current_user.role == "admin"
            or (normalize_role(current_user.role) == "organizer" and event.organizer_id == current_user.id)
            or (normalize_role(current_user.role) == "faculty" and EventFaculty.query.filter_by(
                faculty_id=current_user.id, event_id=event.id
            ).first() is not None)
        )
        if not allowed:
            abort(404)
    registered = False
    if current_user.is_authenticated:
        registration = Registration.query.filter_by(user_id=current_user.id, event_id=event.id).first()
        registered = registration is not None and registration.status not in ("cancelled", "rejected")
    active_registrations = Registration.query.filter(
        Registration.event_id == event.id,
        Registration.status.in_(("confirmed", "approved", "pending")),
    ).count()
    seats = max((event.capacity or 0) - active_registrations, 0)

    reg_ctx = {"can_register": False, "message": "Registration unavailable", "reason": ""}
    if not current_user.is_authenticated:
        reg_ctx.update(message="Sign in to register", reason="A student account is required to reserve a place.")
    elif normalize_role(current_user.role) != "student":
        reg_ctx.update(message="Student registration only", reason="Sign in with a student account to register for events.")
    elif event.status != "approved":
        reg_ctx.update(message="Event not approved", reason="Registration opens after the event is approved.")
    elif event.date and event.date < utcnow().date():
        reg_ctx.update(message="Event completed", reason="Registration is closed for past events.")
    elif event.registration_deadline and utcnow().date() > event.registration_deadline:
        reg_ctx.update(message="Registration closed", reason="The registration deadline has passed.")
    elif seats <= 0:
        reg_ctx.update(message="Event full", reason="All available places have been reserved.")
    elif registered:
        reg_ctx.update(message="Already registered", reason="This account already has a registration for the event.")
    else:
        reg_ctx.update(can_register=True, message="", reason="")

    return render_template("event_details.html", event=event, registered=registered, seats=seats, reg_ctx=reg_ctx,
                           display_status=event_display_status(event))

def _seats_left(event):
    taken = Registration.query.filter(
        Registration.event_id == event.id,
        Registration.status.in_(("confirmed", "approved", "pending")),
    ).count()
    return max((event.capacity or 0) - taken, 0)


@app.route("/student/dashboard")
@role_required("student")
def student_dashboard():
    today = utcnow().date()
    user_regs = Registration.query.filter_by(user_id=current_user.id).order_by(Registration.registered_at.desc()).all()
    upcoming = Event.query.filter(Event.status == "approved", Event.date >= today).order_by(Event.date).limit(4).all()
    upcoming_registered = [reg.event for reg in user_regs if reg.event and reg.event.date >= today]
    recent_notifications = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).limit(5).all()
    recent_registrations = user_regs[:5]
    registration_status_map = {reg.event_id: reg.status for reg in user_regs if reg.event_id}
    recommended_events = Event.query.filter(Event.status == "approved", Event.date >= today).order_by(Event.date).limit(4).all()
    pending_feedbacks = []
    for reg in user_regs:
        if reg.attended and not Feedback.query.filter_by(registration_id=reg.id).first():
            pending_feedbacks.append(reg)
    past_events = Event.query.filter(Event.status.in_(("approved", "completed")), Event.date < today).order_by(Event.date.desc()).limit(4).all()
    seats_left_map = {event.id: _seats_left(event) for event in upcoming}

    regs = len(user_regs)
    attended = sum(1 for reg in user_regs if reg.attended)
    tickets = sum(1 for reg in user_regs if reg.status == "confirmed")
    student_profile = StudentAccountProfile.query.filter_by(user_id=current_user.id).first()
    certificates_count = attended
    uploaded_images_count = int(bool(student_profile and student_profile.profile_image))

    return render_template(
        "student/dashboard.html",
        upcoming=upcoming,
        regs=regs,
        attended=attended,
        tickets=tickets,
        active_tickets=tickets,
        certificates_count=certificates_count,
        uploaded_images_count=uploaded_images_count,
        upcoming_registered=upcoming_registered,
        recent_notifications=recent_notifications,
        recent_registrations=recent_registrations,
        registration_status_map=registration_status_map,
        recommended_events=recommended_events,
        pending_feedbacks=pending_feedbacks,
        past_events=past_events,
        seats_left_map=seats_left_map,
    )


@app.route("/student/events")
@role_required("student")
def student_events():
    q = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    status = request.args.get("status", "open").strip()
    page = request.args.get("page", 1, type=int)
    today = utcnow().date()

    query = Event.query.filter(Event.status == "approved", Event.date >= today)
    if q:
        query = query.filter(Event.title.ilike(f"%{q}%"))
    if category:
        query = query.filter_by(category=category)

    if status == "full":
        full_event_ids = (
            db.session.query(Registration.event_id)
            .join(Event, Registration.event_id == Event.id)
            .filter(Registration.status.in_(("confirmed", "approved")))
            .group_by(Registration.event_id, Event.capacity)
            .having(db.func.count(Registration.id) >= Event.capacity)
        )
        query = query.filter(Event.id.in_(full_event_ids))

    pagination = query.order_by(Event.date.asc()).paginate(page=page, per_page=12, error_out=False)
    categories = [r[0] for r in db.session.query(Event.category).distinct().all()]

    items = []
    for event in pagination.items:
        registered_count = Registration.query.filter_by(event_id=event.id).count()
        is_registered = Registration.query.filter_by(user_id=current_user.id, event_id=event.id).first() is not None
        items.append({
            "event": event,
            "is_registered": is_registered,
            "seats_available": max(0, event.capacity - registered_count),
        })

    return render_template("student/events.html", events=items, categories=categories, q=q, category=category, status=status, pagination=pagination)


@app.route("/student/feedback")
@role_required("student")
def student_feedback_list():
    regs = Registration.query.filter_by(user_id=current_user.id).order_by(Registration.registered_at.desc()).all()
    pending_regs = [reg for reg in regs if reg.attended and not Feedback.query.filter_by(registration_id=reg.id).first()]
    submitted_regs = [reg for reg in regs if Feedback.query.filter_by(registration_id=reg.id).first()]
    return render_template("student/feedback_list.html", pending_regs=pending_regs, submitted_regs=submitted_regs)

def _registration_eligibility(event, user):
    """Decide whether `user` may register for `event`; returns data the registration page renders."""
    existing = Registration.query.filter(
        Registration.user_id == user.id, Registration.event_id == event.id,
        Registration.status.notin_(("cancelled", "rejected")),
    ).first()

    def result(eligible, reason="", message="", status="info"):
        return {"eligible": eligible, "reason": reason, "message": message, "status": status}

    if existing:
        return result(False, "already_registered", "You are already registered for this event.", "success"), existing
    if event.status != "approved":
        return result(False, "event_not_approved", "Registration opens after the event is approved.", "warning"), None
    today = utcnow().date()
    if event.date and event.date < today:
        return result(False, "event_past", "This event has already taken place.", "info"), None
    if event.registration_deadline and today > event.registration_deadline:
        return result(False, "deadline_passed", "The registration deadline has passed.", "warning"), None
    if _seats_left(event) <= 0:
        return result(False, "event_full", "All seats for this event are taken.", "warning"), None
    return result(True), None


@app.route("/events/<int:event_id>/register", methods=["GET", "POST"])
@role_required("student")
def register_event(event_id):
    event = Event.query.get_or_404(event_id)
    eligibility, existing = _registration_eligibility(event, current_user)
    if request.method == "POST":
        if not eligibility["eligible"]:
            flash(eligibility["message"], "danger" if existing is None else "info")
            if existing:
                return redirect(url_for("ticket", registration_id=existing.id))
            return redirect(url_for("event_details", event_id=event.id))
        if not request.form.get("terms_accepted"):
            flash("Please accept the event rules and cancellation policy to continue.", "danger")
            return redirect(url_for("register_event", event_id=event.id))
        if event.fee and event.fee > 0:
            return redirect(url_for("demo_payment", event_id=event.id))
        ticket = "AGC-" + secrets.token_hex(4).upper()
        reg = Registration(ticket_code=ticket, user_id=current_user.id, event_id=event.id,
                           status="confirmed", payment_status="free")
        db.session.add(reg)
        db.session.commit()
        create_notification(current_user.id, "Registration confirmed",
                            f"You are registered for {event.title}. Ticket: {ticket}")
        create_notification(event.organizer_id, "New registration",
                            f"{current_user.name} registered for {event.title}.")
        flash("Registration successful. Your digital ticket is ready.", "success")
        return redirect(url_for("ticket", registration_id=reg.id))
    return render_template("student/register_event.html", event=event, eligibility=eligibility, existing_registration=existing)

@app.route("/student/registrations")
@role_required("student")
def my_registrations():
    regs = Registration.query.filter_by(user_id=current_user.id).order_by(Registration.registered_at.desc()).all()
    return render_template("student/registrations.html", registrations=regs)

@app.route("/student/tickets")
@role_required("student")
def my_tickets():
    regs = Registration.query.filter_by(user_id=current_user.id, status="confirmed").order_by(Registration.registered_at.desc()).all()
    return render_template("student/tickets.html", registrations=regs)

@app.route("/ticket/<int:registration_id>")
@login_required
def ticket(registration_id):
    reg = Registration.query.get_or_404(registration_id)
    if reg.user_id != current_user.id and not (
        current_user.role == "admin"
        or (normalize_role(current_user.role) == "organizer" and reg.event.organizer_id == current_user.id)
    ):
        abort(403)
    return render_template("student/ticket.html", reg=reg)

@app.route("/ticket/<int:registration_id>/qr")
@login_required
def ticket_qr(registration_id):
    reg = Registration.query.get_or_404(registration_id)
    if reg.user_id != current_user.id and not (
        current_user.role == "admin"
        or (normalize_role(current_user.role) == "organizer" and reg.event.organizer_id == current_user.id)
    ):
        abort(403)
    img = qrcode.make(reg.ticket_code)
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png", download_name=f"{reg.ticket_code}.png")


@app.route("/ticket/<int:registration_id>/download")
@login_required
def ticket_download(registration_id):
    reg = Registration.query.get_or_404(registration_id)
    if reg.user_id != current_user.id and not (
        current_user.role == "admin"
        or (normalize_role(current_user.role) == "organizer" and reg.event.organizer_id == current_user.id)
    ):
        abort(403)

    qr_buffer = BytesIO()
    qrcode.make(reg.ticket_code).save(qr_buffer, format="PNG")
    qr_buffer.seek(0)
    pdf_buffer = BytesIO()
    document = canvas.Canvas(pdf_buffer, pagesize=A4)
    width, height = A4
    document.setTitle(f"CEMS ticket {reg.ticket_code}")
    document.setFont("Helvetica-Bold", 24)
    document.drawString(64, height - 80, "CEMS EVENT PASS")
    document.setFont("Helvetica-Bold", 18)
    document.drawString(64, height - 135, reg.event.title)
    document.setFont("Helvetica", 12)
    details = [
        f"Attendee: {reg.user.name}",
        f"Date: {reg.event.date.strftime('%d %B %Y') if reg.event.date else 'To be announced'}",
        f"Time: {reg.event.start_time} - {reg.event.end_time}",
        f"Venue: {reg.event.venue}",
        f"Registration: {reg.status.title()}",
        f"Ticket code: {reg.ticket_code}",
    ]
    for index, detail in enumerate(details):
        document.drawString(64, height - 175 - index * 24, detail)
    document.drawImage(ImageReader(qr_buffer), width - 190, height - 345, width=120, height=120)
    document.setFont("Helvetica", 9)
    document.drawString(64, 54, "Present this pass at the event check-in desk.")
    document.save()
    pdf_buffer.seek(0)
    return send_file(pdf_buffer, mimetype="application/pdf", as_attachment=True, download_name=f"ticket-{reg.ticket_code}.pdf")

@app.route("/student/notifications")
@role_required("student")
def student_notifications():
    return _notification_page("account/notifications.html")


@app.route("/notifications")
@login_required
def user_notifications():
    """Notification inbox for any role (the bell icon in the header points here)."""
    if normalize_role(current_user.role) == "admin":
        return redirect(url_for("admin_notifications"))
    return _notification_page("account/notifications.html")


@app.route("/profile")
@login_required
def profile_home():
    role = normalize_role(current_user.role)
    target = {"student": "profile", "organizer": "organizer_profile", "faculty": "faculty_profile"}.get(role)
    return redirect(url_for(target) if target else url_for(get_role_dashboard_route(role)))

def _ensure_account_profile(user):
    if normalize_role(user.role) == "student":
        profile = user.student_account_profile
        if profile is None:
            profile = StudentAccountProfile(
                user=user,
                student_id=user.roll_no or f"AGC-STU-{user.id:05d}",
                roll_no=user.roll_no or "",
                department=user.department or "",
            )
            db.session.add(profile)
            db.session.commit()
        return profile
    if normalize_role(user.role) == "organizer":
        profile = user.organizer_account_profile
        if profile is None:
            profile = OrganizerAccountProfile(
                user=user,
                employee_id=f"AGC-ORG-{user.id:05d}",
                department=user.department or "",
            )
            db.session.add(profile)
            db.session.commit()
        return profile
    profile = user.faculty_account_profile
    if profile is None:
        profile = FacultyAccountProfile(
            user=user,
            employee_id=f"AGC-FAC-{user.id:05d}",
            department=user.department or "",
            faculty_role="Faculty Member",
            academic_session=ACADEMIC_SESSIONS[-1],
        )
        db.session.add(profile)
        db.session.commit()
    return profile


@app.route("/student/profile", methods=["GET", "POST"])
@role_required("student")
def profile():
    student_profile = _ensure_account_profile(current_user)
    if request.method == "POST":
        current_user.name = request.form.get("name", "").strip() or current_user.name
        current_user.mobile = request.form.get("mobile", "").strip()
        current_user.department = request.form.get("department", "").strip()
        current_user.roll_no = request.form.get("roll_no", "").strip()
        student_profile.roll_no = current_user.roll_no
        student_profile.department = current_user.department
        student_profile.semester = request.form.get("semester", "").strip()
        graduation_year = request.form.get("graduation_year", "").strip()
        student_profile.graduation_year = int(graduation_year) if graduation_year.isdigit() else None
        student_profile.linkedin_url = request.form.get("linkedin_url", "").strip()
        student_profile.github_url = request.form.get("github_url", "").strip()
        student_profile.interests = request.form.get("interests", "").strip()
        student_profile.bio = request.form.get("bio", "").strip()

        upload, new_image, photo_error = _prepare_profile_photo()
        if photo_error:
            flash(photo_error, "danger")
            return redirect(url_for("profile"))
        old_image = student_profile.profile_image
        if new_image:
            student_profile.profile_image = new_image
            try:
                _store_profile_photo(upload, new_image)
                db.session.commit()
            except Exception:
                db.session.rollback()
                _delete_profile_photo(new_image)
                raise
            if old_image:
                _delete_profile_photo(old_image)
        else:
            db.session.commit()
        flash("Profile updated.", "success")
        return redirect(url_for("profile"))

    registrations = Registration.query.filter_by(user_id=current_user.id).order_by(Registration.registered_at.desc()).all()
    attended = [registration for registration in registrations if registration.attended]
    upcoming = [registration for registration in registrations if registration.event and registration.event.date >= utcnow().date()]
    volunteer_records = Volunteer.query.filter_by(email=current_user.email).order_by(Volunteer.id.desc()).all()
    return render_template(
        "account/profile.html",
        role="student",
        profile=student_profile,
        registrations=registrations,
        attended_registrations=attended,
        upcoming_registrations=upcoming,
        volunteer_records=volunteer_records,
    )


@app.route("/student/resume-export")
@role_required("student")
def student_resume_export():
    registrations = Registration.query.filter_by(user_id=current_user.id, attended=True).order_by(Registration.registered_at.desc()).all()
    profile = _ensure_account_profile(current_user)
    volunteer_records = Volunteer.query.filter_by(email=current_user.email).order_by(Volunteer.id.desc()).all()
    lines = [
        f"{current_user.name} | Campus Event Participation",
        f"Student ID: {profile.student_id}",
        f"Department: {profile.department or current_user.department or 'Not set'}",
        "",
        "Verified event participation:",
    ]
    lines.extend(f"- {registration.event.title} ({registration.event.date})" for registration in registrations if registration.event)
    if not registrations:
        lines.append("- No verified event attendance recorded yet.")
    if volunteer_records:
        lines.extend(["", "Volunteer roles:"])
        lines.extend(
            f"- {record.task or 'Volunteer'} for {record.name} ({record.status})"
            for record in volunteer_records
        )
        lines.append("Volunteer hours are not recorded by the current deployment.")
    return send_file(
        BytesIO("\n".join(lines).encode("utf-8")),
        mimetype="text/plain; charset=utf-8",
        as_attachment=True,
        download_name="cems-activity-summary.txt",
    )


@app.route("/student/certificates")
@role_required("student")
def student_certificates():
    registrations = Registration.query.filter_by(user_id=current_user.id, attended=True).order_by(Registration.registered_at.desc()).all()
    certificates = [(_certificate_info(r), r, r.event) for r in registrations]
    return render_template("student/certificates.html", registrations=registrations, certificates=certificates)


def _update_staff_profile(profile, redirect_endpoint):
    """Shared handler for the organizer/faculty 'Update Profile' form."""
    name = request.form.get("name", "").strip()
    if not name:
        flash("Full name cannot be empty.", "danger")
        return redirect(url_for(redirect_endpoint))
    upload, new_image, photo_error = _prepare_profile_photo()
    if photo_error:
        flash(photo_error, "danger")
        return redirect(url_for(redirect_endpoint))
    current_user.name = name
    current_user.mobile = request.form.get("mobile", "").strip()
    current_user.department = request.form.get("department", "").strip()
    profile.department = current_user.department
    profile.designation = request.form.get("designation", "").strip()
    profile.bio = request.form.get("bio", "").strip()
    old_image = profile.profile_image
    if new_image:
        profile.profile_image = new_image
    try:
        if new_image:
            _store_profile_photo(upload, new_image)
        db.session.commit()
    except Exception:
        db.session.rollback()
        _delete_profile_photo(new_image)
        raise
    if new_image and old_image:
        _delete_profile_photo(old_image)
    flash("Profile updated.", "success")
    return redirect(url_for(redirect_endpoint))


@app.route("/organizer/profile", methods=["GET", "POST"])
@role_required("organizer")
def organizer_profile():
    profile = _ensure_account_profile(current_user)
    if request.method == "POST":
        return _update_staff_profile(profile, "organizer_profile")
    events = Event.query.filter_by(organizer_id=current_user.id).order_by(Event.date.desc()).all()
    event_ids = [event.id for event in events]
    sponsors = Sponsor.query.filter(Sponsor.event_id.in_(event_ids)).order_by(Sponsor.id.desc()).all() if event_ids else []
    volunteers = Volunteer.query.filter(Volunteer.event_id.in_(event_ids)).order_by(Volunteer.id.desc()).all() if event_ids else []
    judges = Judge.query.filter(Judge.event_id.in_(event_ids)).order_by(Judge.id.desc()).all() if event_ids else []
    registrations = [registration for event in events for registration in event.registrations]
    return render_template(
        "account/profile.html",
        role="organizer",
        profile=profile,
        events=events,
        sponsors=sponsors,
        volunteers=volunteers,
        judges=judges,
        sponsor_total=sum(sponsor.contribution or 0 for sponsor in sponsors),
        total_registrations=len(registrations),
        total_attendance=sum(1 for registration in registrations if registration.attended),
    )


@app.route("/faculty/profile", methods=["GET", "POST"])
@role_required("faculty", "teacher")
def faculty_profile():
    profile = _ensure_account_profile(current_user)
    if request.method == "POST":
        return _update_staff_profile(profile, "faculty_profile")
    assignments = EventFaculty.query.filter_by(faculty_id=current_user.id).all()
    assigned_ids = [assignment.event_id for assignment in assignments]
    events = Event.query.filter(Event.id.in_(assigned_ids)).order_by(Event.date.desc()).all() if assigned_ids else []
    registrations = [registration for event in events for registration in event.registrations]
    return render_template(
        "account/profile.html",
        role="faculty",
        profile=profile,
        events=events,
        total_registrations=len(registrations),
        total_attendance=sum(1 for registration in registrations if registration.attended),
        certificates_generated=sum(1 for registration in registrations if registration.attended),
    )

@app.route("/registration/<int:registration_id>/feedback", methods=["GET", "POST"])
@role_required("student")
def feedback(registration_id):
    reg = Registration.query.get_or_404(registration_id)
    if reg.user_id != current_user.id:
        abort(403)
    existing = Feedback.query.filter_by(registration_id=reg.id).first()
    if request.method == "POST":
        if not reg.attended:
            flash("Feedback opens after you attend the event.", "warning")
            return redirect(url_for("my_registrations"))
        if existing:
            flash("You have already submitted feedback for this event.", "info")
            return redirect(url_for("student_feedback_list"))
        rating = min(max(request.form.get("rating", 5, type=int) or 5, 1), 5)
        db.session.add(Feedback(registration_id=reg.id, rating=rating, comment=request.form.get("comment", "").strip()))
        db.session.commit()
        flash("Thank you for your feedback.", "success")
        return redirect(url_for("student_feedback_list"))
    if not reg.attended and not existing:
        flash("Feedback opens after you attend the event.", "warning")
        return redirect(url_for("my_registrations"))
    return render_template("student/feedback_submit.html", reg=reg, existing=existing)

@app.route("/organizer/dashboard")
@role_required("organizer")
def organizer_dashboard():
    evs = Event.query.filter_by(organizer_id=current_user.id).order_by(Event.date.desc()).all()
    total_reg = sum(len(e.registrations) for e in evs)
    total_att = sum(1 for e in evs for r in e.registrations if r.attended)
    revenue = sum(e.fee * len([r for r in e.registrations if r.payment_status=="paid"]) for e in evs)
    pending = sum(1 for e in evs if e.status in ("pending", "waiting"))
    approved = sum(1 for e in evs if e.status == "approved")
    return render_template("organizer/dashboard.html", events=evs, total_reg=total_reg, total_att=total_att,
                           revenue=revenue, pending=pending, approved=approved)

@app.route("/festival-calendar")
@role_required("organizer")
def festival_calendar():
    festivals = [
        {"name": "Republic Day", "date": datetime(2026, 1, 26).date(), "type": "National Holiday"},
        {"name": "Holi", "date": datetime(2026, 3, 3).date(), "type": "Festival"},
        {"name": "Eid-ul-Fitr", "date": datetime(2026, 3, 20).date(), "type": "Festival"},
        {"name": "Good Friday", "date": datetime(2026, 4, 3).date(), "type": "Holiday"},
        {"name": "Labour Day", "date": datetime(2026, 5, 1).date(), "type": "National Holiday"},
        {"name": "Independence Day", "date": datetime(2026, 8, 15).date(), "type": "National Holiday"},
        {"name": "Ganesh Chaturthi", "date": datetime(2026, 9, 2).date(), "type": "Festival"},
        {"name": "Navratri", "date": datetime(2026, 9, 17).date(), "type": "Festival"},
        {"name": "Diwali", "date": datetime(2026, 11, 8).date(), "type": "Festival"},
        {"name": "Christmas", "date": datetime(2026, 12, 25).date(), "type": "Holiday"},
    ]
    return render_template("organizer/festival_calendar.html", festivals=festivals, year=2026)

@app.route("/kiosk")
@role_required("organizer")
def kiosk():
    return render_template("kiosk/kiosk.html")


@app.route("/api/kiosk/events")
@role_required("organizer")
def kiosk_events_api():
    events = Event.query.filter_by(organizer_id=current_user.id).order_by(Event.date.desc()).all()
    payload = []
    for event in events:
        registrations = Registration.query.filter(
            Registration.event_id == event.id,
            Registration.status.in_(("approved", "confirmed")),
        ).all()
        payload.append({
            "id": event.id,
            "title": event.title,
            "date": event.date.isoformat() if event.date else None,
            "time": f"{event.start_time} - {event.end_time}",
            "venue": event.venue,
            "registered": len(registrations),
            "attended": sum(1 for registration in registrations if registration.attended),
        })
    return jsonify({"success": True, "events": payload})


@app.route("/api/kiosk/stats/<int:event_id>")
@role_required("organizer")
def kiosk_stats_api(event_id):
    event = Event.query.filter_by(id=event_id, organizer_id=current_user.id).first()
    if event is None:
        return jsonify({"success": False, "message": "Event not found."}), 403
    registrations = Registration.query.filter(
        Registration.event_id == event.id,
        Registration.status.in_(("approved", "confirmed")),
    ).all()
    return jsonify({
        "success": True,
        "registered": len(registrations),
        "attended": sum(1 for registration in registrations if registration.attended),
    })


@app.route("/api/kiosk/checkin", methods=["POST"])
@role_required("organizer")
def kiosk_checkin_api():
    payload = request.get_json(silent=True) or {}
    event_id = payload.get("event_id")
    identifier = (payload.get("identifier") or "").strip().upper()
    if not isinstance(event_id, int) or not identifier:
        return jsonify({"success": False, "status": "invalid", "message": "Choose an event and enter a ticket code."}), 400
    event = Event.query.filter_by(id=event_id, organizer_id=current_user.id).first()
    if event is None:
        return jsonify({"success": False, "status": "invalid", "message": "Event not found."}), 403
    registration = Registration.query.filter_by(ticket_code=identifier, event_id=event.id).first()
    if registration is None:
        return jsonify({"success": False, "status": "invalid", "message": "Ticket not found for this event."})
    if registration.attended:
        return jsonify({
            "success": True,
            "status": "duplicate",
            "participant": registration.user.name if registration.user else "Unknown student",
            "ticket_code": registration.ticket_code,
            "checkin_time": registration.checkin_time.isoformat() if registration.checkin_time else None,
            "message": "This ticket has already been checked in.",
        })

    method = "kiosk_qr" if payload.get("method") == "qr_scan" else "kiosk_manual"
    _save_faculty_attendance(registration, "present", method=method)
    create_notification(registration.user_id, "Check-in successful", f"You checked in for {event.title}.")
    db.session.commit()
    return jsonify({
        "success": True,
        "status": "success",
        "participant": registration.user.name if registration.user else "Unknown student",
        "ticket_code": registration.ticket_code,
        "checkin_time": registration.checkin_time.isoformat() if registration.checkin_time else None,
    })

@app.route("/organizer/events/<int:event_id>/participants")
@role_required("organizer")
def organizer_participants(event_id):
    event = Event.query.get_or_404(event_id)
    if event.organizer_id != current_user.id:
        abort(403)
    return render_template("organizer/participants.html", event=event)

@app.route("/organizer/events/<int:event_id>/cancel", methods=["GET","POST"])
@role_required("organizer")
def organizer_cancel_event(event_id):
    event = Event.query.get_or_404(event_id)
    if event.organizer_id != current_user.id:
        abort(403)
    if request.method == "POST":
        reason = request.form.get("reason", "Cancelled by organizer").strip() or "Cancelled by organizer"
        event.status = "cancelled"
        event.change_status = "cancelled"
        create_notification(current_user.id, "Event cancelled", f"{event.title} was marked as cancelled. Reason: {reason}")
        db.session.commit()
        flash("Event marked as cancelled.", "success")
        return redirect(url_for("organizer_dashboard"))
    return render_template("organizer/cancel_event.html", event=event)


@app.route("/organizer/events/<int:event_id>/reschedule", methods=["GET","POST"])
@role_required("organizer")
def organizer_reschedule_event(event_id):
    event = Event.query.get_or_404(event_id)
    if event.organizer_id != current_user.id:
        abort(403)
    if request.method == "POST":
        new_date = request.form.get("date")
        if new_date:
            event.date = datetime.strptime(new_date, "%Y-%m-%d").date()
        if request.form.get("start_time"):
            event.start_time = request.form.get("start_time")
        if request.form.get("end_time"):
            event.end_time = request.form.get("end_time")
        if request.form.get("venue"):
            event.venue = request.form.get("venue")
        event.change_status = "rescheduled"
        db.session.commit()
        flash("Event reschedule updated.", "success")
        return redirect(url_for("organizer_dashboard"))
    return render_template("organizer/reschedule_event.html", event=event)


@app.route("/organizer/events/<int:event_id>/workflow-status")
@role_required("organizer")
def organizer_workflow_status(event_id):
    event = Event.query.get_or_404(event_id)
    if event.organizer_id != current_user.id:
        abort(403)
    activities = list(event.activity_log)
    return render_template("organizer/workflow_status.html", event=event, activities=activities,
                           status_history=[a for a in activities if a.status])


@app.route("/organizer/events/<int:event_id>/generate-certificates")
@role_required("organizer")
def generate_certificates(event_id):
    event = Event.query.get_or_404(event_id)
    if event.organizer_id != current_user.id:
        abort(403)
    regs = Registration.query.filter_by(event_id=event.id, attended=True).all()
    for reg in regs:
        if reg.user and reg.user.role == "student":
            create_notification(reg.user_id, "Certificate ready", f"Your certificate for {event.title} is ready.")
    db.session.commit()
    flash(f"Certificates prepared for {len(regs)} attendee(s).", "success")
    return redirect(url_for("organizer_participants", event_id=event.id))


def _normalize_time(value):
    """Store times as '10:00 AM' (the format used across the app)."""
    value = (value or "").strip()
    for fmt in ("%H:%M", "%I:%M %p", "%I:%M%p", "%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).strftime("%I:%M %p").lstrip("0")
        except ValueError:
            continue
    return None


@app.template_filter("time24")
def time24(value):
    """Convert '10:00 AM' to '10:00' for <input type=time>."""
    for fmt in ("%I:%M %p", "%H:%M", "%I:%M%p"):
        try:
            return datetime.strptime((value or "").strip(), fmt).strftime("%H:%M")
        except ValueError:
            continue
    return ""


def _parse_date(value):
    try:
        return datetime.strptime((value or "").strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def _read_event_form(form, existing=None):
    """Validate the event form; returns (values, errors)."""
    errors = {}
    values = {}
    title = form.get("title", "").strip()
    if not title:
        errors["title"] = "Event name is required."
    values["title"] = title
    category = form.get("category", "").strip()
    if not category:
        errors["category"] = "Choose a category."
    values["category"] = category
    values["event_type"] = "paid" if form.get("event_type") == "paid" else "free"

    event_date = _parse_date(form.get("date"))
    if not event_date:
        errors["date"] = "Enter a valid event date."
    elif existing is None and event_date < utcnow().date():
        errors["date"] = "The event date cannot be in the past."
    values["date"] = event_date

    deadline = _parse_date(form.get("registration_deadline"))
    if form.get("registration_deadline") and not deadline:
        errors["registration_deadline"] = "Enter a valid deadline."
    elif deadline and event_date and deadline > event_date:
        errors["registration_deadline"] = "The deadline must be on or before the event date."
    values["registration_deadline"] = deadline

    start = _normalize_time(form.get("start_time"))
    end = _normalize_time(form.get("end_time"))
    if not start:
        errors["start_time"] = "Enter a valid start time."
    if not end:
        errors["end_time"] = "Enter a valid end time."
    values["start_time"], values["end_time"] = start, end

    venue = form.get("venue", "").strip()
    if not venue:
        errors["venue"] = "Venue is required."
    values["venue"] = venue

    try:
        capacity = int(form.get("capacity", "") or 0)
        if capacity < 1:
            raise ValueError
    except ValueError:
        errors["capacity"] = "Capacity must be a whole number of at least 1."
        capacity = None
    values["capacity"] = capacity

    try:
        fee = float(form.get("fee", "") or 0)
        if fee < 0:
            raise ValueError
    except ValueError:
        errors["fee"] = "Fee must be zero or more."
        fee = 0
    if values["event_type"] == "free":
        fee = 0
    values["fee"] = fee

    start_reg = _parse_date(form.get("registration_start"))
    values["registration_start"] = start_reg
    for key in ("description", "highlights", "rules", "eligibility", "contact_info", "main_guest", "chief_guest",
                "target_department", "target_semester"):
        values[key] = form.get(key, "").strip() or None
    values["description"] = values["description"] or ""
    return values, errors


def _apply_event_values(event, values):
    for key, value in values.items():
        setattr(event, key, value)


@app.route("/organizer/events/create", methods=["GET", "POST"])
@role_required("organizer")
def create_event():
    if request.method == "POST":
        action = request.form.get("action", "submit")
        values, errors = _read_event_form(request.form)
        upload, banner_path, banner_error = _prepare_event_banner()
        if banner_error:
            errors["banner"] = banner_error
        qr_upload, qr_path, qr_error = _prepare_image_upload("payment_qr", "events", 4 * 1024 * 1024, "Payment QR")
        if qr_error:
            errors["payment_qr"] = qr_error
        if errors:
            flash("Please fix the highlighted fields.", "danger")
            return render_template("organizer/create_event.html", errors=errors), 400
        event = Event(organizer_id=current_user.id, banner=banner_path, payment_qr=qr_path,
                      status="draft" if action == "draft" else "pending")
        _apply_event_values(event, values)
        try:
            db.session.add(event)
            db.session.flush()
            log_event_activity(event, "event_created", "Draft saved." if action == "draft" else "Submitted for admin approval.",
                               status=event.status)
            _store_event_banner(upload, banner_path)
            _store_event_banner(qr_upload, qr_path)
            db.session.commit()
        except Exception:
            db.session.rollback()
            for path in (banner_path, qr_path):
                if path:
                    _delete_profile_photo(path.removeprefix("/static/"))
            app.logger.exception("Could not create event")
            flash("Could not create the event. Please try again.", "danger")
            return render_template("organizer/create_event.html", errors={}), 500
        if event.status == "pending":
            create_notification(current_user.id, "Event submitted", f"{event.title} was submitted for admin review.")
            for admin_user in User.query.filter_by(role="admin").all():
                create_notification(admin_user.id, "Event awaiting approval", f"{event.title} was submitted by {current_user.name}.")
            flash("Event submitted for admin approval.", "success")
        else:
            flash("Event draft saved. Submit it for approval when you are ready.", "success")
        return redirect(url_for("organizer_dashboard"))
    return render_template("organizer/create_event.html", errors={})


@app.route("/organizer/events/<int:event_id>/submit", methods=["POST"])
@role_required("organizer")
def submit_event_for_approval(event_id):
    event = Event.query.get_or_404(event_id)
    if event.organizer_id != current_user.id:
        abort(403)
    if event.status != "draft":
        flash("Only draft events can be submitted for approval.", "warning")
        return redirect(url_for("organizer_dashboard"))
    event.status = "pending"
    log_event_activity(event, "event_submitted", "Submitted for admin approval.", previous="draft", status="pending")
    db.session.commit()
    for admin_user in User.query.filter_by(role="admin").all():
        create_notification(admin_user.id, "Event awaiting approval", f"{event.title} was submitted by {current_user.name}.")
    flash("Event submitted for admin approval.", "success")
    return redirect(url_for("organizer_dashboard"))


@app.route("/organizer/events/<int:event_id>/manage", methods=["GET", "POST"])
@role_required("organizer")
def manage_event(event_id):
    event = Event.query.get_or_404(event_id)
    if event.organizer_id != current_user.id:
        abort(403)
    if request.method == "POST":
        values, errors = _read_event_form(request.form, existing=event)
        upload, banner_path, banner_error = _prepare_event_banner()
        if banner_error:
            errors["banner"] = banner_error
        qr_upload, qr_path, qr_error = _prepare_image_upload("payment_qr", "events", 4 * 1024 * 1024, "Payment QR")
        if qr_error:
            errors["payment_qr"] = qr_error
        if errors:
            flash("Could not update event: " + " ".join(errors.values()), "danger")
            return redirect(url_for("manage_event", event_id=event.id))
        _apply_event_values(event, values)
        if banner_path:
            event.banner = banner_path
            _store_event_banner(upload, banner_path)
        if qr_path:
            event.payment_qr = qr_path
            _store_event_banner(qr_upload, qr_path)
        log_event_activity(event, "event_updated", "Event details updated by organizer.")
        db.session.commit()
        flash("Event updated.", "success")
        return redirect(url_for("manage_event", event_id=event.id))
    faculty_members = User.query.filter(User.role.in_(("faculty", "teacher"))).order_by(User.name).all()
    assigned_ids = {row.faculty_id for row in event.faculty_assignments}
    return render_template("organizer/manage_event.html", event=event, faculty_members=faculty_members, assigned_ids=assigned_ids)


@app.route("/organizer/events/<int:event_id>/faculty", methods=["POST"])
@role_required("organizer")
def organizer_assign_faculty(event_id):
    event = Event.query.get_or_404(event_id)
    if event.organizer_id != current_user.id:
        abort(403)
    faculty = db.session.get(User, request.form.get("faculty_id", type=int) or 0)
    if not faculty or normalize_role(faculty.role) != "faculty":
        flash("Choose a valid faculty member.", "danger")
    elif request.form.get("remove"):
        EventFaculty.query.filter_by(event_id=event.id, faculty_id=faculty.id).delete()
        db.session.commit()
        flash(f"{faculty.name} removed from the event.", "success")
    elif EventFaculty.query.filter_by(event_id=event.id, faculty_id=faculty.id).first():
        flash(f"{faculty.name} is already a coordinator.", "info")
    else:
        db.session.add(EventFaculty(event_id=event.id, faculty_id=faculty.id, assigned_by=current_user.id))
        db.session.commit()
        create_notification(faculty.id, "Event assigned", f"You were assigned to coordinate {event.title}.")
        flash(f"{faculty.name} is now coordinating this event.", "success")
    return redirect(url_for("manage_event", event_id=event.id))


@app.route("/organizer/events/<int:event_id>/registrations")
@role_required("organizer")
def organizer_registrations(event_id):
    event = Event.query.get_or_404(event_id)
    if event.organizer_id != current_user.id:
        abort(403)
    registrations = Registration.query.filter_by(event_id=event.id).order_by(Registration.registered_at.desc()).all()
    return render_template("organizer/registrations.html", event=event, registrations=registrations)

@app.route("/organizer/checkin", methods=["GET","POST"])
@role_required("organizer")
def checkin():
    result = None
    if request.method == "POST":
        code = request.form.get("ticket_code","").strip().upper()
        reg = Registration.query.filter_by(ticket_code=code).first()
        if not reg:
            flash("Ticket not found.", "danger")
        elif reg.event.organizer_id != current_user.id:
            flash("This ticket belongs to another organizer.", "danger")
        elif reg.attended:
            flash("Already checked in.", "warning")
            result = reg
        else:
            _save_faculty_attendance(reg, "present", method="organizer_manual")
            create_notification(reg.user_id, "Check-in successful", f"You checked in for {reg.event.title}.")
            db.session.commit()
            flash(f"{reg.user.name} checked in successfully.", "success")
            result = reg
    return render_template("organizer/checkin.html", result=result)

@app.route("/organizer/reports")
@role_required("organizer")
def organizer_reports():
    events = Event.query.filter_by(organizer_id=current_user.id).all()
    total_events = len(events)
    total_reg = sum(len(e.registrations) for e in events)
    total_att = sum(1 for e in events for r in e.registrations if r.attended)
    revenue = sum(e.fee * sum(1 for r in e.registrations if r.payment_status=="paid") for e in events)
    months = _month_labels()
    status_counts = {}
    for e in events:
        status_counts[e.status] = status_counts.get(e.status, 0) + 1
    return render_template(
        "organizer/reports.html", events=events, total_events=total_events, total_reg=total_reg,
        total_att=total_att, revenue=revenue,
        monthly_registrations=[sum(1 for e in events for r in e.registrations
                                   if r.registered_at and (r.registered_at.year, r.registered_at.month) == ym)
                               for ym in months],
        months_ordered=[datetime(y, m, 1).strftime("%b %Y") for y, m in months],
        events_by_status=status_counts,
        revenue_by_event={e.title: e.fee * sum(1 for r in e.registrations if r.payment_status == "paid") for e in events})


@app.route("/payment/<int:event_id>", methods=["GET","POST"])
@role_required("student")
def demo_payment(event_id):
    event = Event.query.get_or_404(event_id)
    if not ALLOW_DEMO_PAYMENTS:
        flash("Online payment is not available. Please contact the event organizer.", "warning")
        return redirect(url_for("event_details", event_id=event.id))
    eligibility, existing = _registration_eligibility(event, current_user)
    if existing:
        return redirect(url_for("ticket", registration_id=existing.id))
    if not eligibility["eligible"]:
        flash(eligibility["message"], "danger")
        return redirect(url_for("event_details", event_id=event.id))
    if not event.fee or event.fee <= 0:
        return redirect(url_for("register_event", event_id=event.id))
    if request.method == "POST":
        ticket = "AGC-" + secrets.token_hex(4).upper()
        reg = Registration(ticket_code=ticket, user_id=current_user.id, event_id=event.id,
                           status="confirmed", payment_status="paid")
        db.session.add(reg)
        db.session.commit()
        create_notification(current_user.id, "Payment successful",
                            f"Demo payment recorded for {event.title}. Ticket: {ticket}")
        create_notification(event.organizer_id, "New registration",
                            f"{current_user.name} registered and paid for {event.title}.")
        flash("Demo payment successful. Your ticket has been generated.", "success")
        return redirect(url_for("ticket", registration_id=reg.id))
    return render_template("student/demo_payment.html", event=event)

@app.route("/certificate/<int:registration_id>")
@login_required
def certificate(registration_id):
    reg = Registration.query.get_or_404(registration_id)
    if reg.user_id != current_user.id and not (
        current_user.role == "admin"
        or (normalize_role(current_user.role) == "organizer" and reg.event.organizer_id == current_user.id)
    ):
        abort(403)
    if not reg.attended:
        flash("Certificate is available after attendance is recorded.", "warning")
        return redirect(url_for("my_registrations"))
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    c.setTitle("CEMS Certificate")
    c.setFont("Helvetica-Bold", 26)
    c.drawCentredString(w/2, h-150, COLLEGE.upper())
    c.setFont("Helvetica-Bold", 30)
    c.drawCentredString(w/2, h-230, "CERTIFICATE OF PARTICIPATION")
    c.setFont("Helvetica", 16)
    c.drawCentredString(w/2, h-300, "This certificate is proudly presented to")
    c.setFont("Helvetica-Bold", 24)
    c.drawCentredString(w/2, h-350, reg.user.name)
    c.setFont("Helvetica", 15)
    c.drawCentredString(w/2, h-410, f"for participating in {reg.event.title}")
    c.drawCentredString(w/2, h-440, f"held at {reg.event.venue} on {reg.event.date.strftime('%d %B %Y')}")
    c.line(100, 120, w-100, 120)
    c.setFont("Helvetica", 11)
    c.drawString(100, 95, "Campus Event Management System")
    c.drawRightString(w-100, 95, reg.ticket_code)
    c.save()
    buf.seek(0)
    return send_file(buf, mimetype="application/pdf", as_attachment=True, download_name=f"certificate-{reg.ticket_code}.pdf")

def _month_labels(count=6):
    today = utcnow().date().replace(day=1)
    months = []
    for i in range(count - 1, -1, -1):
        year, month = today.year, today.month - i
        while month <= 0:
            year, month = year - 1, month + 12
        months.append((year, month))
    return months


def _event_time_bounds(event):
    def parse(value):
        for fmt in ("%I:%M %p", "%H:%M"):
            try:
                return datetime.strptime((value or "").strip(), fmt).time()
            except ValueError:
                continue
        return None
    start, end = parse(event.start_time), parse(event.end_time)
    return (datetime.combine(event.date, start) if start else None,
            datetime.combine(event.date, end) if end else None)


def _event_row(event):
    start, end = _event_time_bounds(event)
    now = utcnow()
    return SimpleNamespace(
        id=event.id, title=event.title, category=event.category, date=event.date, start_time=event.start_time,
        end_time=event.end_time, venue=event.venue, capacity=event.capacity,
        organizer=event.organizer.name if event.organizer else "—",
        registrations=len(event.registrations), status_label=(event.status or "").replace("_", " ").title(),
        is_live=bool(start and end and start <= now <= end),
        url=url_for("event_details", event_id=event.id),
    )


def _build_admin_dashboard():
    now = utcnow()
    today = now.date()
    events = Event.query.all()
    regs = Registration.query.all()
    approved = [e for e in events if e.status == "approved"]
    attended = sum(1 for r in regs if r.attended)
    metrics = SimpleNamespace(
        events=len(events), registrations=len(regs), attendance=attended,
        attendance_rate=round(100 * attended / len(regs)) if regs else 0,
        certificates=attended,
        completed_events=sum(1 for e in events if e.status == "completed" or (e.status == "approved" and e.date < today)),
        live_events=sum(1 for e in approved if e.date == today),
        upcoming_events=sum(1 for e in approved if e.date >= today),
        pending_approvals=sum(1 for e in events if e.status == "pending"),
        students=User.query.filter_by(role="student").count(),
        organizers=User.query.filter_by(role="organizer").count(),
        venues=Venue.query.count(), resources=Venue.query.count(),
        volunteers=Volunteer.query.count() + VolunteerAssignment.query.count(),
    )
    months = _month_labels()

    def in_month(dt, ym):
        return dt is not None and (dt.year, dt.month) == ym

    feedback_by_event = {}
    for e in events:
        ratings = [f.rating for r in e.registrations for f in r.feedbacks]
        if ratings:
            feedback_by_event[e.title[:24]] = round(sum(ratings) / len(ratings), 2)
    categories, venue_use, role_counts = {}, {}, {}
    for e in events:
        categories[e.category] = categories.get(e.category, 0) + 1
        venue_use[e.venue] = venue_use.get(e.venue, 0) + 1
    for a in VolunteerAssignment.query.all():
        if a.role:
            role_counts[a.role.name] = role_counts.get(a.role.name, 0) + 1
    analytics = {
        "months": [datetime(y, m, 1).strftime("%b") for y, m in months],
        "events_by_month": [sum(1 for e in events if in_month(e.created_at, ym)) for ym in months],
        "registrations_trend": [sum(1 for r in regs if in_month(r.registered_at, ym)) for ym in months],
        "attendance_trend": [sum(1 for r in regs if r.attended and in_month(r.registered_at, ym)) for ym in months],
        "certificate_generation": [sum(1 for r in regs if r.attended and in_month(r.registered_at, ym)) for ym in months],
        "event_categories": {"labels": list(categories), "data": list(categories.values())},
        "venue_utilization": [{"label": k, "value": v} for k, v in sorted(venue_use.items(), key=lambda kv: -kv[1])[:6]],
        "volunteer_participation": [{"label": k, "value": v} for k, v in role_counts.items()],
        "event_feedback": {"labels": list(feedback_by_event), "data": list(feedback_by_event.values())},
    }
    venue_conflicts = []
    by_slot = {}
    for e in approved:
        by_slot.setdefault((e.venue, e.date), []).append(e)
    for (venue, day), group in by_slot.items():
        for i, first in enumerate(group):
            for second in group[i + 1:]:
                s1, e1 = _event_time_bounds(first)
                s2, e2 = _event_time_bounds(second)
                if s1 and e1 and s2 and e2 and s1 < e2 and s2 < e1:
                    venue_conflicts.append(SimpleNamespace(
                        event_a=first.title, event_b=second.title, severity="High",
                        time=f"{day.strftime('%d %b')} · {venue}"))
    pending = [e for e in events if e.status == "pending"]
    alerts = []
    if pending:
        alerts.append(SimpleNamespace(severity="warning", title=f"{len(pending)} event(s) awaiting approval",
                                      detail="Review and approve or reject pending events.", url=url_for("admin_events")))
    if venue_conflicts:
        alerts.append(SimpleNamespace(severity="danger", title=f"{len(venue_conflicts)} venue conflict(s)",
                                      detail="Two events overlap at the same venue.", url=url_for("admin_events")))
    activities = [
        SimpleNamespace(type="registration", title="New registration",
                        description=f"{r.user.name} registered for {r.event.title}", actor=r.user.name,
                        timestamp=r.registered_at or now, url=url_for("admin_registrations"))
        for r in sorted(regs, key=lambda r: r.registered_at or now, reverse=True)[:6]
    ]
    quick_actions = [
        SimpleNamespace(label="Review events", description="Approve or reject submitted events", url=url_for("admin_events"), tone="pink"),
        SimpleNamespace(label="Manage venues", description="Add and edit campus venues", url=url_for("admin_venues"), tone="blue"),
        SimpleNamespace(label="View live events", description="See what is happening today", url=url_for("events"), tone="green"),
    ]
    panels = SimpleNamespace(
        pending_approvals=[_event_row(e) for e in pending[:6]],
        today_events=[_event_row(e) for e in approved if e.date == today][:6],
        venue_conflicts=venue_conflicts, resource_conflicts=[], alerts=alerts,
        recent_activities=activities,
    )
    return SimpleNamespace(generated_at=now, metrics=metrics, panels=panels, analytics=analytics,
                           quick_actions=quick_actions)


@app.route("/admin/dashboard")
@role_required("admin")
def admin_dashboard():
    return render_template("admin/dashboard.html", dashboard=_build_admin_dashboard())

@app.route("/admin/users")
@role_required("admin")
def admin_users():
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template("admin/users.html", users=users)

@app.route("/admin/users/<int:user_id>/toggle", methods=["POST"])
@role_required("admin")
def toggle_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash("You cannot block your own admin account.", "warning")
    else:
        user.is_active_account = not user.is_active_account
        db.session.commit()
        flash("User status updated.", "success")
    return redirect(url_for("admin_users"))

@app.route("/admin/events")
@role_required("admin")
def admin_events():
    events = Event.query.order_by(Event.created_at.desc()).all()
    return render_template("admin/events.html", events=events)

@app.route("/admin/events/<int:event_id>/<action>", methods=["POST"])
@role_required("admin")
def event_action(event_id, action):
    event = Event.query.get_or_404(event_id)
    if action not in ("approve","reject"):
        abort(400)
    previous = event.status
    event.status = "approved" if action == "approve" else "rejected"
    if event.status == "approved":
        event.published_at = utcnow()
    log_event_activity(event, f"event_{event.status}", f"{event.title} {event.status} by admin.", previous=previous, status=event.status)
    create_notification(event.organizer_id, f"Event {event.status}", f"{event.title} has been {event.status} by admin.")
    db.session.commit()
    flash(f"Event {event.status}.", "success")
    return redirect(url_for("admin_events"))

@app.route("/admin/registrations")
@role_required("admin")
def admin_registrations():
    registrations = Registration.query.order_by(Registration.registered_at.desc()).all()
    return render_template("admin/registrations.html", registrations=registrations)

@app.route("/admin/reports")
@role_required("admin")
def admin_reports():
    total_revenue = sum(r.event.fee for r in Registration.query.filter_by(payment_status="paid").all())
    feedbacks = Feedback.query.all()
    avg = round(sum(f.rating for f in feedbacks)/len(feedbacks), 2) if feedbacks else 0
    distribution = {i: sum(1 for f in feedbacks if f.rating == i) for i in range(1, 6)}
    words = {}
    for f in feedbacks:
        for word in re.findall(r"[a-z]{5,}", (f.comment or "").lower()):
            words[word] = words.get(word, 0) + 1
    themes = [SimpleNamespace(theme=w, count=c) for w, c in sorted(words.items(), key=lambda kv: -kv[1])[:12]]
    per_event, per_category = {}, {}
    for f in feedbacks:
        event = f.registration.event
        per_event.setdefault(event, []).append(f.rating)
        per_category.setdefault(event.category, []).append(f.rating)
    top_events = sorted(
        (SimpleNamespace(title=e.title, category=e.category, avg_rating=sum(v) / len(v), feedback_count=len(v))
         for e, v in per_event.items()),
        key=lambda t: -t.avg_rating)[:5]
    return render_template("admin/reports.html",
                           total_revenue=total_revenue,
                           avg_rating=avg,
                           users=User.query.count(),
                           events=Event.query.count(),
                           registrations=Registration.query.count(),
                           attendees=Registration.query.filter_by(attended=True).count(),
                           rating_distribution=distribution,
                           total_feedbacks=len(feedbacks),
                           anonymous_count=sum(1 for f in feedbacks if not f.comment),
                           themes=themes,
                           top_events=top_events,
                           category_averages={k: round(sum(v) / len(v), 2) for k, v in per_category.items()})

@app.route("/admin/notifications", methods=["GET","POST"])
@role_required("admin")
def admin_notifications():
    if request.method == "POST":
        users = User.query.filter(User.role != "admin").all()
        title = request.form.get("title", "Campus Update")
        message = request.form.get("message", "")
        selected = request.form.get("audience", "all")
        targets = users if selected == "all" else [u for u in users if u.role == selected]
        for u in targets:
            db.session.add(Notification(user_id=u.id, title=title, message=message))
        db.session.commit()
        flash(f"Notification sent to {len(targets)} users.", "success")
    return _notification_page("admin/notifications.html")


@app.route("/admin/venues", methods=["GET","POST"])
@role_required("admin")
def admin_venues():
    if request.method == "POST":
        name = request.form.get("name","").strip()
        location = request.form.get("location","").strip()
        capacity = int(request.form.get("capacity",100))
        if name:
            db.session.add(Venue(name=name, location=location, capacity=capacity))
            db.session.commit()
            flash("Venue added.", "success")
    venues = Venue.query.order_by(Venue.name).all()
    return render_template("admin/venues.html", venues=venues)


SUPPORT_MODELS = {"volunteers": Volunteer, "judges": Judge, "sponsors": Sponsor}


@app.route("/organizer/support/<module>", methods=["GET", "POST"])
@role_required("organizer")
def organizer_support(module):
    if module not in SUPPORT_MODELS:
        abort(404)
    events = Event.query.filter_by(organizer_id=current_user.id).order_by(Event.date.desc()).all()
    event_map = {e.id: e for e in events}
    if request.method == "POST":
        event_id = request.form.get("event_id", type=int)
        name = request.form.get("name", "").strip()
        if event_id not in event_map:
            flash("Choose one of your events.", "danger")
        elif not name:
            flash("Name is required.", "danger")
        else:
            contact = request.form.get("email", "").strip() or request.form.get("contact", "").strip()
            if module == "volunteers":
                db.session.add(Volunteer(name=name, email=contact, event_id=event_id, task=request.form.get("task", "").strip()))
            elif module == "judges":
                db.session.add(Judge(name=name, email=contact, event_id=event_id, criteria=request.form.get("criteria", "").strip()))
            else:
                try:
                    contribution = max(float(request.form.get("contribution", "0") or 0), 0)
                except ValueError:
                    contribution = None
                if contribution is None:
                    flash("Contribution must be a number.", "danger")
                    return redirect(url_for("organizer_support", module=module))
                db.session.add(Sponsor(name=name, contact=contact, event_id=event_id, contribution=contribution))
            db.session.commit()
            flash(f"{module[:-1].title()} added.", "success")
        return redirect(url_for("organizer_support", module=module))
    model = SUPPORT_MODELS[module]
    rows = model.query.filter(model.event_id.in_(list(event_map))).order_by(model.id.desc()).all() if event_map else []
    return render_template("organizer/support.html", module=module, events=events, rows=rows, event_map=event_map)


@app.route("/organizer/support/<module>/<int:row_id>/delete", methods=["POST"])
@role_required("organizer")
def organizer_support_delete(module, row_id):
    if module not in SUPPORT_MODELS:
        abort(404)
    row = SUPPORT_MODELS[module].query.get_or_404(row_id)
    event = db.session.get(Event, row.event_id) if row.event_id else None
    if not event or event.organizer_id != current_user.id:
        abort(403)
    db.session.delete(row)
    db.session.commit()
    flash(f"{module[:-1].title()} removed.", "success")
    return redirect(url_for("organizer_support", module=module))


@app.route("/health")
def health():
    return {"status":"ok","college":COLLEGE,"time":utcnow().isoformat()}

@app.errorhandler(404)
def not_found(error):
    return render_template("errors/404.html"), 404

@app.errorhandler(403)
def forbidden(error):
    return render_template("errors/403.html"), 403

# ---------------------------------------------------------------------------
# Notifications API + page context
# ---------------------------------------------------------------------------
NOTIFICATION_CATEGORIES = {
    "general": {"label": "General", "icon": "🔔", "color": "primary"},
    "event": {"label": "Events", "icon": "📅", "color": "info"},
    "registration": {"label": "Registrations", "icon": "🎟️", "color": "success"},
    "payment": {"label": "Payments", "icon": "💳", "color": "warning"},
    "system": {"label": "System", "icon": "⚙️", "color": "secondary"},
}


def _notification_page(template):
    notes = (Notification.query
             .filter_by(user_id=current_user.id, is_archived=False)
             .order_by(Notification.created_at.desc()).all())
    return render_template(
        template,
        notifications=notes,
        notification_categories=NOTIFICATION_CATEGORIES,
        unread_notifications=sum(1 for n in notes if not n.is_read),
        read_ids=[n.id for n in notes if n.is_read],
        csrf=generate_csrf(),
    )


@app.route("/api/notifications/<action>", methods=["POST"])
@login_required
def api_notifications(action):
    if action not in ("mark-read", "mark-unread", "archive", "delete"):
        abort(404)
    payload = request.get_json(silent=True) or {}
    query = Notification.query.filter_by(user_id=current_user.id)
    if not payload.get("all"):
        ids = [int(i) for i in payload.get("ids", []) if str(i).isdigit()]
        query = query.filter(Notification.id.in_(ids))
    notes = query.all()
    for note in notes:
        if action == "mark-read":
            note.is_read = True
        elif action == "mark-unread":
            note.is_read = False
        elif action == "archive":
            note.is_archived = True
        else:
            db.session.delete(note)
    db.session.commit()
    return jsonify({"success": True, "count": len(notes)})


# ---------------------------------------------------------------------------
# Admin: user status, exports, dashboard refresh
# ---------------------------------------------------------------------------
@app.route("/admin/users/<int:user_id>/status", methods=["POST"])
@role_required("admin")
def update_user_status(user_id):
    user = User.query.get_or_404(user_id)
    status = request.form.get("status", "")
    if status not in ("active", "suspended", "disabled"):
        abort(400)
    if user.id == current_user.id:
        flash("You cannot change the status of your own admin account.", "warning")
    else:
        user.account_state = status
        user.is_active_account = status == "active"
        db.session.commit()
        flash(f"{user.name} is now {status}.", "success")
    return redirect(url_for("admin_users"))


def _csv_response(filename, header, rows):
    out = StringIO()
    writer = csv.writer(out)
    writer.writerow(header)
    for row in rows:
        # Guard against spreadsheet formula injection from user-supplied text.
        writer.writerow([("'" + c) if isinstance(c, str) and c[:1] in ("=", "+", "-", "@") else c for c in row])
    data = BytesIO(out.getvalue().encode("utf-8-sig"))
    return send_file(data, mimetype="text/csv", as_attachment=True, download_name=filename)


def _registration_rows(registrations):
    return [
        [r.ticket_code, r.user.name, r.user.email, r.event.title, r.status, r.payment_status,
         "Yes" if r.attended else "No", r.registered_at.strftime("%Y-%m-%d %H:%M") if r.registered_at else ""]
        for r in registrations
    ]


_REGISTRATION_HEADER = ["Ticket", "Name", "Email", "Event", "Status", "Payment", "Attended", "Registered at"]


@app.route("/admin/registrations/export")
@role_required("admin")
def export_registrations():
    regs = Registration.query.order_by(Registration.registered_at.desc()).all()
    return _csv_response("registrations.csv", _REGISTRATION_HEADER, _registration_rows(regs))


@app.route("/organizer/events/<int:event_id>/registrations/export")
@role_required("organizer")
def export_event_registrations(event_id):
    event = Event.query.get_or_404(event_id)
    if event.organizer_id != current_user.id:
        abort(403)
    return _csv_response(f"event-{event.id}-registrations.csv", _REGISTRATION_HEADER, _registration_rows(event.registrations))


@app.route("/organizer/reports/export")
@role_required("organizer")
def organizer_reports_export_csv():
    events = Event.query.filter_by(organizer_id=current_user.id).order_by(Event.date.desc()).all()
    rows = [[e.title, e.category, e.date.isoformat(), e.venue, e.status, len(e.registrations),
             sum(1 for r in e.registrations if r.attended),
             e.fee * sum(1 for r in e.registrations if r.payment_status == "paid")] for e in events]
    return _csv_response("organizer-report.csv", ["Event", "Category", "Date", "Venue", "Status",
                                                  "Registrations", "Attended", "Revenue"], rows)


@app.route("/api/admin/dashboard")
@role_required("admin")
def api_admin_dashboard():
    return jsonify({"success": True, "generated_at": utcnow().isoformat()})


@app.route("/api/organizer/registrations/<int:registration_id>/verify-payment", methods=["POST"])
@role_required("organizer")
def api_verify_payment_organizer(registration_id):
    reg = Registration.query.get_or_404(registration_id)
    if reg.event.organizer_id != current_user.id:
        abort(403)
    reg.payment_status = "paid"
    create_notification(reg.user_id, "Payment verified", f"Your payment for {reg.event.title} was verified.")
    flash("Payment marked as verified.", "success")
    return redirect(request.referrer or url_for("organizer_dashboard"))


@app.route("/api/payment/<int:event_id>/<int:registration_id>/verify", methods=["POST"])
@role_required("student")
def api_verify_qr_payment(event_id, registration_id):
    # No payment gateway is wired up, so never report a payment as verified from the client.
    return jsonify({"success": False, "status": "unavailable",
                    "message": "Automatic payment verification is not available. Ask the organizer to verify your payment."}), 501


# ---------------------------------------------------------------------------
# Certificates
# ---------------------------------------------------------------------------
def _certificate_code(reg):
    year = reg.event.date.year if reg.event and reg.event.date else utcnow().year
    return f"CEMS-{year}-{reg.ticket_code}"


def _certificate_info(reg):
    return SimpleNamespace(
        certificate_code=_certificate_code(reg),
        achievement="Certificate of Participation",
        issued_date=reg.checkin_time or reg.event.date,
        verified=bool(reg.attended),
        issuer=None,
    )


@app.route("/certificate/<int:registration_id>/preview")
@login_required
def certificate_preview(registration_id):
    reg = Registration.query.get_or_404(registration_id)
    if reg.user_id != current_user.id and current_user.role != "admin":
        abort(403)
    return redirect(url_for("verify_certificate", code=_certificate_code(reg)))


@app.route("/verify-certificate")
def verify_certificate():
    code = request.args.get("code", "").strip()
    cert = reg = None
    if code:
        ticket = code.rsplit("-", 1)[-1].upper() if code.upper().startswith("CEMS-") else code.upper()
        reg = Registration.query.filter_by(ticket_code=ticket).first()
        if reg and _certificate_code(reg).upper() == code.upper():
            cert = _certificate_info(reg)
        else:
            reg = None
    return render_template("verify_certificate.html", code=code, cert=cert, reg=reg, COLLEGE=COLLEGE)


# ---------------------------------------------------------------------------
# Faculty / teacher event management shortcuts
# ---------------------------------------------------------------------------
def _assigned_event_or_403(event_id):
    event = Event.query.get_or_404(event_id)
    if not EventFaculty.query.filter_by(faculty_id=current_user.id, event_id=event.id).first():
        abort(403)
    return event


@app.route("/teacher/registrations")
@role_required("faculty", "teacher")
def teacher_manage_registrations():
    return redirect(url_for("teacher_attendance"))


@app.route("/teacher/qr-checkin")
@role_required("faculty", "teacher")
def teacher_qr_checkin():
    return redirect(url_for("teacher_attendance"))


@app.route("/teacher/certificates")
@role_required("faculty", "teacher")
def teacher_certificates():
    return redirect(url_for("teacher_assigned_events"))


@app.route("/teacher/reports")
@role_required("faculty", "teacher")
def teacher_reports():
    return redirect(url_for("teacher_attendance_export"))


def _completion_context(event):
    today = utcnow().date()
    regs = [r for r in event.registrations if r.status in ("confirmed", "approved")]
    attended = sum(1 for r in regs if r.attended)
    checklist = [
        {"label": "Event date reached", "checked": bool(event.date and event.date <= today),
         "detail": f"Scheduled for {event.date.strftime('%d %b %Y') if event.date else 'an unspecified date'}."},
        {"label": "Attendance recorded", "checked": attended > 0,
         "detail": f"{attended} of {len(regs)} confirmed participants marked present."},
        {"label": "Participants confirmed", "checked": len(regs) > 0,
         "detail": f"{len(regs)} confirmed registrations."},
    ]
    if event.status == "completed":
        allowed, reason = False, "This event has already been marked as completed."
    elif event.status != "approved":
        allowed, reason = False, "Only approved events can be completed."
    elif not (event.date and event.date <= today):
        allowed, reason = False, "An event can be completed only on or after its scheduled date."
    else:
        allowed, reason = True, ""
    return dict(
        checklist=checklist, all_checklist_complete=all(item["checked"] for item in checklist),
        completion_allowed=allowed, completion_reason=reason,
        readonly_msg="This event is completed. The summary below is read-only." if event.status == "completed" else "",
    )


@app.route("/faculty/event/<int:event_id>/complete", methods=["GET", "POST"])
@role_required("faculty", "teacher")
def faculty_complete_event(event_id):
    event = _assigned_event_or_403(event_id)
    completion = _completion_context(event)
    if request.method == "POST":
        if not completion["completion_allowed"]:
            flash(completion["completion_reason"], "danger")
            return redirect(url_for("faculty_complete_event", event_id=event.id))
        previous = event.status
        event.status = "completed"
        event.completed_by = current_user.id
        event.completed_at = utcnow()
        event.completion_notes = request.form.get("completion_notes", "").strip() or None
        log_event_activity(event, "event_completed", f"Marked completed by {current_user.name}.", previous=previous, status="completed")
        db.session.commit()
        create_notification(event.organizer_id, "Event completed", f"{event.title} was marked completed by {current_user.name}.")
        flash("Event marked as completed.", "success")
        return redirect(url_for("faculty_event_summary", event_id=event.id))
    return render_template("faculty/event_completion.html", event=event, **completion, **_event_summary_context(event))


def _event_summary_context(event):
    regs = list(event.registrations)
    feedbacks = [f for r in regs for f in r.feedbacks]
    ratings = [f.rating for f in feedbacks]
    volunteers = Volunteer.query.filter_by(event_id=event.id).all()
    certs = [SimpleNamespace(certificate_code=_certificate_code(r), registration=r) for r in regs if r.attended]
    stats = SimpleNamespace(
        total_registrations=len(regs),
        approved_students=sum(1 for r in regs if r.status in ("confirmed", "approved")),
        rejected_students=sum(1 for r in regs if r.status in ("rejected", "cancelled")),
        waitlisted=sum(1 for r in regs if r.status == "waitlisted"),
        present=sum(1 for r in regs if r.attended),
        attended=sum(1 for r in regs if r.attended),
        attendance_percentage=round(sum(1 for r in regs if r.attended) * 100 / len(regs)) if regs else 0,
        absent=sum(1 for r in regs if not r.attended),
        late=0,
        certificates_generated=len(certs),
        feedback_responses=len(feedbacks),
        average_feedback_rating=round(sum(ratings) / len(ratings), 2) if ratings else None,
        volunteer_assignments=len(volunteers),
    )
    completer = db.session.get(User, event.completed_by) if event.completed_by else None
    return dict(
        registrations=regs, feedbacks=feedbacks, volunteers=volunteers, certs=certs, stats=stats,
        faculty_list=list(event.faculty_assignments), completed_by_name=completer.name if completer else None,
    )


@app.route("/faculty/event/<int:event_id>/summary")
@role_required("faculty", "teacher")
def faculty_event_summary(event_id):
    event = _assigned_event_or_403(event_id)
    return render_template("faculty/event_summary.html", event=event, **_event_summary_context(event))


@app.route("/faculty/completed-events")
@role_required("faculty", "teacher")
def faculty_completed_events():
    assigned = EventFaculty.query.filter_by(faculty_id=current_user.id).all()
    events = [a.event for a in assigned if a.event.status == "completed"]
    for event in events:
        completer = db.session.get(User, event.completed_by) if event.completed_by else None
        event._completed_by_name = completer.name if completer else None
    return render_template("faculty/completed_events.html", events=events, categories=sorted({e.category for e in events}),
                           category="", date_filter="", sort="newest")


@app.route("/faculty/event/<int:event_id>/report")
@role_required("faculty", "teacher")
def faculty_event_report(event_id):
    _assigned_event_or_403(event_id)
    return past_event_pdf(event_id) if Event.query.get_or_404(event_id).date < utcnow().date() else redirect(
        url_for("faculty_event_summary", event_id=event_id))


@app.route("/admin/events/<int:event_id>/cancellation", methods=["GET", "POST"])
@role_required("admin")
def admin_manage_cancellation(event_id):
    flash("Cancellation requests are applied directly by organizers; nothing to review.", "info")
    return redirect(url_for("admin_events"))


@app.route("/admin/events/<int:event_id>/reschedule", methods=["GET", "POST"])
@role_required("admin")
def admin_manage_reschedule(event_id):
    flash("Reschedules are applied directly by organizers; nothing to review.", "info")
    return redirect(url_for("admin_events"))


# ---------------------------------------------------------------------------
# Organizer: feedback, QR scanner, past event report
# ---------------------------------------------------------------------------
@app.route("/organizer/feedback")
@role_required("organizer")
def organizer_feedback():
    events = Event.query.filter_by(organizer_id=current_user.id).order_by(Event.date.desc()).all()
    rows = [(e, [f for r in e.registrations for f in r.feedbacks]) for e in events]
    return render_template("organizer/event_feedback.html", rows=rows, event=None)


@app.route("/organizer/events/<int:event_id>/feedback")
@role_required("organizer")
def organizer_event_feedback(event_id):
    event = Event.query.get_or_404(event_id)
    if event.organizer_id != current_user.id:
        abort(403)
    rows = [(event, [f for r in event.registrations for f in r.feedbacks])]
    return render_template("organizer/event_feedback.html", rows=rows, event=event)


@app.route("/organizer/qr-scanner")
@role_required("organizer")
def qr_scanner():
    today = utcnow().date()
    events = Event.query.filter(Event.organizer_id == current_user.id, Event.status == "approved") \
        .order_by(Event.date.asc()).all()
    default = next((e for e in events if e.date and e.date >= today), events[-1] if events else None)
    return render_template("organizer/qr_scanner.html", events=events, default_event_id=default.id if default else None)


@app.route("/past-events/<int:event_id>/report.pdf")
def past_event_pdf(event_id):
    event = Event.query.get_or_404(event_id)
    if event.date >= utcnow().date():
        abort(404)
    regs = list(event.registrations)
    ratings = [f.rating for r in regs for f in r.feedbacks]
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    c.setTitle(f"{event.title} report")
    c.setFont("Helvetica-Bold", 20)
    c.drawString(60, h - 80, event.title[:70])
    c.setFont("Helvetica", 12)
    lines = [
        f"Category: {event.category}",
        f"Date: {event.date.strftime('%d %B %Y')}",
        f"Venue: {event.venue}",
        f"Registrations: {len(regs)}",
        f"Attended: {sum(1 for r in regs if r.attended)}",
        f"Average rating: {round(sum(ratings) / len(ratings), 2) if ratings else 'N/A'}",
    ]
    y = h - 120
    for line in lines:
        c.drawString(60, y, line)
        y -= 22
    c.save()
    buf.seek(0)
    return send_file(buf, mimetype="application/pdf", as_attachment=True, download_name=f"event-{event.id}-report.pdf")


# ---------------------------------------------------------------------------
# Organizer: volunteer management
# ---------------------------------------------------------------------------
VOLUNTEER_ROLE_NAMES = ["Registration Desk", "Crowd Management", "Technical Support", "Hospitality", "Photography", "Stage Management"]


def _parse_dt(value):
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M") if value else None
    except ValueError:
        return None


def _own_event_or_403(event_id):
    event = Event.query.get_or_404(event_id)
    if event.organizer_id != current_user.id:
        abort(403)
    return event


def _volunteer_redirect(event_id):
    return redirect(url_for("organizer_volunteer_management", event_id=event_id))


@app.route("/organizer/volunteer-management")
@role_required("organizer")
def organizer_volunteer_management():
    events = Event.query.filter_by(organizer_id=current_user.id).order_by(Event.date.desc()).all()
    event_id = request.args.get("event_id", type=int)
    event = next((e for e in events if e.id == event_id), events[0] if events else None)
    roles = applications = assignments = []
    if event:
        roles = VolunteerRole.query.filter_by(event_id=event.id).order_by(VolunteerRole.id).all()
        role_ids = [r.id for r in roles]
        if role_ids:
            applications = VolunteerApplication.query.filter(VolunteerApplication.role_id.in_(role_ids)).order_by(VolunteerApplication.created_at.desc()).all()
            assignments = VolunteerAssignment.query.filter(VolunteerAssignment.role_id.in_(role_ids)).order_by(VolunteerAssignment.id.desc()).all()
    students = User.query.filter_by(role="student", is_active_account=True).order_by(User.name).all()
    return render_template("organizer/volunteer_management.html", events=events, event=event, roles=roles,
                           applications=applications, assignments=assignments, students=students,
                           default_role_names=VOLUNTEER_ROLE_NAMES)


@app.route("/organizer/events/<int:event_id>/volunteer-roles", methods=["POST"])
@role_required("organizer")
def organizer_create_volunteer_role(event_id):
    event = _own_event_or_403(event_id)
    name = request.form.get("name", "").strip()
    if not name:
        flash("Role name is required.", "danger")
        return _volunteer_redirect(event.id)
    db.session.add(VolunteerRole(
        event_id=event.id, name=name[:120], description=request.form.get("description", "").strip() or None,
        required_count=max(1, min(100, request.form.get("required_count", 1, type=int))),
        active=request.form.get("active", "1") == "1"))
    db.session.commit()
    flash("Volunteer role created.", "success")
    return _volunteer_redirect(event.id)


@app.route("/organizer/volunteer-roles/<int:role_id>", methods=["POST"])
@role_required("organizer")
def organizer_update_volunteer_role(role_id):
    role = VolunteerRole.query.get_or_404(role_id)
    _own_event_or_403(role.event_id)
    role.required_count = max(1, min(100, request.form.get("required_count", role.required_count, type=int)))
    role.active = request.form.get("active", "1") == "1"
    db.session.commit()
    flash("Volunteer role updated.", "success")
    return _volunteer_redirect(role.event_id)


@app.route("/organizer/events/<int:event_id>/volunteers/assign", methods=["POST"])
@role_required("organizer")
def organizer_assign_volunteer(event_id):
    event = _own_event_or_403(event_id)
    role = VolunteerRole.query.filter_by(id=request.form.get("role_id", type=int), event_id=event.id).first()
    student = User.query.filter_by(id=request.form.get("student_id", type=int), role="student").first()
    if not role or not student:
        flash("Choose a valid student and role.", "danger")
        return _volunteer_redirect(event.id)
    db.session.add(VolunteerAssignment(
        role_id=role.id, student_id=student.id, notes=request.form.get("notes", "").strip() or None,
        shift_start=_parse_dt(request.form.get("shift_start")), shift_end=_parse_dt(request.form.get("shift_end"))))
    create_notification(student.id, "Volunteer assignment", f"You were assigned as {role.name} for {event.title}.")
    flash("Volunteer assigned.", "success")
    return _volunteer_redirect(event.id)


@app.route("/organizer/volunteer-applications/<int:application_id>", methods=["POST"])
@role_required("organizer")
def organizer_review_application(application_id):
    application = VolunteerApplication.query.get_or_404(application_id)
    role = application.role
    _own_event_or_403(role.event_id)
    decision = request.form.get("decision")
    if decision == "approve":
        application.status = "approved"
        application.shift_start = _parse_dt(request.form.get("shift_start")) or application.shift_start
        application.shift_end = _parse_dt(request.form.get("shift_end")) or application.shift_end
        db.session.add(VolunteerAssignment(role_id=role.id, student_id=application.student_id,
                                           shift_start=application.shift_start, shift_end=application.shift_end,
                                           notes=application.notes))
    elif decision == "reject":
        application.status = "rejected"
    else:
        abort(400)
    create_notification(application.student_id, "Volunteer application",
                        f"Your application for {role.name} was {application.status}.")
    flash(f"Application {application.status}.", "success")
    return _volunteer_redirect(role.event_id)


@app.route("/organizer/volunteer-assignments/<int:assignment_id>", methods=["POST"])
@role_required("organizer")
def organizer_update_assignment(assignment_id):
    assignment = VolunteerAssignment.query.get_or_404(assignment_id)
    _own_event_or_403(assignment.role.event_id)
    status = request.form.get("status", assignment.status)
    if status not in ("assigned", "confirmed", "present", "completed", "cancelled", "removed"):
        abort(400)
    assignment.status = status
    assignment.shift_start = _parse_dt(request.form.get("shift_start")) or assignment.shift_start
    assignment.shift_end = _parse_dt(request.form.get("shift_end")) or assignment.shift_end
    db.session.commit()
    flash("Assignment updated.", "success")
    return _volunteer_redirect(assignment.role.event_id)


def _rate_limit_auth_routes():
    """Throttle POSTs to login and registration endpoints (brute force / spam)."""
    for rule in app.url_map.iter_rules():
        if "POST" in rule.methods and ("login" in rule.rule or rule.rule.startswith("/register")):
            view = app.view_functions[rule.endpoint]
            if not getattr(view, "_auth_limited", False):
                limited = limiter.limit("10 per minute", methods=["POST"])(view)
                limited._auth_limited = True
                app.view_functions[rule.endpoint] = limited


_rate_limit_auth_routes()

with app.app_context():
    seed_data()

if __name__ == "__main__":
    app.run(debug=_env_flag("FLASK_DEBUG", False), port=int(os.getenv("PORT", 5001)))
