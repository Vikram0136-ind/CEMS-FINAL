# ACEMS AGC — Role-Based Authentication System

## Architecture & Routing Plan

> **Scope**: Authentication and authorization only. No UI implementation.
> No event-management functionality is modified.

---

## 1. System Overview

The system uses a **single centralized authentication layer** (Flask-Login + Werkzeug password hashing) shared by all three account types. Role-based access control is enforced via a single decorator (`@role_required`) that gates every protected route. There is exactly **one** password hashing implementation, **one** session manager, and **one** login flow — never duplicated per role.

### Three Primary Account Types

| Type | Internal Role Value | Dashboard Route | Registration Route | Login Route |
|------|-------------------|----------------|-------------------|-------------|
| **Student** | `student` | `/student/dashboard` | `/register/student` | `/login/student` |
| **Faculty Member** | `teacher` | `/teacher/dashboard` | `/register/faculty` | `/login/faculty` |
| **Organizer** | `organizer` | `/organizer/dashboard` | `/register/organizer` | `/login/organizer` |

> **Internal role mapping**: The `User.role` column stores `student`, `teacher`, or `organizer`. During faculty registration, the form submits `role=faculty`, and `persist_registration_user()` (app.py:4270-4274) maps this internally to `user_role = "teacher"`. This mapping is preserved — no change required.

---

## 2. Existing Architecture (Reused As-Is)

### 2.1 Core Authentication Components

| Component | Location | Status |
|-----------|----------|--------|
| `User` model with `role` column | `app.py:412` | ✅ Exists, supports `student`, `teacher`, `organizer`, `admin`, `volunteer` |
| Password hashing | `User.set_password()` / `User.check_password()` (app.py:434-438) | ✅ Uses `werkzeug.security.generate_password_hash` / `check_password_hash` — single implementation, no duplication |
| Session management | Flask-Login (`login_manager` in `cems/extensions.py`) | ✅ Single `LoginManager` instance, `@login_required` globally available |
| `load_user` loader | `app.py:1449-1451` | ✅ Loads by `user.id` from `User` model |
| CSRF protection | `cems/extensions.py:14` (Flask-WTF `csrf`) | ✅ Applied to all forms |
| Rate limiting | `cems/extensions.py:16-20` (Flask-Limiter) | ✅ Applied per-route |
| `@role_required` decorator | `app.py:1575-1584` | ✅ Single decorator, accepts `*roles` varargs |
| `@login_required` | Flask-Login | ✅ Applied to all protected routes |
| `is_safe_url()` | Utility for redirect validation | ✅ Exists |

### 2.2 Existing Registration Routes (Reused As-Is)

| Route | Handler | Role Set | Status |
|-------|---------|----------|--------|
| `/register` | `register()` | — | ✅ Account type selection page (`auth/account_type.html`) |
| `/register/student` | `student_register_page()` | `student` | ✅ Exists, uses `auth/student_register.html` |
| `/register/faculty` | `faculty_register_page()` | `teacher` | ✅ Exists, uses `auth/faculty_register.html` |
| `/register/organizer` | `organizer_register_page()` | `organizer` | ✅ Exists, uses `auth/organizer_register.html` |
| `/api/register` | `api_register()` | — | ✅ Legacy AJAX endpoint (preserved) |
| `/api/register/validate-step` | `api_validate_registration_step()` | — | ✅ Multi-step validation (preserved) |
| `persist_registration_user()` | `app.py:4254` | — | ✅ Single function, no role duplication |
| `validate_registration_payload()` | Utility | — | ✅ Shared validation pipeline |

### 2.3 Existing Login Routes (Reused / Extended)

| Route | Handler | Status |
|-------|---------|--------|
| `/login` | `login()` | ✅ Generic login — **enhanced** with role-aware redirect on POST |
| `/api/login` | `api_login()` | ✅ AJAX login — **enhanced** with role-aware redirect on success |
| `/logout` | `logout()` | ✅ Unchanged |
| `/dashboard` | `dashboard()` | ✅ Already role-aware redirect — enhanced for three-role routing |

### 2.4 Existing Dashboard Routes (Reused As-Is)

| Route | Handler | Role Guard | Status |
|-------|---------|------------|--------|
| `/student/dashboard` | `student_dashboard()` | `@role_required("student")` | ✅ Exists |
| `/teacher/dashboard` | `teacher_dashboard()` | `@role_required("teacher")` | ✅ Exists |
| `/organizer/dashboard` | `organizer_dashboard()` | `@role_required("organizer")` | ✅ Exists |

### 2.5 Existing `base.html` Sidebar Logic (Reused As-Is)

The template already has role-specific sidebar navigation at:
- `base.html:31` — Dashboard link routes to `student_dashboard`, `organizer_dashboard`, `admin_dashboard`, or `teacher_dashboard` based on `user_role`
- `base.html:36-78` — Student-specific navigation
- `base.html:79-125` — Organizer-specific navigation
- `base.html:126-168` — Admin-specific navigation
- `base.html:169-185` — Teacher (faculty) navigation
- `base.html:186-192` — Fallback/default navigation

The `role_{{ user_role }}` CSS class on `<body>` (base.html:24) already enables role-specific styling.

---

## 3. Registration Flow

```
ACEMS AGC (Landing Page)
    │
    ├── [Landing page "Create Account" button] ──► /register
    │                                                  │
    │                                          Account Type Selection
    │                                          (auth/account_type.html)
    │                                          Three cards: Student / Organizer / Faculty Member
    │                                                  │
    │                              ┌───────────────────┼───────────────────┐
    │                              ▼                   ▼                   ▼
    │                    /register/student    /register/faculty    /register/organizer
    │                    (Student Registration) (Faculty Registration) (Organizer Registration)
    │                              │                   │                   │
    │                              ▼                   ▼                   ▼
    │                    persist_registration_user()  (same function)     (same function)
    │                    Role = "student"            Role = "teacher"    Role = "organizer"
    │                    (unique fields per role)    (unique fields)     (unique fields)
    │                              │                   │                   │
    │                              ▼                   ▼                   ▼
    │                         Password hash once  (same set_password())  (same set_password())
    │                              │                   │                   │
    │                              ▼                   ▼                   ▼
    │                         Redirect to /login  (same /login page)    (same /login page)
    └──────────────────────────────────────────────────────────────────────────────┘
```

### Key Design Decisions — Registration

1. **Single registration persistence**: `persist_registration_user()` (app.py:4254-4337) handles all three role types in one function. The `role` field in the form data drives the internal role mapping. There is **no duplication** of the user creation logic.

2. **Password hashing**: `user.set_password()` (app.py:434-438) is called exactly once per registration, regardless of role. Werkzeug's `generate_password_hash` is the single hashing implementation.

3. **Account type selection page**: Already exists at `/register` (app.py:4340-4355) with `auth/account_type.html` containing three role cards linking to `/register/student`, `/register/faculty`, and `/register/organizer`.

4. **Registration success flow**: All three registration routes redirect to `/login` after success.

---

## 4. Login Flow

### 4.1 Primary Flow: Generic Login with Role-Aware Redirect

```
ACEMS AGC
    │
    ▼
/login  (GET) ──► Render auth/login.html
    │
    │  User submits email + password
    ▼
/login  (POST) ──► Authenticate via single /login handler ──► success?
    │                                                     │
    │                                          ┌──────────┴──────────┐
    │                                          ▼                     │
    │                                   Check user.role             │
    │                                          │                     │
    │                              ┌───────────┼───────────┐          │
    │                              ▼           ▼           ▼          │
    │                         "student"    "teacher"    "organizer"   │
    │                              │           │           │          │
    │                              ▼           ▼           ▼          │
    │                     /student/dashboard  /teacher/dashboard  /organizer/dashboard
```

**The existing `/login` route (app.py:4770-4803) is enhanced** so that after successful authentication, the user is redirected based on their `role`:

```python
# ENHANCEMENT to existing /login POST handler (app.py:4797-4802):
# Replace:
#   return redirect(url_for("dashboard"))
# With role-aware redirect:
role_redirects = {
    "student": "student_dashboard",
    "teacher": "teacher_dashboard",
    "organizer": "organizer_dashboard",
}
redirect_target = role_redirects.get(current_user.role, "dashboard")
return redirect(url_for(redirect_target))
```

**The existing `/api/login` endpoint (app.py:4543-4569) is similarly enhanced**:
```python
# ENHANCEMENT to JSON login success response:
role_redirects = {
    "student": "student_dashboard",
    "teacher": "teacher_dashboard",
    "organizer": "organizer_dashboard",
}
redirect_target = role_redirects.get(current_user.role, "dashboard")
return jsonify({"success": True, "message": "Login successful!", "redirect": url_for(redirect_target)})
```

### 4.2 Alternative Flow: Role-Specific Login Links

```
ACEMS AGC
    │
    ├── [Landing page role cards] ──► /register/student │ /register/faculty │ /register/organizer
    │                                       │                    │                    │
    │                                   After registration, auto-redirect to role-specific login
    │
    ├── [Login page role links] ──► /login/student │ /login/faculty │ /login/organizer
    │                                          │              │              │
    │                                          ▼              ▼              ▼
    │                                   Same /login POST handler
    │                                   (authenticates via email/password)
    │                                          │
    │                                          ▼
    │                                   user.role determines dashboard
    │                                          │
    │                              ┌───────────┼───────────┐
    │                              ▼           ▼           ▼
    │                     student_dashboard  teacher_dashboard  organizer_dashboard
```

**New routes added for role-specific login entry points**:

| Route | Handler | Behavior |
|-------|---------|----------|
| `/login/student` | `student_login_page()` | Renders login with `role_hint=student`; POST → authenticate → redirect to student dashboard |
| `/login/faculty` | `faculty_login_page()` | Renders login with `role_hint=teacher` (internal role); POST → authenticate → redirect to teacher dashboard |
| `/login/organizer` | `organizer_login_page()` | Renders login with `role_hint=organizer`; POST → authenticate → redirect to organizer dashboard |

**These are thin wrappers around the existing `/login` handler logic.** The implementation approach:

```python
# Role-specific login pages are thin wrappers that pass a role_hint to the template.
# The actual authentication is handled by the shared /login POST handler.

@app.route("/login/student", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def student_login_page():
    return _role_specific_login("student", "student_dashboard")

@app.route("/login/faculty", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def faculty_login_page():
    return _role_specific_login("teacher", "teacher_dashboard")

@app.route("/login/organizer", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def organizer_login_page():
    return _role_specific_login("organizer", "organizer_dashboard")
```

The shared helper `_role_specific_login()` renders the same login template with a `role_hint` parameter and a custom success redirect. The POST authentication reuses the exact same logic as `/login`.

### 4.3 Login Template Enhancement

The existing `auth/login.html` is enhanced to accept an optional `role_hint` variable:

```html
<!-- In auth/login.html, add below the form action: -->
{% if role_hint %}
<input type="hidden" name="role_hint" value="{{ role_hint }}">
{% endif %}
```

On successful login, the handler checks for `role_hint` in form data first (for role-specific login links), then falls back to `user.role` for the generic login.

---

## 5. Dashboard Routing & Access Control

### 5.1 Dashboard Redirect Chain

```
User logs in successfully
    │
    ▼
/login POST handler
    │
    ├── role_hint in POST? ──► Use role_hint for redirect target
    │
    └── No role_hint? ──► Check user.role
            │
            ├── "student"   ──► /student/dashboard
            ├── "teacher"   ──► /teacher/dashboard
            ├── "organizer" ──► /organizer/dashboard
            ├── "admin"     ──► /admin/dashboard  (existing)
            ├── "volunteer" ──► /volunteer/dashboard  (existing)
            └── other       ──► /dashboard (fallback)
```

### 5.2 `/dashboard` Route Enhancement

The existing `/dashboard` route (app.py:4875-4886) already performs role-based redirects. It is updated to be explicit about the three primary roles:

```python
# Current (app.py:4875-4886) — already functional, documented here for completeness:
@app.route("/dashboard")
@login_required
def dashboard():
    if current_user.role == "admin":
        return redirect(url_for("admin_dashboard"))
    if current_user.role == "organizer":
        return redirect(url_for("organizer_dashboard"))
    if current_user.role == "volunteer":
        return redirect(url_for("volunteer_dashboard"))
    if current_user.role == "teacher":
        return redirect(url_for("teacher_dashboard"))
    return redirect(url_for("student_dashboard"))
```

This already correctly handles all roles. No change required — it's documented here as the canonical routing table.

### 5.3 Wrong-Dashboard Access Denial

Every dashboard route is guarded by `@role_required` which returns HTTP 403:

```python
@app.route("/student/dashboard")
@role_required("student")   # Only students can access
def student_dashboard(): ...

@app.route("/teacher/dashboard")
@role_required("teacher")   # Only faculty can access
def teacher_dashboard(): ...

@app.route("/organizer/dashboard")
@role_required("organizer")  # Only organizers can access
def organizer_dashboard(): ...
```

**The `role_required` decorator** (app.py:1575-1584):
```python
def role_required(*roles):
    def decorator(fn):
        @wraps(fn)
        @login_required
        def wrapper(*args, **kwargs):
            if current_user.role not in roles:
                abort(403)  # Access denied — user is not the correct role
            return fn(*args, **kwargs)
        return wrapper
    return decorator
```

When a user attempts to access a dashboard for the wrong role, the decorator aborts with HTTP 403. The user is **not** redirected to the correct dashboard (to avoid confusing them with an silent redirect) — instead they receive a clear 403 Forbidden response. The Flask error handler for 403 should render a friendly error page.

**Flow for wrong-dashboard access**:

```
User with role "student" attempts to access /teacher/dashboard
    │
    ▼
@role_required("teacher") decorator fires
    │
    ├── current_user.role == "student" ──► NOT in ("teacher")
    │
    ▼
abort(403) ──► Error 403 page rendered
    │
    ▼
User is NOT redirected silently (prevents confusion)
    │
    ▼
User sees "403 — Access Forbidden" page
    Option: Include a link back to /dashboard which redirects to student_dashboard
```

---

## 6. Complete Route Architecture

### 6.1 Route Map

```
# ============ PUBLIC ============
/                     → Landing page (unchanged)
/login                → Generic login page (enhanced: role-aware redirect on POST)
/login/student        → Student-specific login entry (NEW wrapper)
/login/faculty        → Faculty-specific login entry (NEW wrapper)
/login/organizer      → Organizer-specific login entry (NEW wrapper)
/register             → Account type selection (unchanged)
/register/student     → Student registration (unchanged)
/register/faculty     → Faculty registration (unchanged, maps to "teacher" role)
/register/organizer   → Organizer registration (unchanged)
/api/login            → AJAX login (enhanced: role-aware redirect)
/api/register         → AJAX registration (unchanged)
/api/register/validate-step → Multi-step validation (unchanged)
/logout               → Logout (unchanged)

# ============ DASHBOARDS (role-gated) ============
/dashboard            → Role-aware redirect (enhanced documentation, no code change)
/student/dashboard    → Student dashboard (@role_required("student"))
/teacher/dashboard    → Faculty dashboard (@role_required("teacher"))
/organizer/dashboard  → Organizer dashboard (@role_required("organizer"))
/admin/dashboard      → Admin dashboard (unchanged, @role_required("admin"))
/volunteer/dashboard  → Volunteer dashboard (unchanged, @role_required)

# ============ ALL OTHER ROUTES ============
# All existing event, registration, profile, admin, etc. routes
# remain COMPLETELY UNCHANGED.
```

### 6.2 Route Priority & Conflict Prevention

| Concern | Solution |
|---------|----------|
| `/login` vs `/login/student` etc. | Flask routes are matched by specificity; `/login/student` matches only when the path is exactly `/login/student`. `/login` matches the base path. No conflict. |
| `/register` vs `/register/student` | Same as above — specific paths take priority. |
| Dashboard redirect chain | `/dashboard` always redirects before rendering; never serves content directly for authenticated users. |
| Role confusion (teacher vs faculty) | Internal role value is `teacher` for faculty members. All code references this consistently. The display label "Faculty Member" is used in UI only. |

---

## 7. Security Architecture

### 7.1 Single Authentication Chain

```
┌─────────────────────────────────────────────────────┐
│                 Flask-Login (Session)                │
│  login_user() / logout_user() / current_user         │
│  @login_required decorator                          │
│  Session cookies managed centrally                  │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│              Password Security (Werkzeug)            │
│  generate_password_hash() / check_password_hash()    │
│  SINGLE implementation — no per-role duplication     │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│              Role Authorization (Single Decorator)   │
│  @role_required("student") / ("teacher") /          │
│  ("organizer") / ("admin") / ("volunteer")          │
│  Checks current_user.role — one check per request   │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│               CSRF Protection (Flask-WTF)            │
│  csrf_token on all forms                            │
│  @csrf_exempt only where explicitly needed          │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│               Rate Limiting (Flask-Limiter)          │
│  /login: 10/min  /register: 5/hr  /api/login: 10/min│
│  Applied per-route, not per-role                    │
└─────────────────────────────────────────────────────┘
```

### 7.2 What Is NOT Duplicated

| Concern | Implementation |
|---------|---------------|
| Password hashing | `User.set_password()` / `User.check_password()` — single method on User model |
| Session management | Flask-Login `login_user()` / `logout_user()` — single global instance |
| Role check | `@role_required(*roles)` — single decorator, parameterized |
| User loading | `load_user(user_id)` — single loader registered with `@login_manager.user_loader` |
| Login logic | `login()` — single POST handler with role-aware redirect |
| Registration persistence | `persist_registration_user()` — single function |
| CSRF | Flask-WTF `csrf` — single app-wide instance |
| Rate limiting | Flask-Limiter `limiter` — single app-wide instance |

---

## 8. Session & State Management

### 8.1 Login Flow (Unified)

```python
# Both /login (generic) and /login/{student,faculty,organizer} (specific) converge here.
# 1. Validate credentials (same for all roles)
# 2. Check account_status (suspended/disabled — same for all roles)
# 3. Call login_user(user, remember=...) — same Flask-Login call
# 4. Record login timestamp (same)
# 5. Commit session (same)
# 6. Redirect based on role (role-specific, but using same mechanism)
```

### 8.2 Session Expiry & Logout

- Flask-Login "remember me" is supported via `remember=bool(request.form.get("remember"))` (login.html line 35) — unchanged.
- `/logout` calls `logout_user()` — unchanged, works for all roles.
- Account suspension/disablement is checked at login time via `AccountStatus` enum — unchanged.

---

## 9. Implementation Plan

### Phase 1: Minimal Enhancements (No New Files)

These changes make the existing architecture fully compliant with the requirements.

**Change 1 — Enhanced `/dashboard` redirect** (app.py:4875-4886):
- **No code change needed** — already correctly routes all three primary roles to their dashboards.

**Change 2 — Enhanced `/login` POST handler** (app.py:4797-4802):
- Replace `return redirect(url_for("dashboard"))` with role-aware redirect using a mapping dictionary.
- This means Student Login → Student Dashboard, Faculty Login → Faculty Dashboard, Organizer Login → Organizer Dashboard.

**Change 3 — Enhanced `/api/login` success response** (app.py:4568-4569):
- Replace `url_for("dashboard")` with role-aware redirect in JSON response.

**Change 4 — Enhanced `auth/login.html`**:
- Add optional `role_hint` hidden input when template is rendered with `role_hint` context variable.
- Add role-specific login links on the login page (text links or buttons) for `/login/student`, `/login/faculty`, `/login/organizer`.

### Phase 2: Role-Specific Login Entry Points

**Change 5 — Add three new route handlers** (app.py, after existing `/login`):
- `/login/student` → renders login with `role_hint="student"`, success → `student_dashboard`
- `/login/faculty` → renders login with `role_hint="teacher"`, success → `teacher_dashboard`
- `/login/organizer` → renders login with `role_hint="organizer"`, success → `organizer_dashboard`

Implementation: Use a shared `_render_login(role_hint, success_redirect)` helper that calls the same auth logic as `/login` but with pre-configured redirect target.

**Change 6 — Create `auth/role_login.html` template** (or enhance `auth/login.html`):
- Inherits from `base.html`
- Accepts `role_hint` and `success_redirect` context variables
- Pre-fills/hides role information if appropriate
- Same form fields (email, password) — no role-specific fields needed since email uniquely identifies the user

### Phase 3: Access Control Verification

**Change 7 — Verify all dashboard routes** have `@role_required` guard:
- `/student/dashboard` ✅ — already has `@role_required("student")`
- `/teacher/dashboard` ✅ — already has `@role_required("teacher")`
- `/organizer/dashboard` ✅ — already has `@role_required("organizer")`

**Change 8 — Add 403 error handler** (if not already present):
- Render a user-friendly "Access Denied" page when `abort(403)` is triggered
- Include a link to `/dashboard` so the user can safely navigate to their correct dashboard

### Phase 4: Landing Page Links (UI — Not Implemented per Requirements)

The architecture assumes the landing page (`landing.html`) contains links to:
- `/login/student` — "Student Login"
- `/login/faculty` — "Faculty Login"
- `/login/organizer` — "Organizer Login"
- `/register/student`, `/register/faculty`, `/register/organizer` — (already present via `/register`)

These UI changes are **out of scope** per the requirement: "Do not implement the UI yet."

---

## 10. Data Model Impact

**No database changes required.**

The existing `User` model already supports all required roles:

```python
# app.py:412-455 (User model — unchanged)
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(160), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(30), default="student")
    # ... other fields
```

The `role` column stores `"student"`, `"teacher"`, or `"organizer"` as needed. The `Role` model in `cems/domain.py` (used for the `role` table/seed data) also already has entries for all three roles:

```python
# app.py:2194-2199 (seed data — unchanged)
roles = [
    Role(name="student", description="Campus student"),
    Role(name="organizer", description="Event organizer"),
    Role(name="admin", description="Platform administrator"),
    Role(name="teacher", description="Faculty member"),
    Role(name="volunteer", description="Event volunteer"),
]
```

---

## 11. Relationship to Existing System

### 11.1 What Is Preserved

| Existing Feature | Impact |
|-----------------|--------|
| All event management routes | **Zero changes** |
| All registration routes (events) | **Zero changes** |
| All admin routes | **Zero changes** |
| All teacher/faculty routes | **Zero changes** |
| All student routes | **Zero changes** |
| All volunteer routes | **Zero changes** |
| All templates (except enhanced login) | **Zero changes** |
| Password hashing | **Zero changes** — single Werkzeug implementation |
| Session management | **Zero changes** — single Flask-Login instance |
| CSRF protection | **Zero changes** |
| Rate limiting | **Zero changes** |
| Database schema | **Zero changes** |
| All other UI templates | **Zero changes** |

### 11.2 What Is Added

| Addition | Location | Purpose |
|----------|----------|---------|
| 3 route handlers | `app.py` (after `/login`) | Role-specific login entry points |
| Role-aware redirect in `/login` POST | `app.py:4797-4802` | Direct to correct dashboard after login |
| Role-aware redirect in `/api/login` | `app.py:4568-4569` | Correct redirect in AJAX response |
| `role_hint` support in login template | `templates/auth/login.html` | Visual + functional role selection |
| 403 error page (if missing) | `templates/errors/403.html` | Friendly access denied page |

### 11.3 What Is Modified (Minimally)

| Modification | File | Nature |
|-------------|------|--------|
| Dashboard redirect mapping | `app.py` `/login` POST handler | Logic enhancement — adds role→dashboard mapping |
| API login redirect | `app.py` `/api/login` success path | Logic enhancement — adds role→dashboard mapping |
| Login template | `templates/auth/login.html` | Add role hint input + role login links |

---

## 12. Error Handling

### 12.1 Invalid Role Login Attempt

```
User visits /login/nonexistent
    │
    ▼
Flask 404 (no route matches)
    │
    ▼
Existing 404 handler renders error page
```

### 12.2 Wrong Dashboard Access

```
User with role "student" visits /teacher/dashboard
    │
    ▼
@role_required("teacher") checks current_user.role
    │
    ├── "student" not in ("teacher",) → abort(403)
    │
    ▼
403 Forbidden page displayed
    │
    ▼
Link to /dashboard provided (redirects to /student/dashboard)
```

### 12.3 Failed Authentication

```
User submits wrong password on /login, /login/student, /login/faculty, or /login/organizer
    │
    ▼
Same error handling — "Invalid email or password."
    │
    ▼
User stays on same page with error message (no redirect to any dashboard)
```

---

## 13. Summary: What Changes vs. What Stays

### Stays (Unchanged)
- All existing routes except `/login` POST handler and `/api/login` success response
- All templates except `auth/login.html` (minor enhancement only)
- All database models and schema
- All password hashing, session management, CSRF, rate limiting
- All event management, registration, admin, student, faculty, volunteer functionality
- The `base.html` sidebar role-switching logic
- The `dashboard()` redirect function

### Changes
| File | Change Type | Description |
|------|-------------|-------------|
| `app.py` | **Logic enhancement** | `/login` POST: redirect to role-specific dashboard instead of generic `/dashboard` |
| `app.py` | **Logic enhancement** | `/api/login` success: return role-specific redirect URL |
| `app.py` | **Add** | 3 new route handlers: `/login/student`, `/login/faculty`, `/login/organizer` |
| `templates/auth/login.html` | **Enhancement** | Add hidden `role_hint` input; add links to role-specific login pages |
| `templates/errors/403.html` | **Add** (if missing) | Friendly "Access Denied" page |

### Not Implemented (Per Requirements)
- All UI templates for student/faculty/organizer dashboards (already exist in the codebase but UI changes are out of scope)
- New registration pages (already exist)
- Landing page navigation changes (UI change, out of scope)
- Any changes to event management functionality

---

## Appendix A: Complete Authentication Flow Diagram

```
╔══════════════════════════════════════════════════════════════════╗
║                    ACEMS AGC AUTH SYSTEM                         ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║  ┌──────────┐     ┌──────────────┐     ┌─────────────────────┐  ║
║  │ Landing  │────▶│  /register   │────▶│ Account Type Select │  ║
║  │  Page    │     │              │     │  /register          │  ║
║  └──────────┘     └──────────────┘     └────────┬────────────┘  ║
║                                                   │               ║
║                          ┌────────────────────────┤               ║
║                          ▼                        ▼               ║
║                   ┌──────────────┐      ┌──────────────┐        ║
║                   │/register/student│  │/register/faculty│       ║
║                   │(role=student) │      │(role=teacher) │       ║
║                   └──────┬───────┘      └──────┬───────┘       ║
║                          │                     │               ║
║                          │  ┌──────────────┐   │               ║
║                          │  │/register/organ│◀─┘               ║
║                          │  │(role=organizer)│                  ║
║                          │  └──────┬───────┘                   ║
║                          │         │                           ║
║                          ▼         ▼                           ║
║                   ┌─────────────────────┐                      ║
║                   │persist_registration │                      ║
║                   │_user() [shared]     │                      ║
║                   │Password hash [once] │                      ║
║                   └──────────┬──────────┘                      ║
║                              │                                 ║
║                              ▼                                 ║
║                   ┌─────────────────────┐                      ║
║                   │ Redirect to /login  │                      ║
║                   └──────────┬──────────┘                      ║
║                              │                                 ║
║                              ▼                                 ║
║                   ┌─────────────────────┐                      ║
║     ┌───────────▶ │    /login (GET)     │                      ║
║     │             │  or /login/{role}   │                      ║
║     │             └──────────┬──────────┘                      ║
║     │                        │                                 ║
║     │     ┌──────────────────┤                                 ║
║     │     ▼                  ▼                                  ║
║     │  /login/student    /login/faculty  (role-specific)        ║
║     │  /login/organizer                      │                  ║
║     │                                   (generic)             ║
║     │                        │                                ║
║     │                        ▼                                ║
║     │             ┌─────────────────────┐                      ║
║     │             │ /login (POST)       │                      ║
║     │             │ @limiter.limit(10/min)│                     ║
║     │             │ @login_required? No │                      ║
║     │             └──────────┬──────────┘                      ║
║     │                        │                                 ║
║     │                        ▼                                 ║
║     │             ┌─────────────────────┐                      ║
║     └─────────────│  Authenticate:      │                      ║
║         (from     │  - User.query by    │                      ║
║          API/     │    email             │                      ║
║          links)   │  - check_password() │                      ║
║                    │  - AccountStatus    │                      ║
║                    │  - login_user()     │                      ║
║                    │  - record_login()   │                      ║
║                    └──────────┬──────────┘                      ║
║                               │                                 ║
║                               ▼                                 ║
║                    ┌─────────────────────┐                      ║
║                    │ Role-based redirect │                      ║
║                    │                     │                      ║
║                    │ student → /student/ │                      ║
║                    │         dashboard   │                      ║
║                    │                     │                      ║
║                    │ teacher → /teacher/ │                      ║
║                    │         dashboard   │                      ║
║                    │                     │                      ║
║                    │ organizer → /       │                      ║
║                    │         organizer/  │                      ║
║                    │         dashboard   │                      ║
║                    └──────────┬──────────┘                      ║
║                               │                                 ║
║                               ▼                                 ║
║                    ┌─────────────────────┐                      ║
║                    │  Role-gated          │                      ║
║                    │  Dashboard           │                      ║
║                    │  @role_required()    │                      ║
║                    │  Active Session      │                      ║
║                    └─────────────────────┘                      ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝
```

---

## Appendix B: Role → Dashboard → Access Control Matrix

| Route | @role_required | Student | Faculty (teacher) | Organizer | Admin |
|-------|---------------|---------|-------------------|-----------|-------|
| `/student/dashboard` | `"student"` | ✅ Access | ❌ 403 | ❌ 403 | ❌ 403 |
| `/teacher/dashboard` | `"teacher"` | ❌ 403 | ✅ Access | ❌ 403 | ❌ 403 |
| `/organizer/dashboard` | `"organizer"` | ❌ 403 | ❌ 403 | ✅ Access | ❌ 403 |
| `/dashboard` | `"student","teacher","organizer","admin","volunteer"` | ✅ Auto-redirect | ✅ Auto-redirect | ✅ Auto-redirect | ✅ Auto-redirect |

---

*Document version: 1.0*
*Based on existing CEMS AGC codebase at commit state as of analysis date.*
