# Troubleshooting

**"Claude API key missing or invalid"**
Set `ANTHROPIC_API_KEY` (in `.env` for the desktop app, or `export` it before `./run.sh`), then restart.

**The desktop app doesn't open**
Look at `data/desktop.log`. If it says port 8000 is in use, close the other program (or the browser version's terminal) and try again.

**The microphone doesn't work**
Open System Settings → Privacy & Security → Microphone, and allow it (it may be listed as "Python" or "Personal AI OS"). In a browser, allow the microphone in the site settings for localhost.

**Search only matches exact words**
The search model may not have loaded. Check that `data/models` exists and that `AIOS_EMBEDDINGS` isn't set to `off`.

**A file shows as unreadable**
It may be a scanned PDF (no text inside), password-protected, or damaged. OCR for scanned PDFs is on the [Roadmap](Roadmap.md).

**Google says "access blocked" or "app not verified"**
Add your own Google address as a **test user** on the Google Auth Platform page, and use the same account to sign in.

**The briefing is the plain version**
That happens when there's no API key or Claude couldn't be reached. Press ↻ Refresh after fixing the key.

Still stuck? Open an [issue](https://github.com/ians0316/personal-ai-os/issues).
