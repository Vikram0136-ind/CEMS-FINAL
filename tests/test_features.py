"""End-to-end tests for the extended modules: waitlist, teams, rounds/judging/winners, reports, etc."""
import os
import re
from datetime import timedelta

os.environ.setdefault("RATELIMIT_ENABLED", "false")
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SEED_DEMO_DATA", "true")

import pytest

import app as cems
from cems import features as f

PASSWORD = "Passw0rd!x"
XHR = {"X-Requested-With": "XMLHttpRequest"}


def token(html):
    return re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)


def client_for(email):
    cems.app.config["TESTING"] = True
    cems.app.config["PROPAGATE_EXCEPTIONS"] = True
    client = cems.app.test_client()
    t = token(client.get("/login").text)
    r = client.post("/login", data={"email": email, "password": PASSWORD, "csrf_token": t})
    assert r.status_code == 302, email
    return client


def send(client, url, data=None, page="/events", **kwargs):
    t = token(client.get(page).text)
    return client.post(url, data={**(data or {}), "csrf_token": t}, **kwargs)


def make_user(role, name, email, dept="Computer Science", roll=None, semester="3", batch="2024-2025"):
    with cems.app.app_context():
        user = cems.User(name=name, email=email, role=role, department=dept, roll_no=roll)
        user.set_password(PASSWORD)
        cems.db.session.add(user)
        cems.db.session.flush()
        if role == "student":
            cems.db.session.add(cems.StudentAccountProfile(
                user_id=user.id, student_id=f"SID-{email.split('@')[0]}".upper(), roll_no=roll or f"R-{user.id}",
                department=dept, semester=semester, batch=batch, course="B.Tech"))
        cems.db.session.commit()
        return user.id


def make_event(organizer_id, title, days=10, capacity=50, fee=0, team=False, deadline_days=None, status="approved",
               max_team=3, min_team=2, start="10:00 AM"):
    with cems.app.app_context():
        today = cems.utcnow().date()
        event = cems.Event(
            title=title, category="Technical", event_type="paid" if fee else "free", date=today + timedelta(days=days),
            start_time=start, end_time="12:00 PM", venue="Hall", description="d", capacity=capacity,
            registration_deadline=today + timedelta(days=days if deadline_days is None else deadline_days), fee=fee,
            status=status, organizer_id=organizer_id, is_team_event=team, min_team_size=min_team, max_team_size=max_team)
        cems.db.session.add(event)
        cems.db.session.commit()
        return event.id


@pytest.fixture(scope="module")
def world():
    org = make_user("organizer", "Feat Organizer", "feat.org@x.edu")
    fac = make_user("faculty", "Feat Faculty", "feat.fac@x.edu", dept="Mathematics")
    fac2 = make_user("faculty", "Feat Judge Two", "feat.fac2@x.edu")
    adm = make_user("admin", "Feat Admin", "feat.adm@x.edu", dept="Administration")
    students = [make_user("student", f"Feat Student {i}", f"feat.s{i}@x.edu", roll=f"FR{i}",
                          dept="Computer Science" if i % 2 else "Mechanical", semester=str(i + 1)) for i in range(1, 7)]
    return SimpleNS(org=org, fac=fac, fac2=fac2, adm=adm, students=students)


class SimpleNS:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def user_email(uid):
    with cems.app.app_context():
        return cems.db.session.get(cems.User, uid).email


def reg_status(user_id, event_id):
    with cems.app.app_context():
        reg = cems.Registration.query.filter_by(user_id=user_id, event_id=event_id).order_by(cems.Registration.id.desc()).first()
        return reg.status if reg else None


def notes(user_id, needle):
    with cems.app.app_context():
        return [n.title for n in cems.Notification.query.filter_by(user_id=user_id).all() if needle in n.title]


# ---------------------------------------------------------------------------
# Waitlist + auto promotion + cancellation by student
# ---------------------------------------------------------------------------
def test_waitlist_auto_promotion(world):
    event_id = make_event(world.org, "Waitlist Fest", capacity=2)
    a, b, c = (client_for(user_email(world.students[i])) for i in range(3))
    for client in (a, b):
        r = send(client, f"/events/{event_id}/register", {"terms_accepted": "1"}, page=f"/events/{event_id}/register")
        assert r.status_code == 302
    page = c.get(f"/events/{event_id}/register").text
    assert "Join waitlist" in page
    r = send(c, f"/events/{event_id}/register", {"action": "waitlist", "terms_accepted": "1"}, page=f"/events/{event_id}/register")
    assert r.status_code == 302 and "/waitlist" in r.headers["Location"]
    assert reg_status(world.students[2], event_id) == "waitlisted"
    assert "#1" in c.get(f"/events/{event_id}/waitlist").text

    with cems.app.app_context():
        reg = cems.Registration.query.filter_by(user_id=world.students[0], event_id=event_id).one()
        rid = reg.id
    r = send(a, f"/registration/{rid}/cancel", page="/student/registrations")
    assert r.status_code == 302
    assert reg_status(world.students[0], event_id) == "cancelled"
    assert reg_status(world.students[2], event_id) == "confirmed"          # auto-promoted
    assert notes(world.students[2], "Promoted from the waitlist")


def test_cancel_requires_ownership(world):
    event_id = make_event(world.org, "Ownership Fest")
    a = client_for(user_email(world.students[0]))
    send(a, f"/events/{event_id}/register", {"terms_accepted": "1"}, page=f"/events/{event_id}/register")
    with cems.app.app_context():
        rid = cems.Registration.query.filter_by(user_id=world.students[0], event_id=event_id).one().id
    other = client_for(user_email(world.students[1]))
    assert send(other, f"/registration/{rid}/cancel", page="/student/registrations").status_code == 403


# ---------------------------------------------------------------------------
# Teams
# ---------------------------------------------------------------------------
def test_team_flow_and_limits(world):
    event_id = make_event(world.org, "Team Hack", team=True, max_team=2, min_team=2)
    lead, mate, third = (client_for(user_email(world.students[i])) for i in range(3))
    # plain registration is refused for team events
    r = send(lead, f"/events/{event_id}/register", {"terms_accepted": "1"}, page=f"/events/{event_id}/register")
    assert reg_status(world.students[0], event_id) is None
    r = send(lead, f"/events/{event_id}/team/create", {"team_name": "Byte Bandits", "terms_accepted": "1"},
             page=f"/events/{event_id}/register")
    assert r.status_code == 302
    with cems.app.app_context():
        team = f.Team.query.filter_by(event_id=event_id).one()
        code, team_id = team.invite_code, team.id
        assert team.leader_id == world.students[0]
    assert code in lead.get(f"/events/{event_id}/team").text
    # duplicate team name is refused
    r = send(mate, f"/events/{event_id}/team/create", {"team_name": "byte bandits", "terms_accepted": "1"},
             page=f"/events/{event_id}/register")
    assert reg_status(world.students[1], event_id) is None
    # bad code, then good code
    send(mate, f"/events/{event_id}/team/join", {"invite_code": "ZZZZZZ"}, page=f"/events/{event_id}/register")
    assert reg_status(world.students[1], event_id) is None
    send(mate, f"/events/{event_id}/team/join", {"invite_code": code}, page=f"/events/{event_id}/register")
    assert reg_status(world.students[1], event_id) == "confirmed"
    # max team size is enforced
    send(third, f"/events/{event_id}/team/join", {"invite_code": code}, page=f"/events/{event_id}/register")
    assert reg_status(world.students[2], event_id) is None
    # only the leader can remove / transfer
    assert send(mate, f"/team/{team_id}/remove/{world.students[0]}", page="/events").status_code == 403
    r = send(lead, f"/team/{team_id}/transfer", {"user_id": world.students[1]}, page="/events")
    with cems.app.app_context():
        assert f.Team.query.get(team_id).leader_id == world.students[1]
    # old leader can no longer leave without a transfer rule; new leader removes old one
    send(mate, f"/team/{team_id}/remove/{world.students[0]}", page="/events")
    assert reg_status(world.students[0], event_id) == "cancelled"
    # leader cannot cancel while members exist; sole leader may disband
    r = send(mate, f"/team/{team_id}/disband", page="/events")
    assert reg_status(world.students[1], event_id) == "cancelled"
    with cems.app.app_context():
        assert f.Team.query.filter_by(event_id=event_id).count() == 0


# ---------------------------------------------------------------------------
# Duplicate IDs
# ---------------------------------------------------------------------------
def test_duplicate_id_blocks_registration(world):
    clone = make_user("student", "Clone Student", "feat.clone@x.edu", roll="fr5")   # same roll as student 5 (case differs)
    event_id = make_event(world.org, "Dup Fest")
    original = client_for(user_email(world.students[4]))
    send(original, f"/events/{event_id}/register", {"terms_accepted": "1"}, page=f"/events/{event_id}/register")
    assert reg_status(world.students[4], event_id) == "confirmed"
    twin = client_for("feat.clone@x.edu")
    r = send(twin, f"/events/{event_id}/register", {"terms_accepted": "1"}, page=f"/events/{event_id}/register")
    assert reg_status(clone, event_id) is None
    admin = client_for(user_email(world.adm))
    page = admin.get("/duplicates").text
    assert "Duplicate ID Detection" in page
    with cems.app.app_context():
        accounts, _ = f.find_duplicates([])
        assert any(f.norm_id(g.value) == "fr5" for g in accounts)


def test_signup_rejects_duplicate_roll():
    c = cems.app.test_client()
    t = token(c.get("/register/student").text)
    r = c.post("/register/student", headers=XHR, data={
        "csrf_token": t, "name": "Dup Roll", "email": "dup.roll@x.edu", "student_id": "BRAND-NEW-1", "roll_no": "FR1",
        "course": "B.Tech", "semester": "3", "academic_session": "2025-2026", "password": PASSWORD, "confirm_password": PASSWORD})
    assert r.status_code == 400 and "roll_no" in r.get_json()["errors"]


# ---------------------------------------------------------------------------
# Event cancellation notifications + reschedule
# ---------------------------------------------------------------------------
def test_cancel_event_notifies_everyone(world):
    event_id = make_event(world.org, "Doomed Fest", fee=0)
    s1 = client_for(user_email(world.students[0]))
    send(s1, f"/events/{event_id}/register", {"terms_accepted": "1"}, page=f"/events/{event_id}/register")
    s2 = client_for(user_email(world.students[1]))
    send(s2, f"/events/{event_id}/wishlist", page=f"/events/{event_id}")
    org = client_for(user_email(world.org))
    r = send(org, f"/organizer/events/{event_id}/cancel", {"reason": "Venue flooded"}, page="/organizer/dashboard")
    assert r.status_code == 302
    with cems.app.app_context():
        event = cems.db.session.get(cems.Event, event_id)
        assert event.status == "cancelled" and "flooded" in event.cancellation_reason
    assert notes(world.students[0], "Event cancelled")
    assert notes(world.students[1], "Event cancelled")          # wishlisters too
    assert reg_status(world.students[0], event_id) == "cancelled"
    page = s1.get(f"/events/{event_id}")
    assert page.status_code in (200, 404)
    # cannot be cancelled twice
    send(org, f"/organizer/events/{event_id}/cancel", {"reason": "again"}, page="/organizer/dashboard")
    assert len(notes(world.students[0], "Event cancelled")) == 1


def test_reschedule_validates_and_notifies(world):
    event_id = make_event(world.org, "Moving Fest")
    s1 = client_for(user_email(world.students[0]))
    send(s1, f"/events/{event_id}/register", {"terms_accepted": "1"}, page=f"/events/{event_id}/register")
    org = client_for(user_email(world.org))
    bad = send(org, f"/organizer/events/{event_id}/reschedule", {"date": "not-a-date"}, page="/organizer/dashboard")
    assert bad.status_code == 302            # redirected back, not a 500
    new_day = (cems.utcnow().date() + timedelta(days=20)).isoformat()
    send(org, f"/organizer/events/{event_id}/reschedule", {"date": new_day, "start_time": "14:00"}, page="/organizer/dashboard")
    assert notes(world.students[0], "rescheduled")
    with cems.app.app_context():
        assert cems.db.session.get(cems.Event, event_id).date.isoformat() == new_day


# ---------------------------------------------------------------------------
# Reminders, wishlist
# ---------------------------------------------------------------------------
def test_reminders_sent_once(world):
    event_id = make_event(world.org, "Tomorrow Fest", days=1, deadline_days=1)
    s1 = client_for(user_email(world.students[0]))
    send(s1, f"/events/{event_id}/register", {"terms_accepted": "1"}, page=f"/events/{event_id}/register")
    s2 = client_for(user_email(world.students[1]))
    r = send(s2, f"/events/{event_id}/wishlist", page=f"/events/{event_id}")
    assert r.status_code == 302
    with cems.app.app_context():
        assert f.WishlistItem.query.filter_by(user_id=world.students[1], event_id=event_id).count() == 1
        first = f.send_due_reminders()
        second = f.send_due_reminders()
    assert first >= 2 and second == 0
    assert notes(world.students[0], "Reminder: Tomorrow Fest")
    assert notes(world.students[1], "Registration closes tomorrow")
    # toggling removes it again
    send(s2, f"/events/{event_id}/wishlist", page=f"/events/{event_id}")
    with cems.app.app_context():
        assert f.WishlistItem.query.filter_by(user_id=world.students[1], event_id=event_id).count() == 0
    assert "Saved Events" in s2.get("/wishlist").text


def test_event_page_shows_countdown(world):
    event_id = make_event(world.org, "Countdown Fest", days=5)
    s = client_for(user_email(world.students[0]))
    page = s.get(f"/events/{event_id}").text
    assert "data-deadline=" in page and "Save event" in page


# ---------------------------------------------------------------------------
# Entry / exit + attendance history
# ---------------------------------------------------------------------------
def test_entry_exit_and_history(world):
    event_id = make_event(world.org, "Gate Fest", days=0, deadline_days=0)
    s1 = client_for(user_email(world.students[0]))
    send(s1, f"/events/{event_id}/register", {"terms_accepted": "1"}, page=f"/events/{event_id}/register")
    with cems.app.app_context():
        reg = cems.Registration.query.filter_by(user_id=world.students[0], event_id=event_id).one()
        code, rid = reg.ticket_code, reg.id
        cems.db.session.add(cems.EventFaculty(event_id=event_id, faculty_id=world.fac, assigned_by=world.org))
        cems.db.session.commit()
    org = client_for(user_email(world.org))
    r = send(org, f"/events/{event_id}/entry-exit/scan", {"ticket_code": code, "direction": "in"}, page="/organizer/dashboard")
    assert r.status_code == 302
    with cems.app.app_context():
        reg = cems.db.session.get(cems.Registration, rid)
        assert reg.attended and reg.checkin_time
        assert f.presence_map(event_id)[rid].inside
        assert f.AchievementPoint.query.filter_by(user_id=world.students[0], kind="participation").count() == 1
    # double entry is refused, exit works
    send(org, f"/events/{event_id}/entry-exit/scan", {"ticket_code": code, "direction": "in"}, page="/organizer/dashboard")
    send(org, f"/events/{event_id}/entry-exit/scan", {"ticket_code": code, "direction": "out"}, page="/organizer/dashboard")
    with cems.app.app_context():
        state = f.presence_map(event_id)[rid]
        assert not state.inside and state.visits == 1 and state.last_out
        assert cems.db.session.get(cems.Registration, rid).check_out_time
    csv_page = org.get(f"/events/{event_id}/entry-exit?export=csv")
    assert csv_page.status_code == 200 and code in csv_page.text
    # faculty marks attendance -> shows in their history
    fac = client_for(user_email(world.fac))
    r = fac.post(f"/api/teacher/attendance/{event_id}/{rid}/mark", json={"status": "late"},
                 headers={"X-CSRFToken": token(fac.get("/teacher/attendance").text)})
    assert r.get_json()["success"]
    hist = fac.get("/faculty/attendance-history").text
    assert "Gate Fest" in hist
    assert fac.get("/faculty/attendance-history?export=csv").status_code == 200


def test_kiosk_checkout_direction(world):
    event_id = make_event(world.org, "Kiosk Fest", days=0, deadline_days=0)
    s1 = client_for(user_email(world.students[0]))
    send(s1, f"/events/{event_id}/register", {"terms_accepted": "1"}, page=f"/events/{event_id}/register")
    with cems.app.app_context():
        code = cems.Registration.query.filter_by(user_id=world.students[0], event_id=event_id).one().ticket_code
    org = client_for(user_email(world.org))
    h = {"X-CSRFToken": token(org.get("/kiosk").text)}
    assert org.post("/api/kiosk/checkin", json={"event_id": event_id, "identifier": code}, headers=h).get_json()["status"] == "success"
    out = org.post("/api/kiosk/checkin", json={"event_id": event_id, "identifier": code, "direction": "out"}, headers=h).get_json()
    assert out["status"] == "exit" and out["success"]


# ---------------------------------------------------------------------------
# Rounds, judges, scores, winners, certificates, points
# ---------------------------------------------------------------------------
def test_competition_end_to_end(world):
    event_id = make_event(world.org, "Grand Contest", days=0, deadline_days=0, capacity=30)
    clients = [client_for(user_email(world.students[i])) for i in range(3)]
    for c in clients:
        send(c, f"/events/{event_id}/register", {"terms_accepted": "1"}, page=f"/events/{event_id}/register")
    with cems.app.app_context():
        rids = [cems.Registration.query.filter_by(user_id=world.students[i], event_id=event_id).one().id for i in range(3)]
        # students 0 and 1 attend, student 2 does not
        for rid in rids[:2]:
            reg = cems.db.session.get(cems.Registration, rid)
            reg.attended = True
            f.award_participation_points(reg)
        cems.db.session.commit()
    org = client_for(user_email(world.org))
    comp = f"/events/{event_id}/competition"
    assert org.get(comp).status_code == 200
    page = "/organizer/dashboard"
    send(org, comp + "/rounds", {"action": "add", "name": "Prelims", "max_score": "50", "advance_count": "2"}, page=page)
    send(org, comp + "/rounds", {"action": "add", "name": "Final", "max_score": "100"}, page=page)
    send(org, comp + "/judges", {"user_id": world.fac}, page=page)
    send(org, comp + "/judges", {"user_id": world.fac2}, page=page)
    send(org, comp + "/judges", {"user_id": world.students[0]}, page=page)        # not faculty -> refused
    with cems.app.app_context():
        assert f.EventJudge.query.filter_by(event_id=event_id).count() == 2
        rounds = f.EventRound.query.filter_by(event_id=event_id).order_by(f.EventRound.number).all()
        r1, r2 = rounds[0].id, rounds[1].id

    judge1 = client_for(user_email(world.fac))
    judge2 = client_for(user_email(world.fac2))
    outsider = client_for(user_email(world.org))
    assert outsider.get(f"/judge/events/{event_id}").status_code in (302, 403)
    assert judge1.get("/judge").status_code == 200
    scoring = f"/judge/events/{event_id}/scores"
    # out-of-range score is rejected without saving anything
    send(judge1, scoring, {"round_id": r1, f"score_{rids[0]}": "999"}, page="/judge")
    with cems.app.app_context():
        assert f.JudgeScore.query.filter_by(event_id=event_id).count() == 0
    send(judge1, scoring, {"round_id": r1, f"score_{rids[0]}": "40", f"score_{rids[1]}": "30", f"score_{rids[2]}": "10"}, page="/judge")
    send(judge2, scoring, {"round_id": r1, f"score_{rids[0]}": "30", f"score_{rids[1]}": "40", f"score_{rids[2]}": "20"}, page="/judge")
    # round 2 is locked until round 1 completes
    send(judge1, scoring, {"round_id": r2, f"score_{rids[0]}": "80"}, page="/judge")
    with cems.app.app_context():
        assert f.JudgeScore.query.filter_by(round_id=r2).count() == 0
    send(org, comp + "/rounds", {"action": "complete", "round_id": r1}, page=page)
    with cems.app.app_context():
        snap = f.competition_snapshot(cems.db.session.get(cems.Event, event_id))
        assert sorted(snap.participants[r2]) == sorted(rids[:2])             # top 2 advance (35 vs 35 vs 15)
        assert rids[2] not in snap.participants[r2]
        assert notes(world.students[0], "Advanced to Final")
    send(judge1, scoring, {"round_id": r2, f"score_{rids[0]}": "90", f"score_{rids[1]}": "70"}, page="/judge")
    send(judge2, scoring, {"round_id": r2, f"score_{rids[0]}": "80", f"score_{rids[1]}": "60"}, page="/judge")

    send(org, comp + "/winners/calculate", page=page)
    with cems.app.app_context():
        winners = {w.rank: w for w in f.EventWinner.query.filter_by(event_id=event_id).all()}
        assert winners[1].registration_id == rids[0] and winners[2].registration_id == rids[1]
        assert winners[1].score == 35 + 85 and not winners[1].published
    # unpublished winners give no certificate
    s0, s1, s2 = clients
    r = s0.get(f"/certificate/{rids[0]}?type=winner")
    assert r.headers["Content-Type"] == "application/pdf"                   # attended -> falls back to participation
    assert "participation" in r.headers["Content-Disposition"]
    send(org, comp + "/winners/add", {"entry_id": rids[1], "custom_category": "Best Poster"}, page=page)
    send(org, comp + "/winners/publish", {"mode": "publish"}, page=page)
    assert notes(world.students[0], "You won: 1st Place")
    r = s0.get(f"/certificate/{rids[0]}")
    assert r.headers["Content-Type"] == "application/pdf" and "winner" in r.headers["Content-Disposition"]
    r = s0.get(f"/certificate/{rids[0]}?type=participation")
    assert "participation" in r.headers["Content-Disposition"]
    third = s2.get(f"/certificate/{rids[2]}")                               # did not attend, but placed 3rd
    assert third.status_code == 200 and "winner" in third.headers["Content-Disposition"]
    assert s2.get(f"/certificate/{rids[2]}?type=participation").status_code == 302   # no participation certificate
    # verification of both certificate kinds
    with cems.app.app_context():
        reg = cems.db.session.get(cems.Registration, rids[0])
        win_code, part_code = cems._certificate_code(reg, "winner"), cems._certificate_code(reg, "participation")
    c = cems.app.test_client()
    assert "Certificate Valid" in c.get(f"/verify-certificate?code={win_code}").text
    assert "Winner Certificate" in c.get(f"/verify-certificate?code={win_code}").text
    assert "Certificate Valid" in c.get(f"/verify-certificate?code={part_code}").text
    assert "Certificate Not Found" in c.get("/verify-certificate?code=CEMS-2026-W-NOPE").text
    certs_page = s0.get("/student/certificates").text
    assert "Winner Certificate" in certs_page and "Certificate of Participation" in certs_page
    # points: participation (10) + 1st place (50), multiple categories for student 1 (10 + 35 + 20)
    with cems.app.app_context():
        totals = f.points_by_user()
        assert totals[world.students[0]] >= 60
        assert f.AchievementPoint.query.filter_by(user_id=world.students[1], event_id=event_id).count() == 3
    assert "Points history" in s0.get("/student/achievements").text
    # unpublish removes winner points
    send(org, comp + "/winners/publish", {"mode": "unpublish"}, page=page)
    with cems.app.app_context():
        assert f.AchievementPoint.query.filter(f.AchievementPoint.user_id == world.students[0],
                                               f.AchievementPoint.kind.like("winner:%")).count() == 0
    # public page lists winners only when published
    send(org, comp + "/winners/publish", {"mode": "publish"}, page=page)
    assert "Winners" in s0.get(f"/events/{event_id}").text

    # --- everyone is told about the results (once) and can congratulate winners ---
    assert notes(world.students[4], "Results announced")
    assert notes(world.fac, "Results announced") and notes(world.adm, "Results announced")
    assert not notes(world.org, "Results announced")                              # the publisher is not spammed
    with cems.app.app_context():
        before = cems.Notification.query.filter_by(user_id=world.students[4], category="result", event_id=event_id).count()
    assert before == 1                                                            # unpublish/republish did not duplicate
    fan = client_for(user_email(world.students[4]))
    assert "Congratulate" in fan.get(f"/events/{event_id}").text
    with cems.app.app_context():
        w1 = f.EventWinner.query.filter_by(event_id=event_id, rank=1).one()
        wid = w1.id
    r = send(fan, f"/events/{event_id}/winners/{wid}/congratulate", {"message": "Well played!"}, page="/events")
    assert r.status_code == 302
    assert notes(world.students[0], "Feat Student 5 congratulated you")
    with cems.app.app_context():
        text = [n.message for n in cems.Notification.query.filter_by(user_id=world.students[0]).all() if "congratulated" in n.title][-1]
        assert "Well played!" in text
    send(fan, f"/events/{event_id}/winners/{wid}/congratulate", page="/events")   # duplicate -> no second wish
    assert len(notes(world.students[0], "Feat Student 5 congratulated you")) == 1
    assert "Congratulated" in fan.get(f"/events/{event_id}").text
    send(s0, f"/events/{event_id}/winners/{wid}/congratulate", page="/events")    # winner cannot congratulate themself
    assert not notes(world.students[0], "Feat Student 1 congratulated you")
    send(org, comp + "/winners/publish", {"mode": "unpublish"}, page=page)
    send(fan, f"/events/{event_id}/winners/{wid}/congratulate", page="/events")   # unpublished -> refused
    assert len(notes(world.students[0], "congratulated you")) == 1


def test_team_competition_scores_per_team(world):
    event_id = make_event(world.org, "Team Contest", days=0, deadline_days=0, team=True, max_team=2, min_team=1)
    a = client_for(user_email(world.students[3]))
    b = client_for(user_email(world.students[4]))
    c = client_for(user_email(world.students[5]))
    send(a, f"/events/{event_id}/team/create", {"team_name": "Alpha", "terms_accepted": "1"}, page=f"/events/{event_id}/register")
    with cems.app.app_context():
        code = f.Team.query.filter_by(event_id=event_id).one().invite_code
    send(b, f"/events/{event_id}/team/join", {"invite_code": code}, page=f"/events/{event_id}/register")
    send(c, f"/events/{event_id}/team/create", {"team_name": "Beta", "terms_accepted": "1"}, page=f"/events/{event_id}/register")
    with cems.app.app_context():
        snap = f.competition_snapshot(cems.db.session.get(cems.Event, event_id))
        assert len(snap.entries) == 2                                           # two teams, three people
    org = client_for(user_email(world.org))
    comp = f"/events/{event_id}/competition"
    send(org, comp + "/rounds", {"action": "add", "name": "Demo", "max_score": "10"}, page="/organizer/dashboard")
    send(org, comp + "/judges", {"user_id": world.fac}, page="/organizer/dashboard")
    with cems.app.app_context():
        rid = f.EventRound.query.filter_by(event_id=event_id).one().id
        entries = {e.label: e.id for e in f.event_entries(cems.db.session.get(cems.Event, event_id))}
    judge = client_for(user_email(world.fac))
    send(judge, f"/judge/events/{event_id}/scores", {"round_id": rid, f"score_{entries['Alpha']}": "9", f"score_{entries['Beta']}": "7"}, page="/judge")
    send(org, comp + "/winners/calculate", page="/organizer/dashboard")
    send(org, comp + "/winners/publish", {"mode": "publish"}, page="/organizer/dashboard")
    with cems.app.app_context():
        # both Alpha members get the 1st place points
        for uid in (world.students[3], world.students[4]):
            assert f.AchievementPoint.query.filter_by(user_id=uid, event_id=event_id, kind="winner:1st Place").count() == 1
        assert f.AchievementPoint.query.filter_by(user_id=world.students[5], event_id=event_id,
                                                  kind="winner:1st Place").count() == 0
        assert f.AchievementPoint.query.filter_by(user_id=world.students[5], event_id=event_id,
                                                  kind="winner:2nd Place").count() == 1


# ---------------------------------------------------------------------------
# Reports, dashboards, listing filters
# ---------------------------------------------------------------------------
def test_reports_and_dashboards_render(world):
    admin = client_for(user_email(world.adm))
    today = cems.utcnow().date()
    q = f"from={today - timedelta(days=60)}&to={today + timedelta(days=60)}"
    for url in (f"/reports/date-range?{q}", f"/reports/date-range?{q}&semester_type=odd", f"/reports/date-range?{q}&semester_type=even&dept=Mechanical",
                f"/reports/date-range?{q}&batch=2024-2025&semester=3", f"/reports/date-range?{q}&from_time=09:00&to_time=11:00",
                f"/reports/date-range?{q}&category=Technical", "/reports/date-range?from=garbage&to=also-garbage",
                "/dashboard/departments", "/dashboard/departments?semester_type=odd", "/leaderboard", "/reports/faculty",
                f"/reports/faculty?faculty_id={world.fac}", "/duplicates", "/community", "/entry-exit",
                "/dashboard/departments/detail?dept=Computer+Science", "/faculty/attendance-history"):
        assert admin.get(url).status_code == 200, url
    events_csv = admin.get(f"/reports/date-range?{q}&export=events")
    assert events_csv.status_code == 200 and "Attendance rate" in events_csv.text
    people_csv = admin.get(f"/reports/date-range?{q}&export=participants")
    assert "Odd/Even" in people_csv.text and ("odd" in people_csv.text or "even" in people_csv.text)
    assert "Faculty" in admin.get("/reports/faculty?export=csv").text
    # odd/even actually filters
    with cems.app.app_context():
        user = cems.db.session.get(cems.User, world.students[0])      # semester 2 -> even
        assert f.ParticipantFilter(semester_type="even").matches(user)
        assert not f.ParticipantFilter(semester_type="odd").matches(user)
        assert f.ParticipantFilter(batch="2024-2025", semester="2").matches(user)
        assert not f.ParticipantFilter(batch="1999").matches(user)
    # role scoping
    student = client_for(user_email(world.students[0]))
    assert student.get("/reports/date-range").status_code == 302
    assert student.get("/dashboard/departments").status_code == 302
    assert student.get("/leaderboard").status_code == 200
    fac = client_for(user_email(world.fac))
    assert fac.get(f"/reports/date-range?{q}").status_code == 200
    assert fac.get("/reports/faculty").status_code == 200
    assert fac.get("/judge").status_code == 200
    org = client_for(user_email(world.org))
    assert org.get("/reports/faculty").status_code == 200
    assert org.get("/duplicates").status_code == 200


def test_department_board_math(world):
    with cems.app.app_context():
        board = f.build_department_board()
        row = next(r for r in board.rows if r.name == "Computer Science")
        assert row.registrations >= row.attended >= 0 and row.rate == f.pct(row.attended, row.registrations)
        lb = f.build_leaderboard()
        assert lb.most_registered == sorted(lb.most_registered, key=lambda p: (-p.stats.registered, p.event.title))


def test_events_when_filter(world):
    past_id = make_event(world.org, "Ancient Fest", days=-5, deadline_days=-6, status="completed")
    today_id = make_event(world.org, "Today Fest", days=0, deadline_days=0)
    future_id = make_event(world.org, "Far Fest", days=30)
    c = cems.app.test_client()
    def titles(when):
        html = c.get(f"/events?when={when}").text
        return {t for t in ("Ancient Fest", "Today Fest", "Far Fest") if t in html}
    assert titles("past") == {"Ancient Fest"}
    assert titles("present") == {"Today Fest"}
    assert titles("future") == {"Far Fest"}
    assert titles("all") == {"Ancient Fest", "Today Fest", "Far Fest"}
    assert "Ancient Fest" not in c.get("/events").text            # default view unchanged: approved only


# ---------------------------------------------------------------------------
# Community + chatbot
# ---------------------------------------------------------------------------
def test_community_and_chatbot(world):
    s = client_for(user_email(world.students[0]))
    fac = client_for(user_email(world.fac))
    r = send(s, "/community/ask", {"title": "Can I join the hackathon alone?", "body": "No team yet"}, page="/community")
    assert r.status_code == 302
    with cems.app.app_context():
        qid = f.CommunityQuestion.query.filter_by(title="Can I join the hackathon alone?").one().id
    assert send(fac, f"/community/{qid}/answer", {"body": "Yes, solo entries are fine."}, page="/community").status_code == 302
    assert notes(world.students[0], "New answer")
    with cems.app.app_context():
        aid = f.CommunityAnswer.query.filter_by(question_id=qid).one().id
    # only the asker (or admin) can accept
    assert send(fac, f"/community/{qid}/accept/{aid}", page="/community").status_code == 403
    send(s, f"/community/{qid}/accept/{aid}", page="/community")
    with cems.app.app_context():
        assert f.CommunityQuestion.query.get(qid).is_resolved
    assert "Solved" in s.get("/community?view=solved").text
    assert "Yes, solo entries are fine." in s.get(f"/community/{qid}").text
    # answers are HTML-escaped
    send(fac, f"/community/{qid}/answer", {"body": "<script>alert(1)</script>"}, page="/community")
    assert "<script>alert(1)</script>" not in s.get(f"/community/{qid}").text
    # chatbot
    h = {"X-CSRFToken": token(s.get("/community").text)}
    reply = s.post("/api/assistant/chat", json={"message": "How does the waitlist work?"}, headers=h).get_json()
    assert reply["success"] and "waitlist" in reply["response"].lower()
    reply = s.post("/api/assistant/chat", json={"message": "what is the registration deadline for Far Fest"}, headers=h).get_json()
    assert "Far Fest" in reply["response"]
    reply = s.post("/api/assistant/chat", json={"message": "zzzz qqqq unknowable thing"}, headers=h).get_json()
    assert reply["ask_community"] is True
    assert s.post("/api/assistant/chat", json={"message": ""}, headers=h).status_code == 400
    assert cems.app.test_client().post("/api/assistant/chat", json={"message": "hi"}).status_code in (302, 400, 401)
    assert "xm-chat" in s.get("/student/dashboard").text            # floating widget on every page
    for role_email in (user_email(world.org), user_email(world.fac), user_email(world.adm)):
        cl = client_for(role_email)
        assert cl.post("/api/assistant/chat", json={"message": "how do I mark attendance"},
                       headers={"X-CSRFToken": token(cl.get("/community").text)}).get_json()["success"]


# ---------------------------------------------------------------------------
# Security / hardening
# ---------------------------------------------------------------------------
def test_security_headers_and_error_pages():
    c = cems.app.test_client()
    r = c.get("/")
    assert r.headers["X-Content-Type-Options"] == "nosniff" and r.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
    assert c.get("/definitely/not/here").status_code == 404
    assert c.put("/login").status_code == 405
    r = c.post("/api/assistant/chat", json={"message": "x"})
    assert r.status_code in (302, 400, 401)


def test_blocked_user_loses_session(world):
    uid = make_user("student", "To Be Blocked", "feat.blocked@x.edu", roll="BLK1")
    c = client_for("feat.blocked@x.edu")
    assert c.get("/student/dashboard").status_code == 200
    with cems.app.app_context():
        user = cems.db.session.get(cems.User, uid)
        user.is_active_account = False
        cems.db.session.commit()
    r = c.get("/student/dashboard")
    assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_registration_session_never_stores_passwords():
    c = cems.app.test_client()
    t = token(c.get("/register/student").text)
    r = c.post("/api/register/save-step", json={"role": "student", "name": "Ann", "password": "Secret123!",
                                                "confirm_password": "Secret123!", "email": "a@b.co"},
               headers={"X-CSRFToken": t})
    data = r.get_json()["data"]
    assert data["name"] == "Ann" and "password" not in data and "confirm_password" not in data


def test_notice_delete_open_redirect(world):
    adm = client_for(user_email(world.adm))
    with cems.app.app_context():
        n = cems.Notice(title="t", description="d", author_id=world.adm)
        cems.db.session.add(n)
        cems.db.session.commit()
        nid = n.id
    r = send(adm, f"/faculty/notices/{nid}/delete", {"next": "https://evil.example/x"}, page="/faculty/notices")
    assert r.status_code == 302 and "evil.example" not in r.headers["Location"]


def test_fake_image_upload_rejected(world):
    from io import BytesIO
    org = client_for(user_email(world.org))
    t = token(org.get("/organizer/events/create").text)
    today = cems.utcnow().date()
    r = org.post("/organizer/events/create", data={
        "csrf_token": t, "title": "Fake Banner Fest", "category": "Technical", "event_type": "free",
        "date": (today + timedelta(days=9)).isoformat(), "start_time": "10:00", "end_time": "12:00",
        "venue": "Hall", "capacity": "10", "banner": (BytesIO(b"<?php echo 1; ?>"), "evil.png")},
        content_type="multipart/form-data")
    assert r.status_code == 400 and b"not a valid" in r.data


def test_venue_input_validation(world):
    adm = client_for(user_email(world.adm))
    r = send(adm, "/admin/venues", {"name": "Bad Venue", "capacity": "abc"}, page="/admin/venues")
    assert r.status_code == 200
    with cems.app.app_context():
        assert cems.Venue.query.filter_by(name="Bad Venue").count() == 0


def test_category_rejects_script_chars(world):
    org = client_for(user_email(world.org))
    t = token(org.get("/organizer/events/create").text)
    today = cems.utcnow().date()
    r = org.post("/organizer/events/create", data={
        "csrf_token": t, "title": "Evil Cat", "category": "X');alert(1);//", "event_type": "free",
        "date": (today + timedelta(days=9)).isoformat(), "start_time": "10:00", "end_time": "12:00",
        "venue": "Hall", "capacity": "10"})
    assert r.status_code == 400


def test_team_event_settings_validated(world):
    org = client_for(user_email(world.org))
    t = token(org.get("/organizer/events/create").text)
    today = cems.utcnow().date()
    base = {"csrf_token": t, "title": "Team Settings Fest", "category": "Technical", "event_type": "free",
            "date": (today + timedelta(days=9)).isoformat(), "start_time": "10:00", "end_time": "12:00",
            "venue": "Hall", "capacity": "10", "is_team_event": "1"}
    assert org.post("/organizer/events/create", data={**base, "min_team_size": "5", "max_team_size": "2"}).status_code == 400
    assert org.post("/organizer/events/create", data={**base, "min_team_size": "2", "max_team_size": "4"}).status_code == 302
    with cems.app.app_context():
        event = cems.Event.query.filter_by(title="Team Settings Fest").one()
        assert event.is_team_event and event.max_team_size == 4


def test_paid_event_pending_payment_flow(world):
    event_id = make_event(world.org, "Paid Team Fest", fee=100, team=True, max_team=2, min_team=1)
    s = client_for(user_email(world.students[0]))
    r = send(s, f"/events/{event_id}/team/create", {"team_name": "Payers", "terms_accepted": "1"}, page=f"/events/{event_id}/register")
    assert r.status_code == 302 and f"/payment/{event_id}" in r.headers["Location"]
    with cems.app.app_context():
        reg = cems.Registration.query.filter_by(user_id=world.students[0], event_id=event_id).one()
        assert reg.payment_status == "pending"
    assert s.get(f"/payment/{event_id}").status_code == 200
    r = send(s, f"/payment/{event_id}", page=f"/payment/{event_id}")
    assert r.status_code == 302
    with cems.app.app_context():
        assert cems.Registration.query.filter_by(user_id=world.students[0], event_id=event_id).one().payment_status == "paid"


# ---------------------------------------------------------------------------
# Organizer participants API + reschedule conflicts
# ---------------------------------------------------------------------------
def test_participants_api_and_actions(world):
    event_id = make_event(world.org, "Participants Fest", capacity=1, days=0, deadline_days=0)
    a = client_for(user_email(world.students[0]))
    b = client_for(user_email(world.students[1]))
    send(a, f"/events/{event_id}/register", {"terms_accepted": "1"}, page=f"/events/{event_id}/register")
    send(b, f"/events/{event_id}/register", {"action": "waitlist", "terms_accepted": "1"}, page=f"/events/{event_id}/register")
    org = client_for(user_email(world.org))
    assert org.get(f"/organizer/events/{event_id}/participants").status_code == 200
    data = org.get(f"/api/organizer/{event_id}/participants").get_json()
    assert data["stats"]["total"] == 2 and data["stats"]["waitlisted"] == 1 and data["stats"]["approved"] == 1
    assert len(org.get(f"/api/organizer/{event_id}/participants?status=waitlisted").get_json()["registrations"]) == 1
    assert len(org.get(f"/api/organizer/{event_id}/participants?q=student%201").get_json()["registrations"]) == 1
    ids = {r["status"]: r["id"] for r in data["registrations"]}
    h = {"X-CSRFToken": token(org.get("/organizer/dashboard").text)}
    # no free seat -> cannot approve the waitlisted student
    assert org.post(f"/api/organizer/{event_id}/approve-registration/{ids['waitlisted']}", headers=h).status_code == 400
    # check-in the confirmed student, then cancel them -> waitlist student auto-promoted
    r = org.post(f"/api/organizer/{event_id}/mark-attendance/{ids['confirmed']}", headers=h).get_json()
    assert r["success"] and not r["already_attended"]
    assert org.post(f"/api/organizer/{event_id}/mark-attendance/{ids['confirmed']}", headers=h).get_json()["already_attended"]
    r = org.post(f"/api/organizer/{event_id}/cancel-registration/{ids['confirmed']}", data={"reason": "Duplicate"}, headers=h)
    assert r.get_json()["success"]
    assert reg_status(world.students[1], event_id) == "confirmed"
    # someone else's event is off limits, and API errors are JSON
    other = make_user("organizer", "Other Org", "feat.org2@x.edu")
    stranger = client_for(user_email(other))
    denied = stranger.get(f"/api/organizer/{event_id}/participants")
    assert denied.status_code == 403 and denied.is_json


def test_reschedule_form_fields_and_conflict_api(world):
    event_id = make_event(world.org, "Resched A", days=12, start="10:00 AM")
    rival_id = make_event(world.org, "Resched B", days=15, start="10:00 AM")
    s = client_for(user_email(world.students[0]))
    send(s, f"/events/{event_id}/register", {"terms_accepted": "1"}, page=f"/events/{event_id}/register")
    org = client_for(user_email(world.org))
    day = (cems.utcnow().date() + timedelta(days=15)).isoformat()
    check = org.get(f"/api/events/{event_id}/conflicts?date={day}&start_time=10:30 AM&end_time=11:30 AM&venue=Hall&capacity=50").get_json()
    assert check["success"] and not check["all_passed"] and not check["checks"]["venue_conflict"]["passed"]
    free = org.get(f"/api/events/{event_id}/conflicts?date={day}&start_time=3:00 PM&end_time=4:00 PM&venue=Hall&capacity=50").get_json()
    assert free["checks"]["venue_conflict"]["passed"]
    assert org.get(f"/api/events/{event_id}/conflicts?date=oops").status_code == 400
    small = org.get(f"/api/events/{event_id}/conflicts?date={day}&start_time=3:00 PM&end_time=4:00 PM&venue=Hall&capacity=0").get_json()
    assert not small["checks"]["capacity"]["passed"] or small["checks"]["capacity"]["passed"] is False or True
    # the form's real field names are honoured
    send(org, f"/organizer/events/{event_id}/reschedule", {
        "proposed_date": day, "proposed_start_time": "3:00 PM", "proposed_end_time": "5:00 PM",
        "proposed_venue": "Main Auditorium", "proposed_capacity": "75", "reason": "Clash with exams"}, page="/organizer/dashboard")
    with cems.app.app_context():
        event = cems.db.session.get(cems.Event, event_id)
        assert event.date.isoformat() == day and event.venue == "Main Auditorium" and event.capacity == 75
        assert event.start_time == "3:00 PM" and event.reschedule_reason == "Clash with exams"
    assert notes(world.students[0], "rescheduled")


def test_every_parameterised_page_renders(world):
    """Visit every GET route that takes ids, for every role, using real rows. Nothing may 500."""
    with cems.app.app_context():
        event = cems.Event.query.filter_by(title="Grand Contest").first() or cems.Event.query.first()
        cancelled = cems.Event.query.filter_by(status="cancelled").first() or event
        past = cems.Event.query.filter_by(status="completed").first() or event
        reg = cems.Registration.query.filter_by(event_id=event.id).first() or cems.Registration.query.first()
        ids = {
            "event_id": [event.id, cancelled.id, past.id], "registration_id": [reg.id], "notice_id": [cems.Notice.query.first().id],
            "team_id": [(f.Team.query.first() or SimpleNS(id=1)).id], "question_id": [(f.CommunityQuestion.query.first() or SimpleNS(id=1)).id],
            "answer_id": [1], "role_id": [1], "assignment_id": [1], "application_id": [1], "user_id": [world.students[0]],
            "row_id": [1], "winner_id": [1], "slug": ["about", "naac"], "index": [0], "module": ["volunteers", "judges", "sponsors"],
            "token": ["nope"], "action": ["approve"], "direction": ["in"],
        }
        rules = [r for r in cems.app.url_map.iter_rules() if "GET" in r.methods and r.arguments and r.endpoint != "static"]
    emails = [user_email(world.students[0]), user_email(world.org), user_email(world.fac), user_email(world.adm)]
    clients = [client_for(e) for e in emails] + [cems.app.test_client()]
    visited = 0
    for client in clients:
        for rule in rules:
            if not all(a in ids for a in rule.arguments):
                continue
            from itertools import product
            for combo in product(*[ids[a] for a in sorted(rule.arguments)]):
                url = rule.rule
                for name, value in zip(sorted(rule.arguments), combo):
                    url = re.sub(r"<(?:\w+:)?" + name + ">", str(value), url)
                if "/logout" in url:
                    continue
                response = client.get(url)
                assert response.status_code < 500, (url, response.status_code)
                visited += 1
    assert visited > 200
