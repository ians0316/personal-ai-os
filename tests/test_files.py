"""File indexing tests: real files in a temp folder, real embedding model."""
import json
import os
import time

import pytest
from fastapi.testclient import TestClient

from app import agent, files, memory, tools
from app.server import app
from tests.pdfgen import make_pdf

if not (memory.MODEL_DIR.exists() and any(memory.MODEL_DIR.iterdir())):
    pytest.skip("embedding model not downloaded", allow_module_level=True)

client = TestClient(app)


@pytest.fixture(scope="module")
def folder(tmp_path_factory):
    import docx
    root = tmp_path_factory.mktemp("docs")
    (root / "school").mkdir()
    make_pdf(root / "school" / "Biology notes.pdf", [
        "Chapter 1. Cells are the basic unit of life.",
        "Chapter 2. Photosynthesis turns sunlight, water and carbon dioxide into glucose in the chloroplast.",
        "Chapter 3. Mitochondria release energy through respiration.",
    ])
    (root / "trip-plan.md").write_text("# Japan trip\n\nFlights to Tokyo on 3 April. Hotel in Shinjuku for 5 nights.\n")
    d = docx.Document()
    d.add_paragraph("Curriculum vitae: Python developer, robotics club captain, fluent in Korean and English.")
    d.save(root / "CV.docx")
    (root / ".hidden").mkdir()
    (root / ".hidden" / "secret.md").write_text("should not be indexed")
    (root / "image.png").write_bytes(b"\x89PNG")
    (root / "broken.pdf").write_bytes(b"%PDF-1.4 not really a pdf")
    return root


@pytest.fixture(scope="module", autouse=True)
def indexed(folder):
    memory.set_embedder(memory.Embedder())
    for s in files.list_sources():
        files.remove_source(s["id"])
    src = files.add_source(str(folder))
    files.scan_all()
    yield src
    files.remove_source(src["id"])
    memory.set_embedder(None)


def names(hits):
    return [h["name"] for h in hits]


def test_scan_picks_supported_files_only(indexed):
    listed = {f["name"]: f for f in files.list_files()}
    assert set(listed) == {"Biology notes.pdf", "trip-plan.md", "CV.docx", "broken.pdf"}
    assert listed["Biology notes.pdf"]["pages"] == 3
    assert listed["broken.pdf"]["status"] in ("error", "empty")
    src = files.list_sources()[0]
    assert src["files"] == 4 and src["errors"] >= 0


@pytest.mark.parametrize("query, name, page", [
    ("how do plants make food from light", "Biology notes.pdf", 2),
    ("where am I staying in Tokyo", "trip-plan.md", None),
    ("what languages do I speak", "CV.docx", None),
])
def test_search_by_meaning_with_pages(query, name, page):
    top = files.search(query, 3)[0]
    assert top["name"] == name and top["page"] == page


def test_keyword_search():
    assert files.search("mitochondria", 3)[0]["page"] == 3


def test_rescan_detects_change_add_delete(folder):
    files.scan_all()  # nothing changed
    plan = folder / "trip-plan.md"
    plan.write_text("# Japan trip\n\nCancelled. Going to Iceland to see the northern lights instead.\n")
    os.utime(plan, (time.time() + 5, time.time() + 5))
    (folder / "new.txt").write_text("Guitar practice: learn the F barre chord.")
    totals = files.scan_all()
    assert totals["updated"] == 1 and totals["added"] == 1
    assert files.search("aurora borealis holiday", 1)[0]["name"] == "trip-plan.md"
    assert files.search("guitar chords", 1)[0]["name"] == "new.txt"
    (folder / "new.txt").unlink()
    assert files.scan_all()["removed"] == 1
    assert "new.txt" not in names(files.search("guitar", 5))


def test_read_file_whole_and_page():
    fid = files.search("photosynthesis", 1)[0]["file_id"]
    whole = files.read(fid)
    assert "[Page 3]" in whole["text"] and "Cells" in whole["text"]
    one = files.read(fid, page=2)
    assert "Photosynthesis" in one["text"] and "Cells" not in one["text"]
    assert "error" in files.read(fid, page=99)
    assert "error" in files.read(999999)


def test_add_source_validation(folder):
    with pytest.raises(ValueError):
        files.add_source("/definitely/not/here")
    with pytest.raises(ValueError):
        files.add_source(str(folder / "school"))  # already covered
    with pytest.raises(ValueError):
        files.add_source(os.path.expanduser("~"))


def test_tools_and_citations():
    cited = files.begin_citations()
    res = json.loads(tools.search_files.call({"query": "photosynthesis"}))
    assert res["results"][0]["file"] == "Biology notes.pdf" and res["results"][0]["page"] == 2
    assert {"file_id": res["results"][0]["file_id"], "name": "Biology notes.pdf", "page": 2} in cited


def test_raw_endpoint_serves_only_indexed():
    fid = files.search("photosynthesis", 1)[0]["file_id"]
    r = client.get(f"/api/files/{fid}/raw")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert client.get("/api/files/999999/raw").status_code == 404


def test_api_sources():
    r = client.post("/api/sources", json={"path": "/nope/nope"})
    assert r.status_code == 400
    body = client.get("/api/sources").json()
    assert body["sources"][0]["files"] >= 3 and "running" in body["status"]


def test_chat_returns_cited_sources(monkeypatch):
    """Fake Claude: searches files, then answers citing the PDF."""
    import anthropic
    import httpx2

    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        base = {"id": f"m{len(calls)}", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
                "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1}}
        if len(calls) == 1:
            return httpx2.Response(200, json={**base, "stop_reason": "tool_use", "content": [
                {"type": "tool_use", "id": "t1", "name": "search_files", "input": {"query": "photosynthesis"}}]})
        return httpx2.Response(200, json={**base, "stop_reason": "end_turn", "content": [
            {"type": "text", "text": "Plants make glucose from light [Biology notes.pdf p.2]."}]})

    monkeypatch.setattr(agent, "_client", anthropic.Anthropic(
        api_key="test", http_client=httpx2.Client(transport=httpx2.MockTransport(handler))))
    r = client.post("/api/chat", json={"message": "how do plants make food?"}).json()
    assert r["sources"] and r["sources"][0]["name"] == "Biology notes.pdf"
    assert all(s["name"] in r["reply"] for s in r["sources"])  # uncited hits are dropped
    tool_result = calls[1]["messages"][-1]["content"][0]
    assert "Photosynthesis" in json.dumps(tool_result)
