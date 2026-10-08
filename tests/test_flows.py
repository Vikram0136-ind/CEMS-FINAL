import os
import re

os.environ.setdefault("RATELIMIT_ENABLED", "false")
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SEED_DEMO_DATA", "true")

from datetime import timedelta

import pytest

import app as cems

XHR = {"X-Requested-With": "XMLHttpRequest"}


def token(html):
    return re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)


def new_client():
    cems.app.config["TESTING"] = True
    cems.app.config["PROPAGATE_EXCEPTIONS"] = True
    return cems.app.test_client()


def post(client, url, data=None, page="/login", **kwargs):
    t = token(client.get(page).text)
    return client.post(url, data={**(data or {}), "csrf_token": t}, **kwargs)


def login(client, email, password):
    r = post(client, "/login", {"email": email, "password": password})
    assert r.status_code == 302, r.status_code
    return r


def register(role, **fields):
    c = new_client()
    r = post(c, f"/register/{role}", fields, headers=XHR)
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["redirect"] == "/login"


@pytest.fixture(scope="module")
def accounts():
    register("faculty", name="Flow Faculty", email="flow.faculty@x.edu", employee_id="FAC-FLOW-1", mobile="9876501234",
             department="CS", designation="Professor", faculty_role="Event Coordinator",
             password="Faculty@123", confirm_password="Faculty@123")
    register("organizer", name="Flow Organizer", email="flow.org@x.edu", employee_id="ORG-FLOW-1",
             organizer_type="General", password="Organizer@123", confirm_password="Organizer@123")
    register("student", name="Flow Student", email="flow.student@x.edu", student_id="S-FLOW-1", roll_no="R1",
             course="B.Tech", semester="3", academic_session="2025-2026",
             password="Student@123", confirm_password="Student@123")


def test_registration_validation_and_duplicates(accounts):
    c = new_client()
    r = post(c, "/register/faculty", {"name": "", "email": "bad", "password": "x"}, headers=XHR)
    assert r.status_code == 400 and "name" in r.get_json()["errors"]
    r = post(c, "/register/faculty", {"name": "Dup", "email": "flow.faculty@x.edu", "employee_id": "Z",
                                       "faculty_role": "Judge", "password": "Faculty@123",
                                       "confirm_password": "Faculty@123"}, headers=XHR)
    assert r.status_code == 400 and "email" in r.get_json()["errors"]


def test_every_role_lands_on_own_dashboard(accounts):
    for email, pw, path in [("flow.faculty@x.edu", "Faculty@123", "/faculty/dashboard"),
                            ("flow.org@x.edu", "Organizer@123", "/organizer/dashboard"),
                            ("flow.student@x.edu", "Student@123", "/student/dashboard")]:
        c = new_client()
        r = login(c, email, pw)
        assert r.headers["Location"].endswith(path)
        page = c.get(path)
        assert page.status_code == 200 and "cems-sidebar" in page.text


def test_full_event_lifecycle(accounts):
    org, admin, student, faculty = new_client(), new_client(), new_client(), new_client()
    login(org, "flow.org@x.edu", "Organizer@123")
    login(admin, "admin@agc.local", "Admin@123")
    login(student, "flow.student@x.edu", "Student@123")
    login(faculty, "flow.faculty@x.edu", "Faculty@123")

    day = (cems.utcnow().date() + timedelta(days=5)).isoformat()
    r = post(org, "/organizer/events/create", {
        "title": "Flow Test Event", "category": "Technical", "event_type": "free", "date": day,
        "start_time": "10:00", "end_time": "12:00", "venue": "Seminar Hall", "capacity": "50", "fee": "0",
        "description": "desc", "rules": "be kind", "eligibility": "all", "contact_info": "x@y.z",
        "main_guest": "A", "chief_guest": "B", "action": "submit"}, page="/organizer/events/create")
    assert r.status_code == 302
    with cems.app.app_context():
        event = cems.Event.query.filter_by(title="Flow Test Event").one()
        eid = event.id
        assert event.status == "pending" and event.start_time == "10:00 AM" and event.chief_guest == "B"

    assert student.get(f"/events/{eid}").status_code == 404

    assert post(admin, f"/admin/events/{eid}/approve", page="/admin/events").status_code == 302
    assert student.get(f"/events/{eid}").status_code == 200

    r = post(student, f"/events/{eid}/register", page=f"/events/{eid}/register")
    assert r.status_code == 302 and "/register" in r.headers["Location"]
    r = post(student, f"/events/{eid}/register", {"terms_accepted": "on"}, page=f"/events/{eid}/register")
    assert "/ticket/" in r.headers["Location"]
    assert student.get(r.headers["Location"]).status_code == 200
    reg_page = student.get("/student/registrations").text
    assert "Flow Test Event" in reg_page and "Confirmed" in reg_page
    with cems.app.app_context():
        code = cems.Registration.query.filter_by(event_id=eid).one().ticket_code

    r = post(student, f"/events/{eid}/register", {"terms_accepted": "on"}, page="/student/dashboard")
    assert "/ticket/" in r.headers["Location"]

    assert post(faculty, f"/faculty/event/{eid}/join", page="/faculty/dashboard").status_code == 302
    assert "Flow Test Event" in faculty.get("/faculty/assigned-events").text

    r = post(org, "/organizer/checkin", {"ticket_code": code}, page="/organizer/checkin")
    assert r.status_code == 200 and "checked in successfully" in r.text

    r = post(faculty, f"/faculty/event/{eid}/complete", {"completion_notes": "n"}, page="/faculty/dashboard")
    assert r.status_code == 302
    with cems.app.app_context():
        assert cems.db.session.get(cems.Event, eid).status == "approved"


def test_notices_and_profiles(accounts):
    for email, pw, url in [("flow.faculty@x.edu", "Faculty@123", "/faculty/profile"),
                           ("flow.org@x.edu", "Organizer@123", "/organizer/profile")]:
        c = new_client()
        login(c, email, pw)
        r = post(c, "/faculty/notices", {"title": f"Notice by {email}", "category": "General", "description": "hello"},
                 page="/faculty/notices")
        assert r.status_code == 302
        assert f"Notice by {email}" in c.get("/notices").text
        r = post(c, url, {"name": "Renamed Person", "mobile": "9999999999", "department": "Dept", "designation": "Lead",
                          "bio": "bio"}, page=url)
        assert r.status_code == 302
        assert "Renamed Person" in c.get(url).text


def test_role_isolation(accounts):
    s = new_client()
    login(s, "flow.student@x.edu", "Student@123")
    for url in ("/organizer/dashboard", "/faculty/dashboard", "/admin/dashboard", "/faculty/notices"):
        r = s.get(url)
        assert r.status_code == 302 and "/student/dashboard" in r.headers["Location"]
    assert new_client().get("/student/dashboard").status_code == 302


def test_sidebar_has_no_dead_links(accounts):
    for email, pw in [("flow.faculty@x.edu", "Faculty@123"), ("flow.org@x.edu", "Organizer@123"),
                      ("flow.student@x.edu", "Student@123"), ("admin@agc.local", "Admin@123")]:
        c = new_client()
        login(c, email, pw)
        home = c.get(c.get("/dashboard").headers["Location"]).text
        for href in set(re.findall(r'class="cems-nav-item[^"]*" href="([^"]+)"', home)):
            assert c.get(href).status_code < 400, (email, href)
