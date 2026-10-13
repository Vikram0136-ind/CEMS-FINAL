"""Faculty-controlled dynamic QR attendance."""
import re
from datetime import timedelta

import pytest

from test_features import SimpleNS, XHR, cems, client_for, make_event, make_user, send, token
from cems import qr_attendance as qa


@pytest.fixture(scope="module")
def world():
    org = make_user("organizer", "QR Organizer", "qr.org@x.edu")
    fac = make_user("faculty", "QR Faculty", "qr.fac@x.edu")
    other = make_user("faculty", "QR Other Faculty", "qr.fac2@x.edu")
    adm = make_user("admin", "QR Admin", "qr.adm@x.edu", dept="Administration")
    students = [make_user("student", f"QR Student {i}", f"qr.s{i}@x.edu", roll=f"QR{i}") for i in range(1, 5)]
    event = make_event(org, "QR Workshop", days=1)
    with cems.app.app_context():
        cems.db.session.add(cems.EventFaculty(event_id=event, faculty_id=fac))
        for sid in students[:3]:   # students[3] stays unregistered
            cems.db.session.add(cems.Registration(ticket_code=f"QRT{sid}", user_id=sid, event_id=event, status="confirmed"))
        cems.db.session.commit()
    return SimpleNS(org=org, fac=fac, other=other, adm=adm, students=students, event=event)


def email(uid):
    with cems.app.app_context():
        return cems.db.session.get(cems.User, uid).email


def start(world, minutes="10", who=None):
    client = client_for(email(who or world.fac))
    r = send(client, "/faculty/attendance-qr/start", {"event_id": world.event, "minutes": minutes}, page="/faculty/attendance-qr")
    assert r.status_code == 302
    return client, r.headers["Location"].rsplit("/", 1)[1]


def session_of(ref):
    with cems.app.app_context():
        s = qa.AttendanceSession.query.filter_by(ref=ref).first()
        return s.token, s.id


def test_dashboard_and_generate_pages_render(world):
    client = client_for(email(world.fac))
    assert "Generate Attendance QR" in client.get("/faculty/dashboard").text
    page = client.get("/faculty/attendance-qr").text
    assert "QR Workshop" in page and 'max="15"' in page


def test_session_creation_qr_and_clamping(world):
    client, ref = start(world, minutes="999")
    with cems.app.app_context():
        s = qa.AttendanceSession.query.filter_by(ref=ref).first()
        assert (s.expires_at - s.created_at) == timedelta(minutes=15) and len(s.token) >= 40 and s.status == "active"
    page = client.get(f"/faculty/attendance-qr/{ref}").text
    assert "End session" in page and "Active" in page
    png = client.get(f"/faculty/attendance-qr/{ref}/qr.png")
    assert png.status_code == 200 and png.data[:4] == b"\x89PNG"
    assert client.get(f"/faculty/attendance-qr/{ref}/status").get_json()["count"] == 0


def test_student_flow_login_redirect_mark_duplicate(world):
    _, ref = start(world)
    tok, _ = session_of(ref)
    anon = cems.app.test_client()
    r = anon.get(f"/attend/{tok}")
    assert r.status_code == 302 and "/login" in r.headers["Location"] and "next=" in r.headers["Location"]

    student = client_for(email(world.students[0]))
    page = student.get(f"/attend/{tok}").text
    assert "Confirm my attendance" in page and "QR Student 1" in page and "QR Workshop" in page
    assert 'name="roll' not in page and 'type="email"' not in page
    r = send(student, f"/attend/{tok}", page=f"/attend/{tok}")
    assert r.status_code == 200 and "Attendance recorded" in r.text
    r = send(student, f"/attend/{tok}", page=f"/attend/{tok}")
    assert "Already marked" in r.text
    with cems.app.app_context():
        assert qa.AttendanceSessionMark.query.count() >= 1
        reg = cems.Registration.query.filter_by(user_id=world.students[0], event_id=world.event).first()
        assert reg.attended and cems.AttendanceRecord.query.filter_by(registration_id=reg.id).first().method == "qr_session"

    fac = client_for(email(world.fac))
    data = fac.get(f"/faculty/attendance-qr/{ref}/status").get_json()
    assert data["count"] == 1 and data["rows"][0]["roll_no"] and data["rows"][0]["checked_in"]
    assert fac.get(f"/faculty/attendance-qr/{ref}/status?q=zzzz").get_json()["rows"] == []
    # existing attendance report reflects the QR check-in
    api = fac.get(f"/api/teacher/attendance/{world.event}").get_json()
    assert any(s["attendance_status"] == "present" for s in api["students"])


def test_unregistered_and_wrong_role_blocked(world):
    _, ref = start(world)
    tok, _ = session_of(ref)
    stranger = client_for(email(world.students[3]))
    r = send(stranger, f"/attend/{tok}", page=f"/attend/{tok}")
    assert r.status_code == 403 and "Not eligible" in r.text
    r = send(client_for(email(world.fac)), f"/attend/{tok}", page="/faculty/dashboard")
    assert r.status_code == 403
    with cems.app.app_context():
        assert qa.AttendanceSessionMark.query.filter_by(user_id=world.students[3]).count() == 0


def test_invalid_token(world):
    student = client_for(email(world.students[1]))
    assert student.get("/attend/not-a-real-token-at-all-xxxxxxxxxxxx").status_code == 404
    assert "Invalid QR code" in student.get("/attend/short").text


def test_expiry_enforced_on_server(world):
    _, ref = start(world)
    tok, sid = session_of(ref)
    student = client_for(email(world.students[1]))
    page = student.get(f"/attend/{tok}").text  # page rendered while still active
    assert "Confirm my attendance" in page
    with cems.app.app_context():
        s = cems.db.session.get(qa.AttendanceSession, sid)
        s.expires_at = cems.utcnow() - timedelta(seconds=1)
        cems.db.session.commit()
    r = send(student, f"/attend/{tok}", page="/events")
    assert r.status_code == 410 and "Session expired" in r.text
    assert student.get(f"/attend/{tok}").status_code == 410
    fac = client_for(email(world.fac))
    assert fac.get(f"/faculty/attendance-qr/{ref}/status").get_json()["status"] == "expired"
    with cems.app.app_context():
        assert qa.AttendanceSessionMark.query.filter_by(session_id=sid, user_id=world.students[1]).count() == 0


def test_manual_close_and_no_reuse(world):
    fac, ref = start(world)
    tok, sid = session_of(ref)
    r = send(fac, f"/faculty/attendance-qr/{ref}/close", page=f"/faculty/attendance-qr/{ref}")
    assert r.status_code == 302
    student = client_for(email(world.students[2]))
    r = send(student, f"/attend/{tok}", page="/events")
    assert r.status_code == 410 and "Session closed" in r.text
    with cems.app.app_context():
        assert cems.db.session.get(qa.AttendanceSession, sid).status == "closed"
    # a new session for the same event closes any still-open one
    _, ref2 = start(world)
    _, ref3 = start(world)
    with cems.app.app_context():
        assert qa.AttendanceSession.query.filter_by(ref=ref2).first().status == "closed"


def test_authorization_of_session_management(world):
    _, ref = start(world)
    other = client_for(email(world.other))
    assert other.get(f"/faculty/attendance-qr/{ref}").status_code == 404
    assert other.get(f"/faculty/attendance-qr/{ref}/status").status_code == 404
    assert send(other, f"/faculty/attendance-qr/{ref}/close", page="/faculty/attendance-qr").status_code == 404
    r = send(other, "/faculty/attendance-qr/start", {"event_id": world.event, "minutes": "5"}, page="/faculty/attendance-qr")
    assert r.status_code == 302 and "/faculty/attendance-qr" in r.headers["Location"]
    with cems.app.app_context():
        assert qa.AttendanceSession.query.filter_by(faculty_id=world.other).count() == 0
    student = client_for(email(world.students[0]))
    assert student.get("/faculty/attendance-qr").status_code == 302
    assert student.get(f"/faculty/attendance-qr/{ref}").status_code == 302
    admin = client_for(email(world.adm))
    assert admin.get(f"/faculty/attendance-qr/{ref}").status_code == 200
    assert cems.app.test_client().get(f"/faculty/attendance-qr/{ref}").status_code == 302


def test_csrf_required_on_start_and_close(world):
    cems.app.config["WTF_CSRF_ENABLED"] = True
    client = client_for(email(world.fac))
    assert client.post("/faculty/attendance-qr/start", data={"event_id": world.event}).status_code == 400


def test_duplicate_constraint_in_database(world):
    from sqlalchemy.exc import IntegrityError
    _, ref = start(world)
    _, sid = session_of(ref)
    with cems.app.app_context():
        reg = cems.Registration.query.filter_by(user_id=world.students[0], event_id=world.event).first()
        for _ in range(2):
            cems.db.session.add(qa.AttendanceSessionMark(session_id=sid, registration_id=reg.id, user_id=world.students[0]))
            if _ == 0:
                cems.db.session.commit()
        with pytest.raises(IntegrityError):
            cems.db.session.commit()
        cems.db.session.rollback()
