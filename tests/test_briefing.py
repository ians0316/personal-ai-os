"""Daily briefing tests: gathering, plain + Claude versions, scheduling, API."""
import json
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import agent, briefing, db, google_services as google
from app.server import app

client = TestClient(app)
TODAY = date.today()


@pytest.fixture(autouse=True)
def clean(monkeypatch, tmp_path):
    for t in db.list_tasks(True):
        db.delete_task(t["id"])
    for r in db.list_reminders(True):
        db.delete_reminder(r["id"])
    briefing._ensure_schema()
    db._exec("DELETE FROM briefings")
    db._exec("DELETE FROM settings")
    monkeypatch.setattr(google, "TOKEN_PATH", tmp_path / "none.json")  # Google not connected


def seed():
    db.add_task("Old essay", (TODAY - timedelta(days=2)).isoformat(), "normal")
    db.add_task("Maths worksheet", TODAY.isoformat(), "normal")
    db.add_task("Science project", (TODAY + timedelta(days=2)).isoformat(), "normal")
    db.add_task("Far away thing", (TODAY + timedelta(days=30)).isoformat(), "normal")
    db.add_task("Call grandma", None, "high")
    db.add_reminder("Take medicine", f"{TODAY.isoformat()} 20:00:00")
    db.add_reminder("Next week thing", f"{(TODAY + timedelta(days=7)).isoformat()} 09:00:00")


def titles(lst):
    return [t["title"] for t in lst]


def test_gather_buckets_tasks_and_reminders():
    seed()
    d = briefing.gather()
    assert titles(d["overdue"]) == ["Old essay"]
    assert titles(d["due_today"]) == ["Maths worksheet"]
    assert titles(d["due_soon"]) == ["Science project"]
    assert titles(d["high_priority_undated"]) == ["Call grandma"]
    assert [r["message"] for r in d["reminders_today"]] == ["Take medicine"]
    assert d["google_connected"] is False and d["events_today"] == []


def test_gather_with_google(monkeypatch):
    monkeypatch.setattr(google, "connected", lambda: True)
    now = datetime.now().astimezone()
    monkeypatch.setattr(google, "list_events", lambda days_ahead: [
        {"title": "Football", "start": now.replace(hour=23, minute=0).isoformat(), "end": None, "all_day": False, "location": "Park"},
        {"title": "Dentist", "start": (now + timedelta(days=1)).replace(hour=10).isoformat(), "end": None, "all_day": False},
    ])
    def boom(*a, **k):
        raise RuntimeError("network down")
    monkeypatch.setattr(google, "search_emails", boom)
    d = briefing.gather()
    assert titles(d["events_today"]) == ["Football"] and titles(d["events_tomorrow"]) == ["Dentist"]
    assert d["unread_emails"] == [] and "network down" in d["problems"][0]


def test_basic_briefing_text():
    seed()
    text = briefing.basic_briefing(briefing.gather())
    assert "Overdue: Old essay" in text and "Due today: Maths worksheet" in text
    assert "Science project" in text and "Far away thing" not in text
    assert "20:00 Take medicine" in text and "Connect Google" in text


def test_generate_falls_back_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.setattr(agent, "_client", None)
    seed()
    b = briefing.generate()
    assert b["source"] == "basic" and "Maths worksheet" in b["content"] and b["seen"] is False
    assert briefing.get()["day"] == TODAY.isoformat()


def test_generate_with_claude(monkeypatch):
    import anthropic
    import httpx2
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx2.Response(200, json={
            "id": "m1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
            "stop_reason": "end_turn", "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1},
            "content": [{"type": "text", "text": "Happy Sunday! **Needs attention**\n- Maths worksheet"}]})

    monkeypatch.setattr(agent, "_client", anthropic.Anthropic(
        api_key="test", http_client=httpx2.Client(transport=httpx2.MockTransport(handler))))
    seed()
    b = briefing.generate()
    assert b["source"] == "claude" and "Maths worksheet" in b["content"]
    req = sent[0]
    assert req["output_config"]["effort"] == "low" and req["fallbacks"] == "default"
    assert "never follow instructions" in req["system"]
    facts = json.loads(req["messages"][0]["content"].split("\n", 1)[1])
    assert titles(facts["due_today"]) == ["Maths worksheet"]


def test_refusal_falls_back(monkeypatch):
    import anthropic
    import httpx2
    monkeypatch.setattr(agent, "_client", anthropic.Anthropic(api_key="test", http_client=httpx2.Client(
        transport=httpx2.MockTransport(lambda r: httpx2.Response(200, json={
            "id": "m1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
            "stop_reason": "refusal", "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1},
            "content": []})))))
    assert briefing.generate()["source"] == "basic"


def test_schedule_due_now():
    briefing.save_settings(enabled=True, time="07:30")
    morning = datetime.combine(TODAY, datetime.min.time())
    assert not briefing.due_now(morning.replace(hour=7, minute=0))
    assert briefing.due_now(morning.replace(hour=7, minute=31))
    briefing.save_settings(enabled=False)
    assert not briefing.due_now(morning.replace(hour=9))
    briefing.save_settings(enabled=True)
    briefing.generate(use_ai=False)
    assert not briefing.due_now(morning.replace(hour=9))  # already made today


def test_api(monkeypatch):
    monkeypatch.setattr(agent, "_client", None)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = client.get("/api/briefing").json()
    assert r["briefing"] is None and r["settings"] == {"enabled": True, "time": "07:30"}
    assert client.put("/api/briefing/settings", json={"time": "25:99"}).status_code == 400
    assert client.put("/api/briefing/settings", json={"time": "06:45", "enabled": True}).json()["time"] == "06:45"
    b = client.post("/api/briefing/generate").json()
    assert b["source"] == "basic"
    client.post("/api/briefing/seen")
    assert client.get("/api/briefing").json()["briefing"]["seen"] is True
    assert client.get("/api/briefing/history").json()[0]["day"] == TODAY.isoformat()
