# Faculty Module Development Roadmap

**CEMS — Campus Event Management System**
Generated: 2026-09-20

---

## Executive Summary

**15 features** to implement across 4 logical categories. Of these:
- **2** already have database models + partial UI (need enhancement)
- **5** have partial models/data structures (need full implementation)
- **4** need full-stack implementation (models → routes → templates)
- **4** are UI/navigation enhancements on existing backends

---

## Category A: Core Faculty Event Operations (Priority: 🔴 HIGH)
*These are the day-to-day tools faculty need to manage their events.*

### A1. Winner & Result Management — ⏱️ 3-4 days | Priority: HIGH

**Current State:** ✅ Partially implemented
- `InterCollegeEvent` DB model has `winner`, `runner_up`, `third_place` fields
- `Event` model has `results` (Text) field
- Templates exist: `faculty/event_completion.html`, `faculty/completed_events.html`, `faculty/event_summary.html`
- Faculty sidebar has "Completed Events" and "Event Completion" routes

**Gap:** No dedicated winner entry form, no result publishing workflow, no result verification for inter-college competitions.

**Implementation Plan:**
1. Create `templates/faculty/winners.html` — Result entry form per event (winner, runner-up, third-place, scores, judge votes)
2. Add `templates/faculty/result_verification.html` — Verify and publish results
3. Extend `InterCollegeEvent` model with `score_details` (JSON), `verified_by`, `verified_at` fields
4. Add routes: `faculty_event_winners(event_id)`, `faculty_submit_results(event_id)`, `faculty_verify_results(event_id)`
5. Add "Results" tab on event details for faculty
6. Student-facing results display on event details page

---

### A2. Task Management for Events — ⏱️ 2-3 days | Priority: HIGH

**Current State:** ✅ Partial — `EventTask` model exists
- Fields: `event_id`, `assigned_to`, `title`, `description`, `status`, `priority`, `due_date`
- No dedicated task UI for faculty

**Gap:** No task board, no task creation/assignment UI, no task tracking for event preparation.

**Implementation Plan:**
1. Create `templates/faculty/event_tasks.html` — Kanban-style task board per event
2. Add task creation modal/form (title, assignee, priority, due date, description)
3. Add task status transitions: pending → in_progress → completed
4. Add task filtering by status and priority
5. Dashboard widget showing overdue tasks for faculty
6. Email notifications on assignment and completion
7. Routes: `faculty_event_tasks(event_id)`, `faculty_create_task(event_id)`, `faculty_update_task(task_id)`

---

### A3. Incident Reporting During Events — ⏱️ 2-3 days | Priority: HIGH

**Current State:** ✅ Partial — `EventEmergency` model exists
- Fields: `event_id`, `alert_type`, `severity`, `description`, `response_team`, `resolved`, `resolution_time`
- No incident reporting UI

**Gap:** No incident reporting form, no incident log/monitoring, no escalation workflow.

**Implementation Plan:**
1. Create `templates/faculty/incident_report.html` — Incident report form (type, severity, description, response team assignment)
2. Create `templates/faculty/incident_log.html` — Log of all incidents per event with filtering
3. Add escalation: severity "critical" auto-notifies admin
4. Add incident resolution workflow: open → in_progress → resolved → closed
5. Add statistics widget on faculty dashboard: open incidents by severity
6. Routes: `faculty_report_incident(event_id)`, `faculty_incident_log(event_id)`, `faculty_resolve_incident(incident_id)`

---

### A4. Guest Management Module — ⏱️ 2-3 days | Priority: MEDIUM-HIGH

**Current State:** ✅ Partial — `VIPGuestManagement` DB model exists
- Fields: `event_id`, `guest_name`, `guest_type`, `special_requirements`, `arrival_time`, `dedicated_handler`
- `Event` model has `main_guest`, `chief_guest` (String fields)
- No dedicated guest management UI

**Gap:** No guest registration form, no guest checklist, no check-in for guests, no VIP concierge view.

**Implementation Plan:**
1. Create `templates/faculty/guests.html` — Guest management page per event
2. Guest registration form: name, type (keynote, judge, sponsor, VIP, faculty), special requirements, arrival time
3. Guest check-in tracking (arrived, seated, departed)
4. Dedicated handler assignment per guest
5. Guest list export (CSV)
6. Add guest count to event sidebar/summary
7. Routes: `faculty_manage_guests(event_id)`, `faculty_add_guest(event_id)`, `faculty_update_guest(guest_id)`

---

### A5. Equipment/Resource Requests for Faculty — ⏱️ 2-3 days | Priority: MEDIUM-HIGH

**Current State:** ✅ Partial — `Resource` model (campus resources), `EquipmentInventory` model (per-event equipment), `EventResource` model (documents/media) all exist
- `Resource` has booking system with availability tracking
- `EquipmentInventory` tracks event-specific items with return status

**Gap:** No faculty-facing request workflow for requesting resources/equipment for their events.

**Implementation Plan:**
1. Create `templates/faculty/resource_requests.html` — Request form (select resource, quantity, date range, justification)
2. Create `templates/faculty/my_requests.html` — Track submitted requests (pending, approved, denied, fulfilled)
3. Add request lifecycle: submitted → approved → reserved → picked_up → returned → closed
4. Add admin approval workflow for resource requests
5. Notification on approval/denial
6. Add "Request Resources" button on event creation/edit pages
7. Routes: `faculty_request_resource(event_id)`, `faculty_my_requests()`, `faculty_approve_request(request_id)` (admin)

---

## Category B: Faculty Productivity & Visibility (Priority: 🟡 MEDIUM)
*These tools help faculty track their workload and schedule.*

### B1. Faculty Calendar View — ⏱️ 3-4 days | Priority: HIGH

**Current State:** ✅ Organizer has `festival_calendar` route/template
- Teacher sidebar does NOT have a calendar entry
- No faculty-specific calendar

**Gap:** Faculty need a personal calendar showing their assigned/coordinated events.

**Implementation Plan:**
1. Create `templates/teacher/calendar.html` — Monthly calendar view
2. Display faculty's assigned events (from `EventFaculty` or `OrganizerProfile`)
3. Color-code by event category/status
4. Click event → event details
5. Add week and day view toggles
6. Add navigation arrows for month browsing
7. Show event stats (registrations, volunteers, etc.) on event hover/click
8. Routes: `teacher_calendar()`, `teacher_calendar_ajax(year, month)` (JSON API for events)

---

### B2. Faculty Workload Dashboard — ⏱️ 3-4 days | Priority: MEDIUM

**Current State:** ✅ Teacher dashboard (`teacher/dashboard.html`) shows basic stats:
- Total Assigned Events, Total Registrations, Pending Registrations, Approved Students, Total Attendance, Certificates Generated

**Gap:** No workload breakdown by event, no time commitment tracking, no resource allocation view.

**Implementation Plan:**
1. Create `templates/teacher/workload.html` — Dedicated workload page
2. Workload breakdown per event:
   - Pre-event tasks (setup, coordination, communication)
   - During-event duties (check-in, supervision, troubleshooting)
   - Post-event tasks (cleanup, reporting, certificate distribution)
3. Visual timeline/Gantt-style view showing faculty commitments
4. Workload intensity indicator (low/medium/high/overloaded)
5. Time estimates vs. actual time spent tracking
6. "My Shifts" view showing daily/weekly schedule
7. Integration with `VolunteerAssignment` to show faculty oversight load
8. Routes: `teacher_workload()`, `teacher_workload_event(event_id)`

---

### B3. Enhance Faculty Analytics Dashboard — ⏱️ 3-5 days | Priority: MEDIUM

**Current State:** ✅ Teacher has `reports.html` (Registration Report)
- Shows registration counts by status (pending, approved, rejected, waitlisted)
- Event selector for filtering
- Basic table view

**Gap:** No holistic analytics (attendance trends, engagement, feedback summaries, comparison across events, volunteer analytics).

**Implementation Plan:**
1. Create `templates/teacher/analytics.html` — Enhanced analytics page
2. Dashboard widgets:
   - Registration trend chart (line chart over weeks)
   - Attendance rate by event (bar chart)
   - Feedback sentiment summary (positive/neutral/negative)
   - Volunteer hours contributed per event
   - Certificate issuance rate
3. Event comparison table (side-by-side metrics)
4. Date range filter
5. Export analytics to CSV/PDF
6. Integration with existing `EventAnalytics`, `FeedbackSentiment`, `AttendancePredictor` models
7. Routes: `teacher_analytics()`, `teacher_analytics_api(event_id)` (JSON data)

---

### B4. Update Teacher Dashboard Sidebar — ⏱️ 0.5 day | Priority: MEDIUM

**Current State:** ✅ Teacher sidebar in `base.html` has:
- Dashboard, Assigned Events, Attendance, Notifications, Certificates, Reports, Kiosk, Profile, Logout

**Gap:** Missing entries for new modules (Calendar, Workload, Tasks, Volunteers, Guests, Resources). Also, `teacher/dashboard.html` sidebar differs from `base.html` sidebar — the HTML template hardcodes its own sidebar items.

**Implementation Plan:**
1. Align `templates/teacher/dashboard.html` sidebar with `base.html` (or replace hardcoded sidebar with base template inheritance)
2. Add new sidebar items to `base.html` teacher section:
   - 📅 Calendar → `teacher_calendar`
   - 📊 Workload → `teacher_workload`
   - 📋 Tasks → (per-event, contextual)
   - 👥 Volunteers → (coordinator view)
   - 👤 Guests → (per-event, contextual)
3. Remove hardcoded sidebar in `teacher/dashboard.html` and use `{% extends "base.html" %}` navigation

---

## Category C: Student & Document Verification (Priority: 🟡 MEDIUM)
*Processes for verifying student participation and document authenticity.*

### C1. Student Eligibility Verification — ⏱️ 2-3 days | Priority: MEDIUM

**Current State:** ✅ Partial — `Event` model has `eligibility` (Text) field
- No verification workflow
- `EventFaculty` links faculty to events (can be used as eligibility context)

**Gap:** No structured eligibility rules, no verification form, no eligibility status tracking per student.

**Implementation Plan:**
1. Extend `Event` model: add `eligibility_rules` (JSON) with structured fields:
   - `min_semester`, `max_semester`, `departments_allowed` (JSON), `gpa_minimum`, `custom_rules` (Text)
2. Create `templates/student/eligibility_check.html` — Student self-check eligibility before registering
3. Create `templates/faculty/eligibility_review.html` — Faculty review panel for eligibility exceptions
4. Add eligibility verification step in registration flow (pre-registration check)
5. Add API endpoint: `GET /api/events/<id>/eligibility?student_id=X` → returns eligible/ineligible/reasons
6. Routes: `student_eligibility_check(event_id)`, `faculty_eligibility_review(event_id)`

---

### C2. Document Verification for Events — ⏱️ 2-3 days | Priority: MEDIUM

**Current State:** ✅ Partial — `EventApprovalWorkflow` has `required_documents` (JSON)
- `Event` has `documents_json` field
- No verification UI

**Gap:** No document upload interface, no verification checklist, no approval workflow for documents.

**Implementation Plan:**
1. Create `templates/faculty/document_upload.html` — Upload event documents (rules, proofs, forms)
2. Create `templates/faculty/document_review.html` — Review/verify documents checklist
3. Create `templates/student/submit_documents.html` — Student document submission
4. Document status tracking: uploaded → under_review → approved → rejected
5. Auto-notify on document status changes
6. Document type classification (rules, eligibility proof, safety forms, etc.)
7. Routes: `faculty_upload_documents(event_id)`, `faculty_review_documents(event_id)`, `student_submit_documents(event_id)`

---

## Category D: Engagement & Communication (Priority: 🟢 STANDARD)
*Features that improve faculty-student-stakeholder interaction.*

### D1. Feedback on Volunteers — ⏱️ 2-3 days | Priority: MEDIUM

**Current State:** ✅ Partial — `VolunteerPerformance` model exists (rating, attendance, hours, feedback, skills)
- `VolunteerAssignment` model tracks assignments
- `Feedback` model exists (event feedback from students, separate from volunteer feedback)
- Organizer has `volunteer_management.html`

**Gap:** No structured feedback submission for volunteers, no feedback aggregation per volunteer.

**Implementation Plan:**
1. Create `templates/faculty/volunteer_feedback.html` — Per-volunteer feedback form per event
2. Feedback fields: overall rating (1-5), punctuality, professionalism, skills demonstrated, comments
3. Create `templates/faculty/volunteer_feedback_summary.html` — Aggregated feedback per volunteer
4. Auto-trigger feedback request after event completion
5. Feedback anonymity option
6. Feedback statistics: average rating, trend over events
7. Routes: `faculty_volunteer_feedback(event_id, volunteer_id)`, `faculty_volunteer_feedback_summary(event_id, volunteer_id)`

---

### D2. Enhance Certificate Management (bulk, types, verification) — ⏱️ 4-5 days | Priority: MEDIUM

**Current State:** ✅ Partial — `DigitalCertificate` model exists (certificate_code, achievement, verified, verification_code)
- Teacher has `certificates.html` (certificate listing per event)
- Teacher has `certificate_preview.html`
- `verify_certificate.html` exists (certificate verification page)
- `EventCredit` model with credit_points for attendance/participation/volunteering

**Gap:** No bulk certificate generation, no certificate type management, no bulk verification, no certificate template customization.

**Implementation Plan:**
1. **Bulk Operations:**
   - `templates/teacher/certificates_bulk.html` — Select multiple students → bulk generate certificates
   - Bulk download as PDF zip
2. **Certificate Types:**
   - Extend `DigitalCertificate` with `certificate_type` (participation, achievement, volunteer, competition, special)
   - Certificate template selection per type
3. **Verification Enhancement:**
   - `templates/certificate_verify.html` — Public verification page (enter code → show certificate details)
   - QR code on each certificate linking to verification URL
4. **Certificate Templates:**
   - Add template engine for certificate design (HTML → PDF via reportlab)
   - Configurable: header, logo, body text, signature, footer
5. Routes: `teacher_certificates_bulk(event_id)`, `teacher_generate_bulk_certificate(event_id)`, `verify_certificate(code)`, `teacher_certificate_types(event_id)`

---

### D3. Add Communication/Notifications Module for Faculty — ⏱️ 2-3 days | Priority: MEDIUM

**Current State:** ✅ Partial — `Notification` model is robust (categories, priorities, actions, read status)
- Teacher has `notifications.html`
- Notification categories include: `event_approval`, `event_rejection`, `changes_requested`, `registration_confirmation`, `registration_cancellation`, `event_reminder`, `venue_change`, `time_change`, `event_cancellation`, `payment_status`, `certificate_issued`, `volunteer_assignment`, `feedback_reminder`, `system`
- `MultiChannelNotification` model exists
- `CampusAnnouncement` model exists

**Gap:** No faculty-to-student broadcast, no faculty-specific notification preferences, no event-specific messaging.

**Implementation Plan:**
1. Create `templates/teacher/communications.html` — Communication center
2. Faculty broadcast messaging: send notification to all registered students of an event
3. Notification preferences: faculty can configure which categories they receive
4. Event-specific announcement: announce changes to event participants
5. Quick-action notification templates: "Event postponed", "Venue changed", "New volunteer needed", "Documents ready for review"
6. Read/unread management, bulk mark as read
7. Integration with `notify()` service for system-triggered notifications
8. Routes: `teacher_communications()`, `teacher_send_communication(event_id)`, `teacher_notification_preferences()`

---

## Implementation Sequence

### Phase 1 — Foundation (Weeks 1-2, ~5 days) ✅ COMPLETED
> Core operational features faculty need immediately

| Order | Task | Est. | Category | Status |
|-------|------|------|----------|--------|
| 1 | B4 — Update Teacher Dashboard Sidebar | 0.5d | B | ✅ Done |
| 2 | A2 — Task Management for Events | 2d | A | ✅ Done |
| 3 | A3 — Incident Reporting | 2d | A | ✅ Done |
| 4 | B1 — Faculty Calendar View | 3d | B | ✅ Done |
| — | Supporting stubs (Workload, Volunteers, Guests) | 0.5d | B | ✅ Done |

### Phase 2 — Event Operations (Next)
> Enhanced event management capabilities

| Order | Task | Est. | Category |
|-------|------|------|----------|
| 5 | A1 — Winner & Result Management | 3.5d | A |
| 6 | A4 — Guest Management | 3d | A |
| 7 | A5 — Equipment/Resource Requests | 3d | A |
| 8 | C1 — Student Eligibility Verification | 2.5d | C |

### Phase 3 — Analytics & Engagement (Pending)
> Data-driven and communication features

| Order | Task | Est. | Category |
|-------|------|------|----------|
| 9 | B2 — Faculty Workload Dashboard | 3.5d | B |
| 10 | B3 — Enhance Faculty Analytics | 4d | B |
| 11 | D1 — Feedback on Volunteers | 2.5d | D |
| 12 | D3 — Communication/Notifications | 2.5d | D |

### Phase 4 — Certificates & Verification (Pending)
> Document and certification management

| Order | Task | Est. | Category |
|-------|------|------|----------|
| 13 | C2 — Document Verification | 2.5d | C |
| 14 | D2 — Enhance Certificate Management | 4.5d | D |
| 15 | Buffer / Testing | 3d | — |

---

## Summary Matrix

| # | Feature | Status | Est. Days | Priority | Phase |
|---|---------|--------|-----------|----------|-------|
| 1 | Winner & Result Management | 🟡 Partial | 3-4 | HIGH | 2 |
| 2 | Task Management for Events | ✅ **DONE** | 2 | HIGH | 1 |
| 3 | Equipment/Resource Requests | 🟡 Partial | 2-3 | MEDIUM-HIGH | 2 |
| 4 | Guest Management | 🟡 Partial (stub done) | 2-3 | MEDIUM-HIGH | 2 |
| 5 | Student Eligibility Verification | 🟡 Partial | 2-3 | MEDIUM | 2 |
| 6 | Document Verification | 🟡 Partial | 2-3 | MEDIUM | 4 |
| 7 | Faculty Calendar View | ✅ **DONE** | 3 | HIGH | 1 |
| 8 | Faculty Workload Dashboard | 🟡 Partial (stub done) | 3-4 | MEDIUM | 3 |
| 9 | Incident Reporting | ✅ **DONE** | 2 | HIGH | 1 |
| 10 | Feedback on Volunteers | 🟡 Partial | 2-3 | MEDIUM | 3 |
| 11 | Certificate Management (bulk/types/verify) | 🟡 Partial | 4-5 | MEDIUM | 4 |
| 12 | Volunteer Management (duties/locations/tracking) | 🟡 Partial | 2-3 | MEDIUM | 3 |
| 13 | Communication/Notifications | 🟡 Partial | 2-3 | MEDIUM | 3 |
| 14 | Faculty Analytics Dashboard | 🟡 Partial | 3-5 | MEDIUM | 3 |
| 15 | Teacher Dashboard Sidebar Update | ✅ **DONE** | 0.5 | MEDIUM | 1 |

**Phase 1 Complete:** 4/15 features implemented | **Remaining:** 11 features | **Total effort:** ~32-38 remaining dev days

---

## Database Models Already Available (Ready to Build On)

These models already exist and can be leveraged without schema changes:

| Model | Purpose | Used By |
|-------|---------|---------|
| `EventTask` | Per-event task tracking | A2 |
| `EventEmergency` | Incident reporting | A3 |
| `VIPGuestManagement` | Guest management | A4 |
| `Resource` / `EquipmentInventory` | Equipment tracking | A5 |
| `EventTask` | Task management | A2 |
| `VolunteerRole` / `VolunteerApplication` / `VolunteerAssignment` / `VolunteerPerformance` | Volunteer system | D1, D2 |
| `DigitalCertificate` | Certificate data | D2 |
| `Notification` | Notifications | D3 |
| `Feedback` / `FeedbackSentiment` | Feedback data | D1 |
| `EventAnalytics` / `EventPolling` / `EventQA` | Analytics data | B3 |
| `EventApprovalWorkflow` | Document verification | C2 |
| `Event` eligibility field | Eligibility rules | C1 |
| `EventFaculty` | Faculty-event linkage | All |
| `InterCollegeEvent` | Competition results | A1 |
| `AttendanceRecord` / `Attendance` | Attendance tracking | B2, B3 |

---

*To begin implementation, start with Phase 1, Task 1 (B4 — Sidebar Update) as it's a quick win that establishes the navigation structure for all subsequent features.*
