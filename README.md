# Campus Event Management System — Amritsar Group of Colleges

A GitHub-ready full-stack college project built with **HTML, CSS, JavaScript, Flask and SQLite**.

## Main roles
- Student — register, discover events, tickets (QR), certificates, notices
- Organizer — create events (draft / submit for approval), reports, check-in, QR scanner, volunteers/judges/sponsors
- Faculty — create an account, coordinate events, mark attendance, complete events, post notices
- Admin — approve events, manage users, venues, notices

## Included modules
- Landing page and upcoming events
- Registration + email verification workflow
- Login / logout / forgot-password workflow
- Role-based dashboards
- Event search, filters and event details
- Free and paid-event registration with a safe demo payment flow
- Digital ticket with QR code
- Organizer event creation and management
- Registration approval/rejection
- Event-day check-in by ticket code
- Notifications
- Attendance records
- Feedback and ratings
- Certificate PDF generation
- Organizer reports and analytics
- Admin user/event management
- Venue management + volunteer, judge and sponsor management
- Responsive UI matching the supplied CEMS reference screens

## Extended modules (departments, competitions, community)

| Area | Where | Who |
| --- | --- | --- |
| Department-wise dashboard (registrations, attendance ratio, winners, points; batch / semester / odd-even filters) | `/dashboard/departments` | admin, organizer, faculty |
| Date-to-date report with time-of-day, department, batch, semester and odd/even filters + CSV export | `/reports/date-range` | admin, organizer, faculty |
| Event lists: all / past / present (today) / future | `/events?when=all\|past\|present\|future` | everyone |
| Department leaderboard, most-registered events, best attendance, which department performed in which event, top students | `/leaderboard` | all signed-in users |
| Wishlist / saved events and registration-deadline countdown | event page, `/wishlist` | signed-in users |
| Event reminders (24 h, event day, deadline) and instant cancellation / reschedule notifications | automatic | students, faculty, organizers |
| Waitlist with automatic promotion when a seat opens or a registration is cancelled | register page, `/events/<id>/waitlist` | students |
| Team registration with team leader, invite codes, min/max team size | register page, `/events/<id>/team` | students |
| Duplicate student-ID / roll-number detection (sign-up, registration, report) | `/duplicates` | admin, organizer |
| Entry / exit time tracking with time-inside per participant | `/entry-exit` | admin, organizer, faculty |
| Faculty attendance history and faculty-wise event reports | `/faculty/attendance-history`, `/reports/faculty` | faculty, admin, organizer |
| Rounds, judge panel, judge score entry, automatic winner calculation, multiple winner categories, winner panel | `/events/<id>/competition`, `/judge` | organizer, admin, faculty judges |
| Separate participation and winner certificates (both verifiable) | `/student/certificates` | students |
| Student achievement points (+10 attend, +50/+35/+25 for 1st/2nd/3rd, +20 other winner categories) | `/student/achievements` | students |
| Campus chatbot (floating 💬 on every page) and community Q&A that students, organizers and faculty answer together | `/community`, `/assistant` | all roles |

Reminders are sent by a throttled background check on normal traffic. To run them on a schedule (recommended in production) add a cron job that calls

```bash
flask --app app send-reminders
```

Existing databases are upgraded automatically on start-up (new tables and columns are added; nothing is dropped).

## Quick start (macOS / Linux)

```bash
cd CEMS-AGC
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env   # then set SECRET_KEY
python app.py
```

Open http://127.0.0.1:5001 (port 5000 is taken by AirPlay on macOS; override with `PORT`). Run tests with `pytest`.

## Production notes

- `SECRET_KEY` is required when `FLASK_ENV=production`.
- Demo accounts and demo payments are on by default in development only. Set `SEED_DEMO_DATA=false` and `ALLOW_DEMO_PAYMENTS=false` in production (already set in `render.yaml`).
- Set `MAIL_SERVER` (and `MAIL_PORT`, `MAIL_USERNAME`, `MAIL_PASSWORD`) to send password-reset emails; otherwise the link is written to the server log.
- Use a shared `RATE_LIMIT_STORAGE_URI` (e.g. Redis) when running several workers.

## Quick start — Windows

```powershell
cd CEMS-AGC
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python app.py
```

Open: http://127.0.0.1:5001

## Demo accounts (development only)

- Admin: `admin@agc.local` / `Admin@123`
- Organizer: `organizer@agc.local` / `Organizer@123`
- Student: `student@agc.local` / `Student@123`
- Faculty: `teacher@agc.local` / `Teacher@123`

Students, organizers and faculty can also create their own accounts at `/register`. Demo event dates are generated relative to the first run.

The app creates the database and demo data automatically on first run.

## Email verification / password reset

For local college demo use, SMTP is optional. When SMTP variables are blank, the verification/reset URL is printed in the Flask terminal.

For real email, fill the SMTP values in `.env`.

## GitHub

```bash
git init
git add .
git commit -m "Initial Campus Event Management System"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/campus-event-management-agc.git
git push -u origin main
```

Do not commit `.env` or `instance/cems.db`.

## Important

This project intentionally uses a **demo payment flow**. It does not collect real card/UPI credentials. For a production deployment, connect an approved payment provider and move secrets to environment variables.

## Project structure

```text
CEMS-AGC/
├── app.py
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md
├── instance/
├── static/
│   ├── css/style.css
│   ├── js/app.js
│   └── uploads/
└── templates/
    ├── base.html
    ├── landing.html
    ├── auth/
    ├── student/
    ├── organizer/
    ├── admin/
    └── errors/
```

## AGC Institutional Customization
The landing page and seed data are customized for Amritsar Group of Colleges (AGC) using the institutional information supplied for this academic project. It includes AGC branding language, autonomous status, NAAC A Grade, AICTE/PCI references, IKGPTU affiliation, IQAC/ISO/NPTEL/AISHE references, campus modules, contact-directory sections, and AGC-focused sample events.

> Note: institutional statistics and notices shown in the demo are based on the supplied project/reference content and should be re-verified against the college's current official material before production use.
