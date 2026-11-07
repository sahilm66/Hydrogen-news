# Hydrogen News Tracker

A small AI agent that checks India's green hydrogen news every week and
writes a plain-English digest: the top 3 stories, then everything grouped
into Policy / Subsidies / Tenders / Industry.

Built in three phases:

| File | What it does |
|---|---|
| `fetch_news.py` | Phase 1. Downloads recent India hydrogen articles from the free GDELT news database, filters them, and skips ones you have already seen. |
| `digest_news.py` | Phase 2. Sends the shortlist to Google's free Gemini AI, which writes the grouped digest and saves it to a dated file. |
| `agent.py` | Phase 3. The agent: one command that lets the AI drive phases 1 and 2 itself, deciding each step as it goes. |

## Run it on your own computer

One time setup:

```
pip install requests
```

Then get a FREE Gemini API key (about 2 minutes):

1. Go to https://aistudio.google.com and sign in with a Google account.
2. Click "Get API key", then "Create API key", and copy it.
3. Save it as an environment variable:

   - Windows (Command Prompt): `setx GEMINI_API_KEY "paste-your-key-here"`
     then close and reopen the terminal.
   - Mac/Linux: `export GEMINI_API_KEY="paste-your-key-here"`

Try it with zero setup first (no key needed):

```
python agent.py --mock
```

Mock mode uses a pretend AI so you can watch the agent loop work. Then the
real thing:

```
python agent.py
```

Notes:

- The news API rate-limits, so a run can take a few minutes. That is normal.
- To see every article again (not just new ones), delete `seen_articles.json`.
- AI models sometimes invent details. The digest links to the original
  articles - those are the source of truth.

## Make it run by itself every week (free, with GitHub)

You will put the code in a GitHub repo, and GitHub Actions will run
`python agent.py` for you every Monday at 8 AM IST and save the digest into
the repo. About 15 minutes of clicking:

1. **Make a free GitHub account** at https://github.com if you do not have one.
2. **Create a new repo:** click the "+" top right, then "New repository".
   Name it anything (e.g. `hydrogen-news`), keep it Private, click Create.
3. **Upload the code:** on your repo page, click "Add file" then
   "Upload files", and drag in `fetch_news.py`, `digest_news.py`,
   `agent.py` and this `README.md`. Click "Commit changes".
4. **Add the workflow file:** click "Add file" then "Create new file". In the
   name box, type exactly:

   ```
   .github/workflows/weekly.yml
   ```

   (typing the slashes creates the folders for you). Paste in the contents
   of the `weekly.yml` from this project and click "Commit changes".
5. **Add your secret API key:** in the repo, go to
   Settings -> Secrets and variables -> Actions -> "New repository secret".
   Name: `GEMINI_API_KEY`. Value: your key from the setup above. Save.
   (Secrets are hidden from everyone, including you after saving - that is
   the point.)
6. **Test it once by hand:** go to the repo's "Actions" tab, click
   "Weekly hydrogen news digest" on the left, then the "Run workflow"
   button. Watch it go green.

Done. Every Monday morning the digest appears in your repo as a dated
`digest-YYYY-MM-DD.md` file, and you can read the full history of runs in
the Actions tab.

## Files the scripts create

| File | What is inside |
|---|---|
| `latest_run.json` | The articles from the most recent fetch (phase 1 hands these to phase 2). |
| `seen_articles.json` | Every article URL already shown, so you never see repeats. |
| `digest-YYYY-MM-DD.md` | One saved digest per run. |
