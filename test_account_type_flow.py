import re
from datetime import date, timedelta
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from app import (
    AttendanceRecord,
    Event,
    EventFaculty,
    FacultyAccountProfile,
    OrganizerAccountProfile,
    Registration,
    StudentAccountProfile,
    User,
    app,
    db,
)


def _csrf_token(client, path):
    page = client.get(path)
    match = re.search(r'name="csrf_token"\s+value="([^"]+)"', page.get_data(as_text=True))
    assert match, f'No CSRF token found on {path}'
    return match.group(1)


def test_account_type_page_has_required_role_selection_heading():
    client = app.test_client()
    response = client.get('/register')
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert 'Choose Your Account Type' in text
    assert '.acems-account-type-grid' in text
    assert 'grid-template-columns: repeat(3, minmax(0, 1fr))' in text
    assert 'Student' in text
    assert 'Faculty Member' in text
    assert 'Organizer' in text
    assert text.count('/register/student') == 1
    assert text.count('/register/faculty') == 1
    assert text.count('/register/organizer') == 1
    assert client.get('/notices').status_code == 200
    assert client.get('/notices/1').status_code == 200


def test_role_specific_routes_and_dashboard_access_are_separated():
    client = app.test_client()
    routes = ['/register/student', '/register/faculty', '/register/organizer']
    for route in routes:
        resp = client.get(route)
        assert resp.status_code == 200
        page = resp.get_data(as_text=True)
        if route == '/register/faculty':
            assert 'Faculty Registration' in page
            assert 'name="faculty_role"' in page
            assert 'name="academic_session"' in page
        if route == '/register/organizer':
            assert 'Organizer Registration' in page
            assert 'value="General" selected' in page

    student_token = _csrf_token(client, '/login')
    student_login = client.post('/login', data={'email': 'student@agc.local', 'password': 'Student@123', 'csrf_token': student_token}, follow_redirects=True)
    assert student_login.status_code == 200
    assert '/student/dashboard' in student_login.request.path or '/dashboard' in student_login.request.path
    dashboard_text = student_login.get_data(as_text=True)
    for label in ('Active Tickets', 'Certificates', 'My Uploaded Images'):
        assert re.search(
            rf'<div class="cems-stat-value">\d+</div>\s*<div class="cems-stat-label">{label}</div>',
            dashboard_text,
        ), f'Missing numeric dashboard value for {label}'

    student_unauthorized = client.get('/organizer/dashboard', follow_redirects=False)
    assert student_unauthorized.status_code in (302, 403)

    faculty_client = app.test_client()
    faculty_token = _csrf_token(faculty_client, '/login')
    faculty_login = faculty_client.post('/login', data={'email': 'teacher@agc.local', 'password': 'Teacher@123', 'csrf_token': faculty_token}, follow_redirects=True)
    assert faculty_login.status_code == 200
    assert '/faculty/dashboard' in faculty_login.request.path or '/teacher/dashboard' in faculty_login.request.path

    organizer_client = app.test_client()
    organizer_token = _csrf_token(organizer_client, '/login')
    organizer_login = organizer_client.post('/login', data={'email': 'organizer@agc.local', 'password': 'Organizer@123', 'csrf_token': organizer_token}, follow_redirects=True)
    assert organizer_login.status_code == 200
    assert '/organizer/dashboard' in organizer_login.request.path


def test_role_registration_persists_profiles_and_role_logins_return_json():
    client = app.test_client()
    client.get('/login')
    suffix = uuid4().hex[:10]
    accounts = [
        {
            'path': '/register/student',
            'login_path': '/login/student',
            'email': f'student-{suffix}@example.test',
            'password': 'Student@123',
            'payload': {
                'name': 'Test Student', 'mobile': '9876543210',
                'student_id': f'ST-{suffix}', 'roll_no': f'RN-{suffix}',
                'course': 'B.Tech', 'semester': '3',
                'academic_session': '2026-2027', 'batch': '2025',
            },
            'profile_model': StudentAccountProfile,
            'profile_field': 'student_id',
            'profile_value': f'ST-{suffix}',
            'redirect': '/student/dashboard',
            'profile_path': '/student/profile',
            'sidebar_item': 'My Certificates',
            'profile_heading': 'Student Profile',
        },
        {
            'path': '/register/organizer',
            'login_path': '/organizer/login',
            'email': f'organizer-{suffix}@example.test',
            'password': 'Organizer@123',
            'payload': {
                'name': 'Test Organizer', 'employee_id': f'ORG-{suffix}',
                'department': 'Student Affairs', 'designation': 'Event Coordinator',
                'organizer_type': 'General',
            },
            'profile_model': OrganizerAccountProfile,
            'profile_field': 'employee_id',
            'profile_value': f'ORG-{suffix}',
            'redirect': '/organizer/dashboard',
            'profile_path': '/organizer/profile',
            'sidebar_item': 'Sponsor Ledger',
            'profile_heading': 'Organizer Profile',
        },
        {
            'path': '/register/faculty',
            'login_path': '/faculty/login',
            'email': f'faculty-{suffix}@example.test',
            'password': 'Faculty@123',
            'payload': {
                'name': 'Test Faculty', 'employee_id': f'FAC-{suffix}',
                'department': 'Computer Science', 'designation': 'Assistant Professor',
                'faculty_role': 'Faculty Member', 'academic_session': '2026-2027',
            },
            'profile_model': FacultyAccountProfile,
            'profile_field': 'employee_id',
            'profile_value': f'FAC-{suffix}',
            'redirect': '/faculty/dashboard',
            'profile_path': '/faculty/profile',
            'sidebar_item': 'Assigned Events',
            'profile_heading': 'Faculty Profile',
        },
    ]
    emails = [account['email'] for account in accounts]

    try:
        for account in accounts:
            token = _csrf_token(client, account['path'])
            response = client.post(
                account['path'],
                data={
                    **account['payload'],
                    'email': account['email'],
                    'password': account['password'],
                    'confirm_password': account['password'],
                    'csrf_token': token,
                },
                headers={'X-Requested-With': 'XMLHttpRequest'},
            )
            assert response.status_code == 200
            assert response.get_json()['redirect'] == account['login_path']

            with app.app_context():
                user = User.query.filter_by(email=account['email']).one()
                profile = account['profile_model'].query.filter_by(user_id=user.id).one()
                assert getattr(profile, account['profile_field']) == account['profile_value']

            login_client = app.test_client()
            login_token = _csrf_token(login_client, account['login_path'])
            login_response = login_client.post(
                account['login_path'],
                data={'email': account['email'], 'password': account['password'], 'csrf_token': login_token},
                headers={'X-Requested-With': 'XMLHttpRequest'},
            )
            assert login_response.status_code == 200
            assert login_response.get_json()['redirect'] == account['redirect']
            dashboard_response = login_client.get(account['redirect'])
            assert dashboard_response.status_code == 200
            assert account['sidebar_item'] in dashboard_response.get_data(as_text=True)
            profile_response = login_client.get(account['profile_path'])
            assert profile_response.status_code == 200
            assert account['profile_heading'] in profile_response.get_data(as_text=True)

        student_account = accounts[0]
        wrong_role_client = app.test_client()
        wrong_role_token = _csrf_token(wrong_role_client, '/faculty/login')
        wrong_role_response = wrong_role_client.post(
            '/faculty/login',
            data={
                'email': student_account['email'],
                'password': student_account['password'],
                'csrf_token': wrong_role_token,
            },
            headers={'X-Requested-With': 'XMLHttpRequest'},
        )
        assert wrong_role_response.status_code == 400
        assert 'faculty portal' in wrong_role_response.get_json()['message']
    finally:
        with app.app_context():
            users = User.query.filter(User.email.in_(emails)).all()
            user_ids = [user.id for user in users]
            if user_ids:
                for profile_model in (StudentAccountProfile, OrganizerAccountProfile, FacultyAccountProfile):
                    profile_model.query.filter(profile_model.user_id.in_(user_ids)).delete(synchronize_session=False)
                for user in users:
                    db.session.delete(user)
                db.session.commit()


def test_faculty_attendance_is_assignment_scoped_and_persisted():
    suffix = uuid4().hex[:10]
    client = app.test_client()
    with app.app_context():
        faculty = User.query.filter_by(email='teacher@agc.local').one()
        organizer = User.query.filter_by(email='organizer@agc.local').one()
        student = User(name='Attendance Test Student', email=f'attendance-{suffix}@example.test', role='student', roll_no=f'R-{suffix}')
        student.set_password('Student@123')
        event = Event(
            title=f'Attendance Test {suffix}', category='Technical', event_type='free',
            date=date.today() + timedelta(days=10), start_time='10:00', end_time='11:00',
            venue='Test Hall', capacity=20, status='approved', organizer_id=organizer.id,
        )
        db.session.add_all([student, event])
        db.session.flush()
        registration = Registration(
            ticket_code=f'TEST-{suffix}', user_id=student.id, event_id=event.id,
            status='confirmed', payment_status='free',
        )
        db.session.add_all([
            registration,
            EventFaculty(event_id=event.id, faculty_id=faculty.id, assigned_by=faculty.id),
        ])
        db.session.commit()
        event_id = event.id
        registration_id = registration.id
        student_id = student.id

    try:
        token = _csrf_token(client, '/login')
        login_response = client.post(
            '/login',
            data={'email': 'teacher@agc.local', 'password': 'Teacher@123', 'csrf_token': token},
        )
        assert login_response.status_code == 302

        page = client.get(f'/teacher/attendance?event_id={event_id}')
        assert page.status_code == 200
        assert f'Attendance Test {suffix}' in page.get_data(as_text=True)

        attendance_response = client.get(f'/api/teacher/attendance/{event_id}?search=Attendance')
        assert attendance_response.status_code == 200
        attendance_data = attendance_response.get_json()
        assert attendance_data['total'] == 1
        assert attendance_data['students'][0]['registration_id'] == registration_id
        assert attendance_data['students'][0]['attendance_status'] == 'not_marked'

        mark_response = client.post(
            f'/api/teacher/attendance/{event_id}/{registration_id}/mark',
            json={'status': 'late'},
            headers={'X-CSRFToken': token},
        )
        assert mark_response.status_code == 200
        assert mark_response.get_json()['success'] is True

        refreshed = client.get(f'/api/teacher/attendance/{event_id}').get_json()
        assert refreshed['students'][0]['attendance_status'] == 'late'
        assert refreshed['students'][0]['check_in_time']
        with app.app_context():
            registration = db.session.get(Registration, registration_id)
            assert registration.attended is True
            assert AttendanceRecord.query.filter_by(registration_id=registration_id).one().status == 'late'

        export = client.get(f'/teacher/attendance/export?event_id={event_id}')
        assert export.status_code == 200
        assert f'Attendance Test Student' in export.get_data(as_text=True)

        denied = client.get('/api/teacher/attendance/999999')
        assert denied.status_code == 403
    finally:
        with app.app_context():
            AttendanceRecord.query.filter_by(registration_id=registration_id).delete()
            Registration.query.filter_by(id=registration_id).delete()
            EventFaculty.query.filter_by(event_id=event_id).delete()
            db.session.delete(db.session.get(Event, event_id))
            db.session.delete(db.session.get(User, student_id))
            db.session.commit()


def test_organizer_event_and_attendee_artifacts_are_owner_scoped():
    suffix = uuid4().hex[:10]
    with app.app_context():
        organizer = User.query.filter_by(email='organizer@agc.local').one()
        other_organizer = User(
            name='Other Organizer', email=f'other-organizer-{suffix}@example.test', role='organizer'
        )
        other_organizer.set_password('Organizer@123')
        student = User(name='Owner Test Student', email=f'owner-student-{suffix}@example.test', role='student')
        student.set_password('Student@123')
        event = Event(
            title=f'Private Pending Event {suffix}', category='Technical', event_type='free',
            date=date.today() + timedelta(days=10), start_time='10:00', end_time='11:00',
            venue='Owner Hall', capacity=20, status='pending', organizer=other_organizer,
        )
        db.session.add_all([other_organizer, student, event])
        db.session.flush()
        registration = Registration(
            ticket_code=f'OWNER-{suffix}', user_id=student.id, event_id=event.id,
            status='confirmed', payment_status='free', attended=True,
        )
        db.session.add(registration)
        db.session.commit()
        event_id = event.id
        registration_id = registration.id
        organizer_id = other_organizer.id
        student_id = student.id

    try:
        client = app.test_client()
        token = _csrf_token(client, '/organizer/login')
        client.post('/organizer/login', data={
            'email': 'organizer@agc.local', 'password': 'Organizer@123', 'csrf_token': token,
        })
        assert client.get(f'/events/{event_id}').status_code == 404
        assert client.get(f'/ticket/{registration_id}').status_code == 403
        assert client.get(f'/ticket/{registration_id}/qr').status_code == 403
        assert client.get(f'/certificate/{registration_id}').status_code == 403

        owner_client = app.test_client()
        owner_token = _csrf_token(owner_client, '/organizer/login')
        owner_client.post('/organizer/login', data={
            'email': f'other-organizer-{suffix}@example.test',
            'password': 'Organizer@123',
            'csrf_token': owner_token,
        })
        assert owner_client.get(f'/events/{event_id}').status_code == 200
        assert owner_client.get(f'/ticket/{registration_id}').status_code == 200
        assert owner_client.get(f'/ticket/{registration_id}/qr').status_code == 200
        assert owner_client.get(f'/certificate/{registration_id}').status_code == 200
    finally:
        with app.app_context():
            Registration.query.filter_by(id=registration_id).delete()
            db.session.delete(db.session.get(Event, event_id))
            db.session.delete(db.session.get(User, student_id))
            db.session.delete(db.session.get(User, organizer_id))
            db.session.commit()


def test_organizer_event_create_and_edit_persist_existing_fields_and_banner():
    suffix = uuid4().hex[:10]
    client = app.test_client()
    banner_path = None
    with app.app_context():
        organizer_id = User.query.filter_by(email='organizer@agc.local').one().id

    try:
        token = _csrf_token(client, '/organizer/login')
        login_response = client.post('/organizer/login', data={
            'email': 'organizer@agc.local', 'password': 'Organizer@123', 'csrf_token': token,
        })
        assert login_response.status_code == 302

        create_token = _csrf_token(client, '/organizer/events/create')
        created = client.post('/organizer/events/create', data={
            'csrf_token': create_token,
            'title': f'QA Event {suffix}',
            'category': 'Technical',
            'event_type': 'paid',
            'date': (date.today() + timedelta(days=30)).isoformat(),
            'start_time': '10:30',
            'end_time': '12:30',
            'registration_deadline': (date.today() + timedelta(days=20)).isoformat(),
            'venue': 'QA Auditorium',
            'capacity': '25',
            'fee': '99.50',
            'description': 'QA event description',
            'highlights': 'QA highlight',
            'action': 'submit',
            'banner': (BytesIO(b'qa banner bytes'), f'{suffix}.png'),
        }, follow_redirects=False)
        assert created.status_code == 302

        with app.app_context():
            event = Event.query.filter_by(title=f'QA Event {suffix}', organizer_id=organizer_id).one()
            event_id = event.id
            banner_path = Path(app.static_folder) / event.banner.removeprefix('/static/')
            assert event.status == 'pending'
            assert event.event_type == 'paid'
            assert event.capacity == 25
            assert event.fee == 99.5
            assert banner_path.is_file()

        edit_token = _csrf_token(client, f'/organizer/events/{event_id}/manage')
        edited = client.post(f'/organizer/events/{event_id}/manage', data={
            'csrf_token': edit_token,
            'title': f'QA Event Updated {suffix}',
            'category': 'Workshop',
            'event_type': 'free',
            'date': (date.today() + timedelta(days=45)).isoformat(),
            'start_time': '13:00',
            'end_time': '15:00',
            'registration_deadline': (date.today() + timedelta(days=35)).isoformat(),
            'venue': 'QA Seminar Hall',
            'capacity': '40',
            'fee': '0',
            'description': 'Updated description',
            'highlights': 'Updated highlight',
        })
        assert edited.status_code == 200
        with app.app_context():
            event = db.session.get(Event, event_id)
            assert event.title == f'QA Event Updated {suffix}'
            assert event.event_type == 'free'
            assert event.date == date.today() + timedelta(days=45)
            assert event.start_time == '13:00'
            assert event.end_time == '15:00'
            assert event.registration_deadline == date.today() + timedelta(days=35)
            assert event.venue == 'QA Seminar Hall'
            assert event.capacity == 40
            assert event.banner
    finally:
        with app.app_context():
            event = Event.query.filter_by(organizer_id=organizer_id, title=f'QA Event Updated {suffix}').first()
            if event is None:
                event = Event.query.filter_by(organizer_id=organizer_id, title=f'QA Event {suffix}').first()
            if event:
                db.session.delete(event)
                db.session.commit()
        if banner_path and banner_path.exists():
            banner_path.unlink()


def test_organizer_kiosk_lists_owned_events_and_records_checkin():
    suffix = uuid4().hex[:10]
    with app.app_context():
        organizer = User.query.filter_by(email='organizer@agc.local').one()
        student = User.query.filter_by(email='student@agc.local').one()
        event = Event(
            title=f'Kiosk QA Event {suffix}', category='Technical', event_type='free',
            date=date.today() + timedelta(days=10), start_time='10:00', end_time='11:00',
            venue='Kiosk Hall', capacity=20, status='approved', organizer_id=organizer.id,
        )
        db.session.add(event)
        db.session.flush()
        registration = Registration(
            ticket_code=f'KIOSK-{suffix}'.upper(), user_id=student.id, event_id=event.id,
            status='confirmed', payment_status='free',
        )
        db.session.add(registration)
        db.session.commit()
        event_id = event.id
        registration_id = registration.id

    try:
        client = app.test_client()
        login_token = _csrf_token(client, '/organizer/login')
        client.post('/organizer/login', data={
            'email': 'organizer@agc.local', 'password': 'Organizer@123', 'csrf_token': login_token,
        })
        kiosk_page = client.get('/kiosk')
        csrf_match = re.search(r'<meta name="csrf-token" content="([^"]+)"', kiosk_page.get_data(as_text=True))
        assert csrf_match
        csrf_token = csrf_match.group(1)

        events_response = client.get('/api/kiosk/events')
        assert events_response.status_code == 200
        assert any(item['id'] == event_id for item in events_response.get_json()['events'])
        stats = client.get(f'/api/kiosk/stats/{event_id}').get_json()
        assert stats['registered'] == 1
        assert stats['attended'] == 0

        checkin = client.post('/api/kiosk/checkin', json={
            'event_id': event_id, 'identifier': f'KIOSK-{suffix}', 'method': 'qr_scan',
        }, headers={'X-CSRFToken': csrf_token})
        assert checkin.status_code == 200
        assert checkin.get_json()['status'] == 'success'
        duplicate = client.post('/api/kiosk/checkin', json={
            'event_id': event_id, 'identifier': f'KIOSK-{suffix}', 'method': 'manual',
        }, headers={'X-CSRFToken': csrf_token})
        assert duplicate.get_json()['status'] == 'duplicate'

        with app.app_context():
            registration = db.session.get(Registration, registration_id)
            attendance = AttendanceRecord.query.filter_by(registration_id=registration_id).one()
            assert registration.attended is True
            assert attendance.method == 'kiosk_qr'
        assert client.get('/api/kiosk/stats/999999').status_code == 403
    finally:
        with app.app_context():
            AttendanceRecord.query.filter_by(registration_id=registration_id).delete()
            Registration.query.filter_by(id=registration_id).delete()
            db.session.delete(db.session.get(Event, event_id))
            db.session.commit()
