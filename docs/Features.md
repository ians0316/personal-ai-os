# Features

## Today
A **daily briefing** every morning (07:30 by default, change it on the Today tab): today's calendar, overdue and due-today tasks, today's reminders, unread email worth a look, and what's coming up. Claude writes it; without an API key you get a plain version. A toast and a dot on the tab tell you when it's ready. **↻ Refresh** rebuilds it.

## Chat
Ask anything. Claude can use these tools for you:

| Tool | What it does |
|---|---|
| `search_notes`, `add_note`, `update_note` | Find notes by meaning, save new facts, update old ones |
| `list_tasks`, `add_task`, `complete_task` | Your to-do list |
| `set_reminder`, `list_reminders` | Reminders that pop up at the right time |
| `search_files`, `read_file` | Search and read your connected documents, with citations |
| `list_calendar_events` | Read your Google Calendar |
| `search_emails`, `read_email` | Read your Gmail |
| `draft_email` | Save a reply as a Gmail **draft**. It is never sent. |

Small chips under each reply show which actions it took. Related notes are found automatically and given to Claude with each message.

## Voice
Press 🎤 or **Ctrl+Space** to talk, and again to send. Whisper turns your speech into text on your Mac, offline. 🔊 reads replies aloud; Esc stops it.

## Notes
Write notes with tags. Search understands meaning: "teeth" finds a note about your dentist. Badges show whether a result matched by **words**, **meaning**, or both.

## Tasks and Reminders
Tasks have due dates and priorities; overdue ones turn red. Reminders show a toast (and a desktop notification if you allow it) at the set time.

## Files
Connect folders of PDF, Word (.docx), Markdown and text files. They're indexed on your Mac and re-checked every minute. Answers cite the file and page, like `[Biology notes.pdf p.2]`, with links that open the file. Hidden folders, `node_modules` and files over 25 MB are skipped. Scanned PDFs (images) can't be read yet.

## Calendar and email
On the **Connections** tab, connect Google. The app asks only for: read calendars, read mail, and compose drafts. It has **no permission to send email or change your calendar**. Emails are marked as untrusted so instructions hidden in them are never followed.
