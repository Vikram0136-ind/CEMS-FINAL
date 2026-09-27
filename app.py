
from datetime import datetime, timedelta
import csv
from io import BytesIO
from io import StringIO
from functools import wraps
import os
import secrets
from types import SimpleNamespace
from uuid import uuid4
import qrcode
from dotenv import load_dotenv
from flask import Flask, render_template, redirect, url_for, request, flash, send_file, abort, jsonify, session
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_sqlalchemy import SQLAlchemy
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from markupsafe import Markup, escape

from cems.extensions import csrf

load_dotenv()

app = Flask(__name__)


def event_banner_url(event):
    if not event:
        return ""
    banner = getattr(event, "banner", None)
    if banner:
        return banner
    return "/static/images/default-event.jpg"


def event_image_url(event):
    return event_banner_url(event)


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
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-change-me")
app.config["WTF_CSRF_ENABLED"] = True
app.config["WTF_CSRF_TIME_LIMIT"] = 3600
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
db_url = os.getenv("DATABASE_URL", "sqlite:///cems.db")
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024

app.jinja_env.globals["event_banner_url"] = event_banner_url
app.jinja_env.globals["event_image_url"] = event_image_url


@app.template_filter("nl2br")
def nl2br(value):
    return Markup("<br>".join(escape(line) for line in str(value or "").splitlines()))

csrf.init_app(app)
db = SQLAlchemy(app)
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

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

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
    academic_session = db.Column(db.String(20), nullable=False)
    profile_image = db.Column(db.String(255))
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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    organizer = db.relationship("User", backref="organized_events")

class EventFaculty(db.Model):
    __tablename__ = "event_faculty"
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("event.id"), nullable=False)
    faculty_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    assigned_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    assigned_at = db.Column(db.DateTime, default=datetime.utcnow)
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
    marked_at = db.Column(db.DateTime, default=datetime.utcnow)

class AttendanceRecord(db.Model):
    __tablename__ = "attendance_record"
    id = db.Column(db.Integer, primary_key=True)
    registration_id = db.Column(db.Integer, db.ForeignKey("registration.id"), unique=True, nullable=False)
    status = db.Column(db.String(30), default="present")
    method = db.Column(db.String(30), default="manual")
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow)
    check_in_time = db.Column(db.DateTime)

class DigitalCertificate(db.Model):
    __tablename__ = "digital_certificate"
    id = db.Column(db.Integer, primary_key=True)
    registration_id = db.Column(db.Integer, db.ForeignKey("registration.id"), nullable=False)
    file_name = db.Column(db.String(200))
    issued_at = db.Column(db.DateTime, default=datetime.utcnow)
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
    registered_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship("User", backref="registrations")
    event = db.relationship("Event", backref="registrations")
    feedbacks = db.relationship("Feedback", backref="registration", cascade="all, delete-orphan")

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    title = db.Column(db.String(180), nullable=False)
    message = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship("User", backref="notifications")

class Feedback(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    registration_id = db.Column(db.Integer, db.ForeignKey("registration.id"), nullable=False)
    rating = db.Column(db.Integer, nullable=False)
    comment = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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
        "agc_profile": AGC_PROFILE,
        "agc_updates": AGC_UPDATES,
        "now": datetime.utcnow,
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

def seed_data():
    db.create_all()

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
            db.session.add(user)
        user.name = user_data["name"]
        user.role = user_data["role"]
        user.department = user_data["department"]
        user.roll_no = user_data.get("roll_no") or user.roll_no
        user.mobile = user_data.get("mobile") or user.mobile
        user.is_active_account = True
        user.set_password(user_data["password"])

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
        for title, cat, typ, y, m, d, st, et, venue, cap, fee in sample:
            e = Event(title=title, category=cat, event_type=typ, date=datetime(y,m,d).date(),
                      start_time=st, end_time=et, venue=venue,
                      description=f"{title} is a campus event at {COLLEGE}, designed for students, faculty, clubs and invited guests to learn, participate, collaborate and showcase talent. This event features industry experts, peer learning, and hands-on experience.",
                      highlights="Student participation\nIndustry interaction\nCompetitions & activities\nNetworking & learning\nCertificates\nRefreshments",
                      capacity=cap, registration_deadline=datetime(y,m,d).date()-timedelta(days=2),
                      fee=fee, status="approved", organizer_id=organizer.id)
            db.session.add(e)
        db.session.flush()

        assigned_events = Event.query.order_by(Event.date.asc()).limit(3).all()
        for event in assigned_events:
            db.session.add(EventFaculty(event_id=event.id, faculty_id=teacher.id, assigned_by=admin.id))
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


@app.route("/notices")
def notices():
    published_at = datetime.utcnow()
    notice_rows = [
        SimpleNamespace(
            id=index + 1,
            title=title,
            category="Campus Announcement",
            description=title,
            published_at=published_at - timedelta(days=index),
            image=None,
            event=None,
            attachment=None,
        )
        for index, title in enumerate(AGC_NOTICES)
    ]
    return render_template("notices.html", notices=notice_rows)


@app.route("/notices/<int:notice_id>")
def board_notice_detail(notice_id):
    if notice_id < 1 or notice_id > len(AGC_NOTICES):
        abort(404)
    title = AGC_NOTICES[notice_id - 1]
    notice = SimpleNamespace(
        id=notice_id,
        title=title,
        category="Campus Announcement",
        description=title,
        published_at=datetime.utcnow() - timedelta(days=notice_id - 1),
        image=None,
        event=None,
        attachment=None,
    )
    return render_template("notice_detail.html", notice=notice)


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


def _registration_success(login_endpoint, message):
    redirect_url = url_for(login_endpoint)
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"success": True, "message": message, "redirect": redirect_url})
    flash(message, "success")
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
        if role == "student" and not mobile:
            errors["mobile"] = "Phone number is required."
        elif mobile and len(mobile.replace("+", "").replace(" ", "")) < 10:
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
            organizer_type = (payload.get("organizer_type") or "").strip()
            if not organizer_type:
                errors["organizer_type"] = "Select an organizer type."
        else:
            employee_id = (payload.get("employee_id") or "").strip()
            faculty_role = (payload.get("faculty_role") or "").strip()
            academic_session = (payload.get("academic_session") or "").strip()
            if not employee_id:
                errors["employee_id"] = "Faculty ID is required."
            if not faculty_role:
                errors["faculty_role"] = "Select a faculty role."
            if academic_session not in ACADEMIC_SESSIONS:
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
            if not batch:
                errors["batch"] = "Batch is required."
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
            batch=(payload.get("batch") or "").strip(),
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
        return _registration_success("student_login", "Student account created successfully. Please sign in.")
    return render_template("auth/student_register.html", today_iso=datetime.utcnow().date().isoformat(), academic_sessions=ACADEMIC_SESSIONS)


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
        return _registration_success("organizer_login", "Organizer account created successfully. Please sign in.")
    return render_template("auth/organizer_register.html", today_iso=datetime.utcnow().date().isoformat(), academic_sessions=ACADEMIC_SESSIONS)


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
            academic_session=(payload.get("academic_session") or "").strip(),
            profile_image=profile_image,
        ))
        try:
            _store_profile_photo(upload, profile_image)
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            _delete_profile_photo(profile_image)
            return jsonify({"success": False, "errors": {"account": "An account with this email or faculty ID already exists."}}), 400
        return _registration_success("faculty_login_page", "Faculty account created successfully. Please sign in.")
    return render_template("auth/faculty_register.html", today_iso=datetime.utcnow().date().isoformat(), academic_sessions=ACADEMIC_SESSIONS, faculty_roles=FACULTY_ROLES)


def _login_for_role(expected_role=None, template="auth/login.html"):
    seed_data()

    if current_user.is_authenticated:
        return redirect(url_for(get_role_dashboard_route(current_user.role)))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()
        error = None

        if not user or not user.check_password(password):
            error = ("Invalid email or password.", "credentials")
        elif not user.is_active_account:
            error = ("Your account has been blocked by admin.", "account")
        elif expected_role and normalize_role(user.role) != normalize_role(expected_role):
            error = (f"This account cannot sign in through the {expected_role} portal.", "role")

        if error:
            message, field = error
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify({"success": False, "message": message, "errors": {field: message}}), 400
            flash(message, "danger")
            return render_template(template)

        login_user(user, remember=bool(request.form.get("remember")))
        destination = url_for(get_role_dashboard_route(user.role))
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": True, "redirect": destination})
        return redirect(destination)

    return render_template(template)


@app.route("/login/student", methods=["GET", "POST"])
def student_login():
    return _login_for_role("student", "auth/student_login.html")


@app.route("/faculty/login", methods=["GET", "POST"])
def faculty_login_page():
    return _login_for_role("faculty", "auth/faculty_login.html")


@app.route("/organizer/login", methods=["GET", "POST"])
def organizer_login():
    return _login_for_role("organizer", "auth/organizer_login.html")


@app.route("/organizer/login-alt", methods=["GET", "POST"])
def organizer_login_page():
    return _login_for_role("organizer", "auth/organizer_login.html")


@app.route("/login/student-alt", methods=["GET", "POST"])
def student_login_page():
    return _login_for_role("student", "auth/student_login.html")
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        mobile = request.form.get("mobile", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        role = request.form.get("role", "student")
        department = request.form.get("department", "").strip()
        roll_no = request.form.get("roll_no", "").strip()

        # Required fields
        if not all([name, email, password]):
            flash(
                "Name, email and password are required.",
                "danger"
            )
            return render_template("auth/register.html")

        # Confirm password
        if password != confirm:
            flash(
                "Passwords do not match.",
                "danger"
            )
            return render_template("auth/register.html")

        # Minimum password length
        if len(password) < 8:
            flash(
                "Password must be at least 8 characters.",
                "danger"
            )
            return render_template("auth/register.html")

        # Check existing account
        if User.query.filter_by(email=email).first():
            flash(
                "An account with this email already exists.",
                "danger"
            )
            return render_template("auth/register.html")

        # Allowed roles
        if role not in ("student", "organizer"):
            role = "student"

        # Create new user
        user = User(
            name=name,
            email=email,
            mobile=mobile,
            role=role,
            department=department,
            roll_no=roll_no
        )

        # Hash password
        user.set_password(password)

        # Save user
        db.session.add(user)
        db.session.commit()

        # Automatically login the new user
        login_user(
            user,
            remember=True
        )

        flash(
            "Account created successfully!",
            "success"
        )

        # Directly open dashboard
        return redirect(url_for("dashboard"))

    return render_template("auth/register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    return _login_for_role()

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email","").strip().lower()
        user = User.query.filter_by(email=email).first()
        if user:
            token = secrets.token_urlsafe(32)
            user.reset_token = token
            db.session.commit()
            reset_url = url_for("reset_password", token=token, _external=True)
            send_email(email, "CEMS password reset", f"Reset your password:\n{reset_url}")
        flash("If the account exists, a reset link has been generated.", "info")
        return redirect(url_for("login"))
    return render_template("auth/forgot.html")

@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    user = User.query.filter_by(reset_token=token).first_or_404()
    if request.method == "POST":
        password = request.form.get("password","")
        confirm = request.form.get("confirm_password","")
        if len(password) < 8 or password != confirm:
            flash("Use matching passwords of at least 8 characters.", "danger")
        else:
            user.set_password(password)
            user.reset_token = None
            db.session.commit()
            flash("Password updated. Please log in.", "success")
            return redirect(url_for("login"))
    return render_template("auth/reset.html")

@app.route("/logout")
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
    assigned = EventFaculty.query.filter_by(faculty_id=current_user.id).all()
    assigned_ids = [row.event_id for row in assigned]
    assigned_events = Event.query.filter(Event.id.in_(assigned_ids)).order_by(Event.date.desc()).all() if assigned_ids else []

    total_assigned = len(assigned_events)
    total_registrations = sum(len(event.registrations) for event in assigned_events)
    pending_registrations = sum(1 for event in assigned_events for reg in event.registrations if reg.status == "pending")
    approved_students = sum(1 for event in assigned_events for reg in event.registrations if reg.status in ("confirmed", "approved"))
    total_attendance = sum(1 for event in assigned_events for reg in event.registrations if reg.attended)
    certificates_generated = sum(1 for event in assigned_events for reg in event.registrations if reg.attended)
    return render_template("teacher/dashboard.html", assigned_events=assigned_events, total_assigned=total_assigned,
                           total_registrations=total_registrations, pending_registrations=pending_registrations,
                           approved_students=approved_students, total_attendance=total_attendance,
                           certificates_generated=certificates_generated)


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
    now = datetime.utcnow()
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
    today = datetime.utcnow().date()
    if status == "upcoming":
        query = query.filter(Event.date >= today)
    elif status == "completed":
        query = query.filter(Event.date < today)
    event_list = query.order_by(Event.date.asc()).all()
    categories = [r[0] for r in db.session.query(Event.category).distinct().all()]
    return render_template("events.html", events=event_list, categories=categories, q=q, category=category, status=status)


@app.route("/past-events")
def past_events():
    q = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    venue = request.args.get("venue", "").strip()
    page = request.args.get("page", 1, type=int)
    today = datetime.utcnow().date()

    query = Event.query.filter(Event.status == "approved", Event.date < today)
    if q:
        query = query.filter(Event.title.ilike(f"%{q}%"))
    if category:
        query = query.filter_by(category=category)
    if venue:
        query = query.filter(Event.venue.ilike(f"%{venue}%"))

    pagination = query.order_by(Event.date.desc()).paginate(page=page, per_page=12, error_out=False)
    categories = [r[0] for r in db.session.query(Event.category).distinct().all()]
    venues = [r[0] for r in db.session.query(Event.venue).distinct().all()]

    return render_template("past_events.html", events=pagination.items, categories=categories, venues=venues,
                           q=q, category=category, venue=venue, pagination=pagination)


@app.route("/past-events/<int:event_id>")
def past_event_detail(event_id):
    event = Event.query.get_or_404(event_id)
    if event.date >= datetime.utcnow().date():
        abort(404)
    return render_template("past_event_detail.html", event=event)

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
    elif event.date and event.date < datetime.utcnow().date():
        reg_ctx.update(message="Event completed", reason="Registration is closed for past events.")
    elif event.registration_deadline and datetime.utcnow().date() > event.registration_deadline:
        reg_ctx.update(message="Registration closed", reason="The registration deadline has passed.")
    elif seats <= 0:
        reg_ctx.update(message="Event full", reason="All available places have been reserved.")
    elif registered:
        reg_ctx.update(message="Already registered", reason="This account already has a registration for the event.")
    else:
        reg_ctx.update(can_register=True, message="", reason="")

    return render_template("event_details.html", event=event, registered=registered, seats=seats, reg_ctx=reg_ctx)

@app.route("/student/dashboard")
@role_required("student")
def student_dashboard():
    today = datetime.utcnow().date()
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
    )


@app.route("/student/events")
@role_required("student")
def student_events():
    q = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    status = request.args.get("status", "open").strip()
    page = request.args.get("page", 1, type=int)
    today = datetime.utcnow().date()

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

@app.route("/events/<int:event_id>/register", methods=["GET","POST"])
@role_required("student")
def register_event(event_id):
    event = Event.query.get_or_404(event_id)
    if event.status != "approved":
        flash("This event is not available for registration.", "danger")
        return redirect(url_for("events"))
    existing = Registration.query.filter_by(user_id=current_user.id, event_id=event.id).first()
    if existing:
        flash("You are already registered for this event.", "info")
        return redirect(url_for("my_registrations"))
    count = Registration.query.filter_by(event_id=event.id, status="confirmed").count()
    if count >= event.capacity:
        flash("This event is full.", "danger")
        return redirect(url_for("event_details", event_id=event.id))
    if event.registration_deadline and datetime.utcnow().date() > event.registration_deadline:
        flash("Registration deadline has passed.", "danger")
        return redirect(url_for("event_details", event_id=event.id))
    if request.method == "POST":
        if event.fee > 0:
            return redirect(url_for("demo_payment", event_id=event.id))
        ticket = "AGC-" + secrets.token_hex(4).upper()
        reg = Registration(ticket_code=ticket, user_id=current_user.id, event_id=event.id,
                           status="confirmed", payment_status="free")
        db.session.add(reg)
        create_notification(current_user.id, "Registration confirmed",
                            f"You are registered for {event.title}. Ticket: {ticket}")
        db.session.commit()
        flash("Registration successful. Your digital ticket is ready.", "success")
        return redirect(url_for("ticket", registration_id=reg.id))
    return render_template("student/register_event.html", event=event)

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
    notes = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).all()
    for n in notes:
        n.is_read = True
    db.session.commit()
    return render_template("student/notifications.html", notifications=notes)

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
    upcoming = [registration for registration in registrations if registration.event and registration.event.date >= datetime.utcnow().date()]
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
    return render_template("student/certificates.html", registrations=registrations)


@app.route("/organizer/profile")
@role_required("organizer")
def organizer_profile():
    profile = _ensure_account_profile(current_user)
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


@app.route("/faculty/profile")
@role_required("faculty", "teacher")
def faculty_profile():
    profile = _ensure_account_profile(current_user)
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

@app.route("/registration/<int:registration_id>/feedback", methods=["POST"])
@role_required("student")
def feedback(registration_id):
    reg = Registration.query.get_or_404(registration_id)
    if reg.user_id != current_user.id:
        abort(403)
    rating = int(request.form.get("rating", 5))
    rating = min(max(rating,1),5)
    db.session.add(Feedback(registration_id=reg.id, rating=rating, comment=request.form.get("comment","")))
    db.session.commit()
    flash("Thank you for your feedback.", "success")
    return redirect(url_for("my_registrations"))

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

@app.route("/organizer/volunteer-management")
@role_required("organizer")
def organizer_volunteer_management():
    events = Event.query.filter_by(organizer_id=current_user.id).order_by(Event.date.desc()).all()
    event = events[0] if events else None
    return render_template("organizer/volunteer_management.html", events=events, event=event, roles=[],
                           applications=[], assignments=[], students=[], default_role_names=[])

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
    return render_template("organizer/workflow_status.html", event=event)


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


@app.route("/organizer/events/create", methods=["GET","POST"])
@role_required("organizer")
def create_event():
    if request.method == "POST":
        upload, banner_path, banner_error = _prepare_event_banner()
        if banner_error:
            flash(banner_error, "danger")
            return render_template("organizer/create_event.html", errors={"banner": banner_error})
        action = request.form.get("action", "submit")
        try:
            event = Event(
                title=request.form.get("title","").strip(),
                category=request.form.get("category","Other"),
                event_type=request.form.get("event_type","free"),
                date=datetime.strptime(request.form.get("date"), "%Y-%m-%d").date(),
                start_time=request.form.get("start_time"),
                end_time=request.form.get("end_time"),
                venue=request.form.get("venue"),
                description=request.form.get("description",""),
                highlights=request.form.get("highlights",""),
                capacity=int(request.form.get("capacity",100)),
                registration_deadline=datetime.strptime(request.form.get("registration_deadline"), "%Y-%m-%d").date() if request.form.get("registration_deadline") else None,
                fee=float(request.form.get("fee",0) or 0),
                banner=banner_path,
                status="draft" if action == "draft" else "pending",
                organizer_id=current_user.id
            )
            db.session.add(event)
            _store_event_banner(upload, banner_path)
            db.session.commit()
            if event.status == "pending":
                create_notification(current_user.id, "Event submitted", f"{event.title} was submitted for admin review.")
                flash("Event created and sent for admin approval.", "success")
            else:
                flash("Event draft saved.", "success")
            return redirect(url_for("organizer_dashboard"))
        except Exception as exc:
            db.session.rollback()
            if banner_path:
                _delete_profile_photo(banner_path.removeprefix("/static/"))
            flash(f"Could not create event: {exc}", "danger")
    return render_template("organizer/create_event.html")

@app.route("/organizer/events/<int:event_id>/manage", methods=["GET","POST"])
@role_required("organizer")
def manage_event(event_id):
    event = Event.query.get_or_404(event_id)
    if event.organizer_id != current_user.id:
        abort(403)
    if request.method == "POST":
        upload, banner_path, banner_error = _prepare_event_banner()
        if banner_error:
            flash(banner_error, "danger")
            return redirect(url_for("manage_event", event_id=event.id))
        try:
            event.title = request.form.get("title", event.title).strip()
            event.category = request.form.get("category", event.category)
            event.event_type = request.form.get("event_type", event.event_type)
            event.date = datetime.strptime(request.form.get("date"), "%Y-%m-%d").date() if request.form.get("date") else event.date
            event.registration_deadline = datetime.strptime(request.form.get("registration_deadline"), "%Y-%m-%d").date() if request.form.get("registration_deadline") else None
            event.start_time = request.form.get("start_time", event.start_time)
            event.end_time = request.form.get("end_time", event.end_time)
            event.venue = request.form.get("venue", event.venue)
            event.description = request.form.get("description", event.description)
            event.highlights = request.form.get("highlights", event.highlights)
            event.capacity = max(int(request.form.get("capacity", event.capacity)), 1)
            event.fee = max(float(request.form.get("fee", event.fee) or 0), 0)
            if banner_path:
                event.banner = banner_path
                _store_event_banner(upload, banner_path)
            db.session.commit()
            flash("Event updated.", "success")
        except (TypeError, ValueError) as exc:
            db.session.rollback()
            if banner_path:
                _delete_profile_photo(banner_path.removeprefix("/static/"))
            flash(f"Could not update event: {exc}", "danger")
    return render_template("organizer/manage_event.html", event=event)

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
    return render_template("organizer/reports.html", events=events, total_events=total_events,
                           total_reg=total_reg, total_att=total_att, revenue=revenue)


@app.route("/payment/<int:event_id>", methods=["GET","POST"])
@role_required("student")
def demo_payment(event_id):
    event = Event.query.get_or_404(event_id)
    existing = Registration.query.filter_by(user_id=current_user.id, event_id=event.id).first()
    if existing:
        return redirect(url_for("ticket", registration_id=existing.id))
    if event.fee <= 0:
        return redirect(url_for("register_event", event_id=event.id))
    if request.method == "POST":
        ticket = "AGC-" + secrets.token_hex(4).upper()
        reg = Registration(ticket_code=ticket, user_id=current_user.id, event_id=event.id,
                           status="confirmed", payment_status="paid")
        db.session.add(reg)
        create_notification(current_user.id, "Payment successful",
                            f"Demo payment recorded for {event.title}. Ticket: {ticket}")
        db.session.commit()
        flash("Demo payment successful. Your ticket has been generated.", "success")
        return redirect(url_for("ticket", registration_id=reg.id))
    return render_template("student/payment.html", event=event)

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

@app.route("/admin/dashboard")
@role_required("admin")
def admin_dashboard():
    stats = {
        "users": User.query.count(),
        "events": Event.query.count(),
        "registrations": Registration.query.count(),
        "attendees": Registration.query.filter_by(attended=True).count(),
        "pending_events": Event.query.filter_by(status="pending").count()
    }
    events = Event.query.order_by(Event.created_at.desc()).limit(8).all()
    return render_template("admin/dashboard.html", stats=stats, events=events)

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
    event.status = "approved" if action == "approve" else "rejected"
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
    return render_template("admin/reports.html",
                           total_revenue=total_revenue,
                           avg_rating=avg,
                           users=User.query.count(),
                           events=Event.query.count(),
                           registrations=Registration.query.count(),
                           attendees=Registration.query.filter_by(attended=True).count())

@app.route("/admin/notifications", methods=["GET","POST"])
@role_required("admin")
def admin_notifications():
    users = User.query.filter(User.role != "admin").all()
    if request.method == "POST":
        title = request.form.get("title","Campus Update")
        message = request.form.get("message","")
        selected = request.form.get("audience","all")
        targets = users if selected == "all" else [u for u in users if u.role == selected]
        for u in targets:
            create_notification(u.id, title, message)
        db.session.commit()
        flash(f"Notification sent to {len(targets)} users.", "success")
    return render_template("admin/notifications.html")


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


@app.route("/organizer/support/<module>", methods=["GET","POST"])
@role_required("organizer")
def organizer_support(module):
    if module not in ("volunteers","judges","sponsors"):
        abort(404)
    events = Event.query.filter_by(organizer_id=current_user.id).all()
    if request.method == "POST":
        event_id = int(request.form.get("event_id"))
        if not any(e.id == event_id for e in events):
            abort(403)
        if module == "volunteers":
            db.session.add(Volunteer(name=request.form.get("name"), email=request.form.get("email"),
                                     event_id=event_id, task=request.form.get("task")))
        elif module == "judges":
            db.session.add(Judge(name=request.form.get("name"), email=request.form.get("email"),
                                 event_id=event_id, criteria=request.form.get("criteria")))
        else:
            db.session.add(Sponsor(name=request.form.get("name"), contact=request.form.get("contact"),
                                   event_id=event_id, contribution=float(request.form.get("contribution",0) or 0)))
        db.session.commit()
        module_name = module.rstrip('s').title()
        flash(f"{module_name} added.", "success")
    model = {"volunteers": Volunteer, "judges": Judge, "sponsors": Sponsor}[module]
    rows = model.query.filter(model.event_id.in_([e.id for e in events])).order_by(model.id.desc()).all() if events else []
    return render_template("organizer/support.html", module=module, events=events, rows=rows)

@app.route("/health")
def health():
    return {"status":"ok","college":COLLEGE,"time":datetime.utcnow().isoformat()}

@app.errorhandler(404)
def not_found(error):
    return render_template("errors/404.html"), 404

@app.errorhandler(403)
def forbidden(error):
    return render_template("errors/403.html"), 403

with app.app_context():
    seed_data()

if __name__ == "__main__":
    app.run(debug=True)
