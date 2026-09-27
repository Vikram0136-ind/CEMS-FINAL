import re
from app import app


def csrf_token(client, path):
    page = client.get(path)
    match = re.search(r'name="csrf_token"\s+value="([^"]+)"', page.get_data(as_text=True))
    if not match:
        raise AssertionError(f'No CSRF token on {path}')
    return match.group(1)

client = app.test_client()
for route in ['/register/student', '/register/faculty', '/register/organizer']:
    resp = client.get(route)
    print('GET', route, resp.status_code)

student_token = csrf_token(client, '/login')
student_login = client.post('/login', data={'email': 'student@agc.local', 'password': 'Student@123', 'csrf_token': student_token}, follow_redirects=True)
print('student login status', student_login.status_code)
print('student request path', student_login.request.path)
print('student history', [(r.status_code, r.location) for r in getattr(student_login, 'history', [])])

student_unauthorized = client.get('/organizer/dashboard', follow_redirects=False)
print('student unauthorized', student_unauthorized.status_code, student_unauthorized.location)

faculty_client = app.test_client()
faculty_token = csrf_token(faculty_client, '/login')
print('faculty token acquired', faculty_token[:12])
response = faculty_client.post('/login', data={'email': 'teacher@agc.local', 'password': 'Teacher@123', 'csrf_token': faculty_token}, follow_redirects=False)
print('faculty login status', response.status_code)
print('faculty redirect location', response.location)
with faculty_client.session_transaction() as session:
    print('faculty session user id', session.get('_user_id'))
    print('faculty session keys', list(session.keys()))
print('faculty dashboard direct', faculty_client.get('/faculty/dashboard', follow_redirects=False).status_code)
print('faculty dashboard direct location', faculty_client.get('/faculty/dashboard', follow_redirects=False).location)

print('done')
