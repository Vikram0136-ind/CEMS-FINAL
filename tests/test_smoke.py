import os
import re

os.environ.setdefault("RATELIMIT_ENABLED", "false")
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SEED_DEMO_DATA", "true")

import pytest

import app as cems

ACCOUNTS = {
    "admin": ("admin@agc.local", "Admin@123"),
    "organizer": ("organizer@agc.local", "Organizer@123"),
    "student": ("student@agc.local", "Student@123"),
    "teacher": ("teacher@agc.local", "Teacher@123"),
}


def csrf(html):
    return re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)


def login(role):
    client = cems.app.test_client()
    email, password = ACCOUNTS[role]
    token = csrf(client.get("/login").text)
    response = client.post("/login", data={"email": email, "password": password, "csrf_token": token})
    assert response.status_code == 302
    return client


@pytest.fixture(autouse=True)
def _app():
    cems.app.config["TESTING"] = True
    cems.app.config["PROPAGATE_EXCEPTIONS"] = True
    yield


def test_health():
    assert cems.app.test_client().get("/health").json["status"] == "ok"


def test_post_requires_csrf():
    assert cems.app.test_client().post("/login", data={"email": "x", "password": "y"}).status_code == 400


def test_logout_is_post_only():
    client = login("student")
    assert client.get("/logout").status_code == 405
    token = csrf(client.get("/events").text)
    assert client.post("/logout", data={"csrf_token": token}).status_code == 302


@pytest.mark.parametrize("role", list(ACCOUNTS))
def test_every_argumentless_page_renders(role):
    client = login(role)
    for rule in cems.app.url_map.iter_rules():
        if "GET" in rule.methods and not rule.arguments and rule.endpoint != "static" and rule.rule != "/logout":
            assert client.get(rule.rule).status_code < 500, rule.rule


def test_reset_link_expires():
    client = cems.app.test_client()
    assert client.get("/reset-password/not-a-real-token").status_code == 302
