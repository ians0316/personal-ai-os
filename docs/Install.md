# Install

## What you need
- A Mac (Apple Silicon or Intel) with Python 3.12 or newer
- A Claude API key from [console.anthropic.com](https://console.anthropic.com)
- About 1 GB of free space (libraries plus two small AI models)

## Set it up (once)
```bash
git clone https://github.com/ians0316/personal-ai-os.git
cd personal-ai-os
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env
```
Or download the zip from the latest [release](https://github.com/ians0316/personal-ai-os/releases/latest) instead of cloning.

## Run it in your browser
```bash
set -a; . ./.env; set +a
./run.sh
```
Open http://localhost:8000. The first start downloads a small search model (~65 MB) into `data/models`.

## Build the desktop app
```bash
./make_app.sh
```
This makes `dist/Personal AI OS.app`. Double-click it or drag it to your Dock. It reads your key from `.env`. The app runs from this folder, so run `make_app.sh` again if you move the folder.

The first time you press 🎤, macOS asks for microphone access, and the speech model (~140 MB) downloads once.

## Connect Google (optional)
Open the **Connections** tab and follow the steps. You make your own free OAuth client in Google Cloud and paste its JSON. See [Features → Calendar and email](Features.md#calendar-and-email).

## Update
1. `git pull` (or download the new release zip and copy its files over your old folder).
2. `.venv/bin/pip install -r requirements.txt`
3. Restart the app.

> ⚠️ Keep the `data/` folder: it holds your notes, tasks, settings and Google sign-in. Deleting it starts you from empty.
