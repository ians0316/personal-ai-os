"""Personal AI OS as a desktop app: a native window plus the local server.

Run:  .venv/bin/python desktop.py     (or double-click "Personal AI OS.app", see make_app.sh)

The window shows the same interface as the browser version. Because the
desktop window can't give web pages microphone access, voice recording and
read-aloud go through the small `NativeBridge` below instead.
"""

import socket
import threading
import time
import urllib.request

import uvicorn
import webview

from app import db, voice

HOST, PORT = "127.0.0.1", 8000  # Google sign-in expects port 8000
URL = f"http://localhost:{PORT}/"


class NativeBridge:
    """Functions the page can call as window.pywebview.api.<name>()."""

    def __init__(self):
        self.recorder = voice.Recorder()

    def start_recording(self):
        try:
            self.recorder.start()
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": f"Microphone unavailable: {e}"}

    def stop_recording(self):
        audio = self.recorder.stop()
        try:
            return {"ok": True, "text": voice.transcribe(audio)}
        except Exception as e:
            return {"ok": False, "error": f"Couldn't transcribe: {e}"}

    def speak(self, text):
        voice.speak(text)
        return {"ok": True}

    def stop_speaking(self):
        voice.stop_speaking()
        return {"ok": True}


def port_in_use() -> bool:
    with socket.socket() as s:
        return s.connect_ex((HOST, PORT)) == 0


def our_server_running() -> bool:
    try:
        with urllib.request.urlopen(URL + "api/voice/status", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def start_server() -> None:
    config = uvicorn.Config("app.server:app", host=HOST, port=PORT, log_level="warning")
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True, name="aios-server").start()
    for _ in range(100):  # wait up to 10 s
        if our_server_running():
            return
        time.sleep(0.1)
    raise SystemExit("The server didn't start. Is something else using port 8000?")


def set_app_name(name: str = "Personal AI OS") -> None:
    """Show our name instead of "Python" in the macOS menu bar."""
    try:
        from Foundation import NSBundle
        info = NSBundle.mainBundle().localizedInfoDictionary() or NSBundle.mainBundle().infoDictionary()
        info["CFBundleName"] = name
    except Exception:
        pass


def main() -> None:
    set_app_name()
    if port_in_use():
        if not our_server_running():
            raise SystemExit("Port 8000 is used by another program. Close it and try again.")
        # Reuse the already-running server (e.g. ./run.sh in a terminal).
    else:
        start_server()
    webview.create_window("Personal AI OS", URL, js_api=NativeBridge(), width=1120, height=780,
                          min_size=(380, 500), background_color="#141414")
    storage = db.DB_PATH.parent / "webview"
    storage.mkdir(parents=True, exist_ok=True)
    webview.start(private_mode=False, storage_path=str(storage))


if __name__ == "__main__":
    main()
