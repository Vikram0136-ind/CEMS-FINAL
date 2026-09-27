"""Smoke tests for multi-step wizard."""
import sys
import os
import json
import io

os.environ["SECRET_KEY"] = "test-secret-key"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from app import app

# Disable CSRF for test client
app.config["WTF_CSRF_ENABLED"] = False

client = app.test_client()
results = []

def check(name, condition):
    status = "PASS" if condition else "FAIL"
    results.append(status)
    print(f"{status}: {name}")

# Test pages load with stepper
resp = client.get("/register/student")
check("Student page loads", resp.status_code == 200)
html = resp.get_data(as_text=True)
check("Student form present", "student-register-form" in html)
check("Student stepper present", "student-stepper" in html)
check("Student step 1", 'data-step="1"' in html)
check("Student step 2", 'data-step="2"' in html)
check("Student step 3", 'data-step="3"' in html)
check("Student step 4", 'data-step="4"' in html)
check("Student indicator", "Step 1 of 4" in html)

resp = client.get("/register/organizer")
check("Organizer page loads", resp.status_code == 200)
html = resp.get_data(as_text=True)
check("Organizer form present", "organizer-register-form" in html)
check("Organizer stepper present", "organizer-stepper" in html)
check("Organizer step 1", 'data-step="1"' in html)
check("Organizer step 2", 'data-step="2"' in html)
check("Organizer step 3", 'data-step="3"' in html)
check("Organizer indicator", "Step 1 of 3" in html)

resp = client.get("/register/faculty")
check("Faculty page loads", resp.status_code == 200)
html = resp.get_data(as_text=True)
check("Faculty form present", "faculty-register-form" in html)
check("Faculty stepper present", "faculty-stepper" in html)
check("Faculty step 1", 'data-step="1"' in html)
check("Faculty step 2", 'data-step="2"' in html)
check("Faculty step 3", 'data-step="3"' in html)
check("Faculty indicator", "Step 1 of 3" in html)

# Test API validation
resp = client.post("/api/register/validate-step", data={
    "role": "student", "step": "1",
    "name": "John Doe", "email": "john@test.com", "mobile": "+919876543210",
})
data = json.loads(resp.get_data(as_text=True))
check("Student step 1 valid", resp.status_code == 200 and data["success"])

resp = client.post("/api/register/validate-step", data={
    "role": "student", "step": "1",
    "name": "", "email": "",
})
data = json.loads(resp.get_data(as_text=True))
check("Student step 1 invalid", resp.status_code == 400 and data["success"] is False)

resp = client.post("/api/register/validate-step", data={
    "role": "student", "step": "2",
    "student_id": "99CS9999", "roll_no": "99CS9999",
})
data = json.loads(resp.get_data(as_text=True))
check("Student step 2 valid", resp.status_code == 200 and data["success"])

resp = client.post("/api/register/validate-step", data={
    "role": "student", "step": "3",
    "course": "B.Tech", "semester": "1", "academic_session": "2025-2026", "batch": "2025",
})
data = json.loads(resp.get_data(as_text=True))
check("Student step 3 valid", resp.status_code == 200 and data["success"])

resp = client.post("/api/register/validate-step", data={
    "role": "student", "step": "4",
    "password": "Pass123!@#", "confirm_password": "Pass123!@#",
})
data = json.loads(resp.get_data(as_text=True))
check("Student step 4 valid", resp.status_code == 200 and data["success"])

resp = client.post("/api/register/validate-step", data={
    "role": "organizer", "step": "1",
    "name": "Jane", "email": "jane@test.com", "mobile": "+919876543211",
})
data = json.loads(resp.get_data(as_text=True))
check("Organizer step 1 valid", resp.status_code == 200 and data["success"])

resp = client.post("/api/register/validate-step", data={
    "role": "organizer", "step": "2",
    "employee_id": "AGC-ORG-1001",
})
data = json.loads(resp.get_data(as_text=True))
check("Organizer step 2 valid", resp.status_code == 200 and data["success"])

resp = client.post("/api/register/validate-step", data={
    "role": "organizer", "step": "3",
    "password": "Org123!@#", "confirm_password": "Org123!@#",
})
data = json.loads(resp.get_data(as_text=True))
check("Organizer step 3 valid", resp.status_code == 200 and data["success"])

resp = client.post("/api/register/validate-step", data={
    "role": "faculty", "step": "1",
    "name": "Dr Smith", "email": "dr@test.com", "mobile": "+919876543212",
})
data = json.loads(resp.get_data(as_text=True))
check("Faculty step 1 valid", resp.status_code == 200 and data["success"])

resp = client.post("/api/register/validate-step", data={
    "role": "faculty", "step": "2",
    "employee_id": "AGC-FAC-1001",
})
data = json.loads(resp.get_data(as_text=True))
check("Faculty step 2 valid", resp.status_code == 200 and data["success"])

resp = client.post("/api/register/validate-step", data={
    "role": "faculty", "step": "3",
    "password": "Fac123!@#", "confirm_password": "Fac123!@#",
})
data = json.loads(resp.get_data(as_text=True))
check("Faculty step 3 valid", resp.status_code == 200 and data["success"])

# Test invalid role/step
resp = client.post("/api/register/validate-step", data={"role": "invalid", "step": "1"})
check("Invalid role rejected", resp.status_code == 400)

resp = client.post("/api/register/validate-step", data={"role": "student", "step": "99"})
check("Invalid step rejected", resp.status_code == 400)

# Test session save/restore
resp = client.post("/api/register/save-step", data={
    "role": "student", "step": "1", "name": "Test", "email": "test@test.com",
})
data = json.loads(resp.get_data(as_text=True))
check("Save step", resp.status_code == 200 and data["success"])

resp = client.post("/api/register/restore-step", data={"role": "student", "step": "1"})
data = json.loads(resp.get_data(as_text=True))
check("Restore step", resp.status_code == 200 and data["success"] and data["data"]["name"] == "Test")

resp = client.post("/api/register/clear-session")
data = json.loads(resp.get_data(as_text=True))
check("Clear session", resp.status_code == 200 and data["success"])

resp = client.post("/api/register/restore-step", data={"role": "student", "step": "1"})
data = json.loads(resp.get_data(as_text=True))
check("Session cleared", resp.status_code == 200 and data["data"] == {})

# Test full registration
resp = client.post("/register/student", data={
    "name": "Test Student", "email": "student@test.com", "mobile": "+919876543213",
    "date_of_birth": "2000-01-15",
    "student_id": "99CS9999", "roll_no": "99CS9999",
    "course": "B.Tech", "semester": "1", "academic_session": "2025-2026", "batch": "2025",
    "password": "Test123!@#", "confirm_password": "Test123!@#",
})
check("Student registration", resp.status_code in (200, 302))

resp = client.post("/register/organizer", data={
    "name": "Test Organizer", "email": "org@test.com", "mobile": "+919876543214",
    "employee_id": "AGC-ORG-9999", "department": "Student Affairs",
    "password": "Org123!@#", "confirm_password": "Org123!@#",
})
check("Organizer registration", resp.status_code in (200, 302))

resp = client.post("/register/faculty", data={
    "name": "Dr Faculty", "email": "fac@test.com", "mobile": "+919876543215",
    "employee_id": "AGC-FAC-9999", "department": "CS", "designation": "Asst Prof",
    "password": "Fac123!@#", "confirm_password": "Fac123!@#",
})
check("Faculty registration", resp.status_code in (200, 302))

resp = client.get("/faculty/dashboard")
check("Faculty dashboard access", resp.status_code == 200)

# Test duplicate email
client.post("/register/student", data={
    "name": "Dup", "email": "dup@test.com", "mobile": "+919876543216",
    "student_id": "99CS8888", "roll_no": "99CS8888",
    "course": "B.Tech", "semester": "1", "academic_session": "2025-2026", "batch": "2025",
    "password": "Test123!@#", "confirm_password": "Test123!@#",
})
resp = client.post("/register/student", data={
    "name": "Dup2", "email": "dup@test.com", "mobile": "+919876543217",
    "student_id": "99CS7777", "roll_no": "99CS7777",
    "course": "B.Tech", "semester": "1", "academic_session": "2025-2026", "batch": "2025",
    "password": "Test123!@#", "confirm_password": "Test123!@#",
})
data = json.loads(resp.get_data(as_text=True))
check("Duplicate email rejected", resp.status_code == 400 and "email" in data.get("errors", {}))

passed = results.count("PASS")
failed = results.count("FAIL")
total = len(results)
print(f"\nResults: {passed} passed, {failed} failed out of {total} tests")
if failed > 0:
    sys.exit(1)
