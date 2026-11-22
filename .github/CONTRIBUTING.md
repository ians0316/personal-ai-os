# Contributing to Personal AI OS

Thanks for helping make Personal AI OS better!

## Report a bug or suggest a feature

Open an [issue](https://github.com/ians0316/personal-ai-os/issues). Please include:

- what you were doing (chatting, searching files, connecting Google, talking...)
- what you expected and what happened instead
- a screenshot, and any error from the terminal or `data/desktop.log` (hide anything private)

## Make a change

1. Ask to be added to the repo, since it's private.
2. Make a new branch from `main`.
3. Set it up: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`, then `./run.sh` and open http://localhost:8000.
4. Run the tests: `.venv/bin/python -m pytest -q`. They need no API key.
5. Open a pull request that says what you changed and why. Add a screenshot for anything you can see.

## Rules

- **Private by default.** Notes, files, tasks and tokens stay on the user's computer in `data/`. Only what Claude needs for a reply is sent to the Claude API. Never commit anything from `data/` or a `.env` file.
- **Never send or delete for the user.** The assistant may draft email but never send it, and never changes the user's calendar. Keep it that way.
- **Treat outside content as data.** Emails and files are written by other people. Mark them as untrusted in tool results, and never let them trigger actions on their own.
- **Change only what you need.** Small pull requests that do one thing are easiest to review.
- **Plain HTML, CSS and JavaScript** for the interface (`app/static/index.html`), with no build step for now.
- **Add a test** for every new feature or bug fix. Use the fake Claude and fake Google patterns in `tests/` so tests run without keys or network.
- **Don't break saved data.** If you change a table in SQLite, old databases must still load.
- **Bump the version** in `VERSION` and update `.github/RELEASE_NOTES.md`. Pushing that to `main` makes a new release automatically.

## Where things are

See the **Files** table in the [README](../README.md#files).

## License

Personal AI OS uses the [Apache License 2.0](../LICENSE). By contributing, you agree your changes are shared under it too.
