# FAQ

**Does it work without an API key?**
Notes, tasks, reminders, file search, Google and the plain daily briefing work. Chat and the Claude-written briefing need a key.

**How much does it cost to use?**
Personal AI OS is free. The Claude API charges per use; normal personal use is usually a few cents a day. The daily briefing uses Claude's lowest effort setting to keep it cheap.

**Can it send email for me?**
No. It saves drafts in Gmail, and you review and send them yourself. It doesn't even have permission to send.

**Does it work on Windows or Linux?**
The web version (`./run.sh`) should work anywhere Python runs. The desktop app and read-aloud are Mac-only for now.

**Why does Google make me sign in again every week?**
While your Google Cloud project is in "testing" mode, Google expires sign-ins after 7 days. That's normal for a personal project.

**Where are my notes?**
In `data/aios.db` inside the project folder. Back up the whole `data/` folder to keep everything.
