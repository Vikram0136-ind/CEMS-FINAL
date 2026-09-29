# Campus Event Management System — Amritsar Group of Colleges

A GitHub-ready full-stack college project built with **HTML, CSS, JavaScript, Flask and SQLite**.

## Main roles
- Student / Participant
- Event Organizer
- Admin

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
