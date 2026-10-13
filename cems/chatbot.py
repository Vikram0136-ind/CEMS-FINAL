"""Rule-based campus chatbot plus similar-question search for the community Q&A.

No external service is used and no SQL is ever built from user text: every lookup
goes through ORM queries with bound parameters.
"""

import re

from . import features as f
from .features import ctx, utcnow, normalize_role

STOPWORDS = {
    "the", "a", "an", "is", "are", "to", "of", "for", "in", "on", "at", "and", "or", "my", "me", "i", "can", "do",
    "how", "what", "when", "where", "which", "who", "why", "does", "it", "this", "that", "about", "any", "there",
    "be", "with", "from", "will", "you", "your", "please", "tell", "show", "give", "need", "want", "have", "has",
    "event", "events", "get", "am", "was", "if", "by", "as", "so", "we", "our", "us",
}

SUGGESTIONS = {
    "student": ["Which events are coming up?", "What is the registration deadline?", "How do I join a team?",
                "How does the waitlist work?", "How many achievement points do I have?"],
    "organizer": ["How do I create an event?", "How do I enter scores for judges?", "How do I declare winners?",
                  "Where can I see attendance reports?", "How do I cancel an event?"],
    "faculty": ["How do I mark attendance?", "Where is my attendance history?", "How do I judge an event?",
                "Show today's events", "Where are the faculty reports?"],
    "admin": ["Which events are coming up?", "Where is the department dashboard?", "How do I run reminders?",
              "How do I find duplicate IDs?", "Show the leaderboard"],
}


def tokens(text):
    return [t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if t not in STOPWORDS and len(t) > 1]


def has(low, *words):
    return any(re.search(r"\b" + re.escape(w), low) for w in words)


def _link(label, endpoint_or_url, **values):
    from flask import url_for
    url = endpoint_or_url if endpoint_or_url.startswith("/") else url_for(endpoint_or_url, **values)
    return {"label": label, "url": url}


def match_event(low):
    """Best-matching approved/completed event for words in the message."""
    words = set(tokens(low))
    if not words:
        return None
    best, best_score = None, 0
    for event in ctx.Event.query.filter(ctx.Event.status.in_(("approved", "completed"))).all():
        title = (event.title or "").lower()
        if len(title) > 3 and title in low:
            return event
        title_tokens = set(tokens(title))
        score = len(words & title_tokens)
        needed = 1 if len(title_tokens) <= 1 else 2
        if score >= needed and score > best_score:
            best, best_score = event, score
    return best


def similar_questions(text, limit=3):
    words = set(tokens(text))
    if not words:
        return []
    scored = []
    for question in f.CommunityQuestion.query.order_by(f.CommunityQuestion.created_at.desc()).limit(300).all():
        overlap = len(words & set(tokens(question.title + " " + (question.body or ""))))
        if overlap >= (1 if len(words) == 1 else 2):
            scored.append((overlap + (1 if question.is_resolved else 0), question))
    scored.sort(key=lambda row: -row[0])
    return [q for _, q in scored[:limit]]


def _event_line(event):
    return f"{event.title} — {event.date.strftime('%d %b %Y')}, {event.start_time}, {event.venue}"


def _upcoming(limit=5, category=None):
    query = ctx.Event.query.filter(ctx.Event.status == "approved", ctx.Event.date >= utcnow().date())
    if category:
        query = query.filter(ctx.Event.category.ilike(category))
    return query.order_by(ctx.Event.date.asc()).limit(limit).all()


def reply(user, message):
    """Return {reply, links, suggestions, ask_community} for a chat message."""
    text = (message or "").strip()[:500]
    low = text.lower()
    role = normalize_role(user.role)
    out = {"reply": "", "links": [], "ask_community": False, "suggestions": SUGGESTIONS.get(role, SUGGESTIONS["student"])}
    if not text:
        out["reply"] = "Type a question and I will do my best to help."
        return out

    event = match_event(low)
    today = utcnow().date()

    def done(msg, links=None):
        out["reply"] = msg
        out["links"] = links or []
        return out

    if has(low, "hello", "hi", "hey", "good morning", "good evening") and len(tokens(low)) <= 2:
        return done(f"Hi {user.name.split()[0]}! I can answer questions about events, deadlines, registration, teams, "
                    "waitlists, certificates, attendance, scores and points. If I can't help, I'll point you to the community.")

    if has(low, "what can you do", "help me", "help", "capabilit") and not event:
        return done("Ask me about upcoming events, registration deadlines, teams, the waitlist, certificates, attendance, "
                    "results and achievement points. For anything else, post it on the Community board and "
                    "students, organizers and faculty can answer.", [_link("Open community Q&A", "features.community")])

    if has(low, "deadline", "last date", "closing", "countdown", "close") and has(low, "registration", "register", "deadline", "last date", "closing", "countdown", "close"):
        if event and event.registration_deadline:
            days = (event.registration_deadline - today).days
            state = "has closed" if days < 0 else ("closes today" if days == 0 else f"closes in {days} day(s)")
            return done(f"Registration for {event.title} {state} (deadline {event.registration_deadline.strftime('%d %b %Y')}).",
                        [_link("View event", "event_details", event_id=event.id)])
        closing = (ctx.Event.query.filter(ctx.Event.status == "approved", ctx.Event.date >= today,
                                          ctx.Event.registration_deadline >= today)
                   .order_by(ctx.Event.registration_deadline.asc()).limit(5).all())
        if closing:
            lines = [f"• {e.title} — closes {e.registration_deadline.strftime('%d %b')}" for e in closing]
            return done("Registrations closing soon:\n" + "\n".join(lines), [_link("Browse events", "events")])
        return done("No events have an upcoming registration deadline right now.")

    if has(low, "winner", "result", "won", "topper", "rank") and not has(low, "how"):
        target = event
        if target:
            winners = f.published_winners(target)
            if winners:
                lines = [f"• {w.category}: {(w.team.name if w.team else w.registration.user.name)}" for w in winners]
                return done(f"Winners of {target.title}:\n" + "\n".join(lines),
                            [_link("Open event", "event_details", event_id=target.id)])
            return done(f"Results for {target.title} have not been published yet.")
        recent = (f.EventWinner.query.filter_by(published=True).order_by(f.EventWinner.declared_at.desc()).first())
        if recent:
            return done(f"The latest published result is for {recent.event.title}. Ask me about it by name, or see the leaderboard.",
                        [_link("Leaderboard", "features.leaderboard")])
        return done("No results have been published yet.", [_link("Leaderboard", "features.leaderboard")])

    if has(low, "leaderboard", "points", "achievement", "rank", "standing"):
        points = sum(p.points for p in f.AchievementPoint.query.filter_by(user_id=user.id).all())
        mine = f"You have {points} achievement points. " if role == "student" else ""
        return done(mine + "Points: +10 for attending, +50/+35/+25 for 1st/2nd/3rd place, +20 for other winner categories. "
                    "Departments are ranked by the total points of their students.",
                    [_link("Leaderboard", "features.leaderboard"), _link("My achievements", "features.achievements")]
                    if role == "student" else [_link("Leaderboard", "features.leaderboard")])

    if has(low, "waitlist", "wait list", "waiting list"):
        extra = ""
        if role == "student":
            waiting = ctx.Registration.query.filter_by(user_id=user.id, status="waitlisted").count()
            extra = f" You are currently on {waiting} waitlist(s)." if waiting else ""
        return done("When an event is full you can join its waitlist. If anyone cancels, the first person in the queue is "
                    "promoted automatically and notified — no action needed." + extra, [_link("My registrations", "my_registrations")]
                    if role == "student" else [])

    if has(low, "team", "group", "leader", "invite", "member"):
        msg = ("Team events: one student creates the team and becomes the team leader, then shares the invite code. "
               "Members join with that code until the maximum team size is reached. Leaders can remove members, "
               "transfer leadership or disband the team.")
        if event and event.is_team_event:
            low_n, high_n = f.team_limits(event)
            msg += f" {event.title} allows teams of {low_n}–{high_n}."
        return done(msg, [_link("View event", "event_details", event_id=event.id)] if event else [])

    if has(low, "certificate"):
        msg = ("Participants receive a Certificate of Participation once their attendance is recorded. Winners receive a separate "
               "Winner certificate naming their category (e.g. 1st Place) after the organizer publishes the results.")
        return done(msg, [_link("My certificates", "student_certificates")] if role == "student" else [])

    if has(low, "reminder", "remind", "notification", "notify"):
        return done("Reminders are automatic: students get a notification 24 hours before an event and on the event day, and "
                    "everyone who saved an event is reminded before its registration deadline. Cancellations and reschedules notify "
                    "everyone affected immediately. Admins can also press “Send reminders now” on their dashboard.")

    if has(low, "duplicate"):
        return done("The system blocks a second account that uses the same student ID or roll number from registering for an "
                    "event. Admins and organizers can review any duplicates under Duplicate IDs.",
                    [_link("Duplicate IDs", "features.duplicates")] if role in ("admin", "organizer") else [])

    if has(low, "department") and has(low, "dashboard", "report", "performance", "leaderboard"):
        return done("The Department Dashboard compares departments by registrations, attendance ratio, winners and achievement "
                    "points. Filter by batch, semester or odd/even semester.",
                    [_link("Department dashboard", "features.department_dashboard")] if role in ("admin", "organizer", "faculty")
                    else [_link("Leaderboard", "features.leaderboard")])

    if has(low, "wishlist", "save event", "saved", "bookmark"):
        return done("Tap “Save event” on any event page to add it to your wishlist. You'll get a reminder before its "
                    "registration deadline.", [_link("My wishlist", "features.wishlist")])

    if has(low, "cancel") and has(low, "registration", "ticket", "booking", "seat", "my"):
        return done("Open My Registrations and press Cancel on the event. Your seat is released and the next student on the "
                    "waitlist is promoted automatically. Team leaders must transfer leadership or disband the team first.",
                    [_link("My registrations", "my_registrations")])

    if has(low, "cancel") and role in ("organizer", "admin"):
        return done("Open the event in your dashboard and choose Cancel. Every registered student, waitlisted student, coordinating "
                    "faculty and everyone who saved the event is notified instantly with your reason.")

    if has(low, "attendance", "check in", "check-in", "checkin", "entry", "exit", "check out", "scan", "qr"):
        if role == "faculty":
            return done("Open Attendance to mark present/absent/late for your assigned events, or use Entry / Exit to record "
                        "when a participant enters and leaves. Everything you mark is kept in your attendance history.",
                        [_link("Attendance", "teacher_attendance"), _link("Attendance history", "features.attendance_history")])
        if role in ("organizer", "admin"):
            return done("Use Check-in, the QR Scanner or the Entry / Exit desk. Entry and exit times are stored so you can see "
                        "how long each participant stayed.", [_link("Entry / Exit", "features.entry_exit_index")])
        return done("Show the QR code on your ticket at the entrance. Your entry (and exit) time is recorded automatically.",
                    [_link("My tickets", "my_tickets")])

    if has(low, "score", "judge", "judging", "round", "mark") and has(low, "score", "judge", "judging", "round"):
        return done("Organizers add rounds and assign faculty as judges from the event's Competition page. Judges enter scores "
                    "per round in the Judge Panel; totals are averaged across judges and winners are calculated automatically.",
                    [_link("Judge panel", "features.judge_index")] if role == "faculty" else [])

    if has(low, "declare", "publish") and has(low, "winner", "result"):
        return done("Open the event's Competition page, press “Calculate winners” to rank entries by judge score, optionally "
                    "add extra winner categories, then press Publish. Winners are notified and receive winner certificates.")

    if has(low, "report") or has(low, "dashboard", "statistics", "analytics"):
        if role == "admin":
            return done("Reports: Date-to-date report, Department dashboard, Faculty-wise reports and the Leaderboard.",
                        [_link("Date report", "features.date_report"), _link("Department dashboard", "features.department_dashboard"),
                         _link("Faculty reports", "features.faculty_report")])
        if role in ("organizer", "faculty"):
            return done("Use the Date-to-date report, Department dashboard and your event reports. You can export CSV files.",
                        [_link("Date report", "features.date_report"), _link("Department dashboard", "features.department_dashboard")])
        return done("Open the Leaderboard to see department rankings and the most popular events.",
                    [_link("Leaderboard", "features.leaderboard")])

    if has(low, "create", "organize", "organise", "host") and has(low, "event") or (has(low, "approve", "approval") and role in ("organizer", "admin")):
        return done("Organizers create events from Create Event, then submit them for admin approval. Once approved they appear "
                    "on the Events page and students can register.", [_link("Create event", "create_event")] if role == "organizer" else [])

    if has(low, "register", "registration", "sign up", "signup", "join", "enrol", "enroll"):
        if event:
            return done(f"{event.title}: {_event_line(event)}. Open the event page and press Register Now"
                        f"{' (team event — create or join a team)' if event.is_team_event else ''}.",
                        [_link("View event", "event_details", event_id=event.id)])
        return done("Open an event page and press Register Now. Free events confirm instantly; paid events ask for payment. If "
                    "the event is full you can join the waitlist.", [_link("Browse events", "events")])

    if has(low, "venue", "where", "location", "when", "time", "date", "schedule") and event:
        return done(_event_line(event) + ".", [_link("View event", "event_details", event_id=event.id)])

    if has(low, "today", "tonight"):
        todays = ctx.Event.query.filter(ctx.Event.status == "approved", ctx.Event.date == today).all()
        if todays:
            return done("Today:\n" + "\n".join("• " + _event_line(e) for e in todays), [_link("Browse events", "events")])
        return done("There are no events scheduled today.", [_link("Upcoming events", "events")])

    if has(low, "upcoming", "coming", "next", "list", "show", "available", "what's on", "whats on", "happening") or \
            has(low, "technical", "cultural", "sports", "workshop", "academic", "entrepreneurship", "social"):
        category = next((c for c in ("technical", "cultural", "sports", "workshop", "academic", "entrepreneurship", "social")
                         if c in low), None)
        events = _upcoming(5, category)
        if events:
            lines = ["• " + _event_line(e) for e in events]
            return done(("Upcoming " + (category + " " if category else "") + "events:\n") + "\n".join(lines),
                        [_link("Browse all events", "events")])
        return done("I couldn't find any upcoming events for that.", [_link("Browse all events", "events")])

    if has(low, "my registration", "registered", "my ticket", "my events") and role == "student":
        regs = (ctx.Registration.query.filter(ctx.Registration.user_id == user.id, ctx.Registration.status.in_(f.ACTIVE))
                .order_by(ctx.Registration.registered_at.desc()).limit(5).all())
        if regs:
            return done("Your latest registrations:\n" + "\n".join(f"• {r.event.title} ({r.event.date.strftime('%d %b')})" for r in regs),
                        [_link("My registrations", "my_registrations")])
        return done("You have no active registrations yet.", [_link("Discover events", "student_events")])

    if event:
        return done(f"{_event_line(event)}. Registration deadline: "
                    f"{event.registration_deadline.strftime('%d %b %Y') if event.registration_deadline else 'open'}.",
                    [_link("View event", "event_details", event_id=event.id)])

    related = similar_questions(text)
    out["ask_community"] = True
    if related:
        out["reply"] = ("I don't have a direct answer, but the community has discussed something similar. "
                        "You can also post your question for students, organizers and faculty.")
        out["links"] = [{"label": q.title[:70], "url": f"/community/{q.id}"} for q in related]
    else:
        out["reply"] = ("I'm not sure about that one. Post it on the community board — students, organizers and "
                        "faculty can answer from anywhere, and you'll be notified when someone replies.")
        out["links"] = [_link("Ask the community", "features.community")]
    return out
