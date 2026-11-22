"""Core tests: storage, tools and HTTP API. No Claude API key needed."""
import json
import os
import tempfile


from fastapi.testclient import TestClient  # noqa: E402

from app import agent, db, tools  # noqa: E402
from app.server import app  # noqa: E402

client = TestClient(app)


def call(tool, **kw):
    return json.loads(tool.call(kw))


def test_tool_schemas_generated():
    names = {t.name for t in tools.ALL_TOOLS}
    assert {"search_notes", "add_note", "add_task", "set_reminder"} <= names
    schema = tools.add_task.to_dict()
    assert schema["input_schema"]["required"] == ["title"]


def test_notes_search():
    call(tools.add_note, title="Mia birthday", body="Sister Mia's birthday is 14 March", tags="family")
    call(tools.add_note, title="Wifi", body="Home wifi password is on the fridge")
    res = call(tools.search_notes, query="when is Mia's birthday")
    assert res["results"][0]["title"] == "Mia birthday"
    assert call(tools.search_notes, query="zzzz")["results"] == []


def test_tasks_flow():
    t = call(tools.add_task, title="Physics homework", due="2026-11-27", priority="high")["task"]
    assert t["due"] == "2026-11-27"
    assert any(x["id"] == t["id"] for x in call(tools.list_tasks)["tasks"])
    call(tools.complete_task, task_id=t["id"])
    assert all(x["id"] != t["id"] for x in call(tools.list_tasks)["tasks"])
    assert "error" in call(tools.add_task, title="x", due="next tuesday-ish")


def test_reminders_fire_once():
    call(tools.set_reminder, message="past one", remind_at="2000-01-01 09:00")
    call(tools.set_reminder, message="future one", remind_at="2999-01-01T09:00")
    due = client.get("/api/reminders/due").json()
    assert [r["message"] for r in due] == ["past one"]
    assert client.get("/api/reminders/due").json() == []
    assert [r["message"] for r in client.get("/api/reminders").json()] == ["future one"]


def test_api_crud():
    n = client.post("/api/notes", json={"title": "API note", "body": "hello"}).json()
    assert client.patch(f"/api/notes/{n['id']}", json={"body": "edited"}).json()["body"] == "edited"
    assert client.delete(f"/api/notes/{n['id']}").status_code == 200
    t = client.post("/api/tasks", json={"title": "API task"}).json()
    assert client.patch(f"/api/tasks/{t['id']}", json={"done": True}).json()["done"] == 1
    assert client.post("/api/reminders", json={"message": "x", "remind_at": "bad"}).status_code == 400
    assert client.get("/").status_code == 200


def test_history_alternates():
    db.clear_chat()
    db.add_chat_message("assistant", "orphan")
    db.add_chat_message("user", "hi")
    db.add_chat_message("assistant", "hello")
    db.add_chat_message("user", "unanswered")
    assert agent._history() == [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]


def test_agent_loop_with_fake_claude(monkeypatch):
    """Fake the Claude API: first reply asks for add_task, second reply is text."""
    import anthropic
    import httpx2 as httpx

    sent = []

    def handler(request: httpx.Request):
        body = json.loads(request.content)
        sent.append(body)
        base = {"id": f"msg_{len(sent)}", "type": "message", "role": "assistant",
                "model": body["model"], "stop_sequence": None,
                "usage": {"input_tokens": 10, "output_tokens": 5}}
        if len(sent) == 1:
            return httpx.Response(200, json={**base, "stop_reason": "tool_use", "content": [
                {"type": "tool_use", "id": "toolu_1", "name": "add_task",
                 "input": {"title": "Buy milk", "priority": "low"}}]})
        return httpx.Response(200, json={**base, "stop_reason": "end_turn",
                                         "content": [{"type": "text", "text": "Added **Buy milk**."}]})

    fake = anthropic.Anthropic(api_key="test", http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(agent, "_client", fake)
    db.clear_chat()

    r = client.post("/api/chat", json={"message": "add buy milk"}).json()
    assert r["reply"] == "Added **Buy milk**."
    assert r["actions"] == [{"tool": "add_task", "input": {"title": "Buy milk", "priority": "low"}}]
    assert any(t["title"] == "Buy milk" for t in db.list_tasks())
    # request shape
    assert sent[0]["model"] == "claude-opus-5-5"
    assert sent[0]["thinking"] == {"type": "adaptive"}
    assert sent[1]["messages"][-1]["content"][0]["type"] == "tool_result"
    assert [m["role"] for m in db.recent_chat()] == ["user", "assistant"]


def test_missing_key_is_clear(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.setattr(agent, "_client", None)
    r = client.post("/api/chat", json={"message": "hi"})
    assert r.status_code == 401 and "API key" in r.json()["detail"]
