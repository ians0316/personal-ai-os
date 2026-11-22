# Privacy

| What | Where it lives | Who else sees it |
|---|---|---|
| Notes, tasks, reminders, chat history | `data/aios.db` on your Mac | The parts Claude needs for a reply are sent to the Claude API |
| Your documents | Stay in their folders; an index is in `data/aios.db` | Only passages Claude searches or reads are sent to the Claude API |
| Search model and speech model | `data/models` | No one. They run on your Mac |
| Your voice | Never saved | No one. Transcribed on your Mac; only the text is sent as a chat message |
| Google sign-in | `data/google_token.json` (only your user can read it) | Google |
| Claude API key | `.env` or your shell | Anthropic |

- Nothing in `data/` or `.env` is ever committed to git (see `.gitignore`).
- The app can't send email, change your calendar, or read files outside folders you connect.
- Disconnecting Google deletes the token and asks Google to cancel it.
