#!/usr/bin/env python3
"""
agent.py - Phase 3 of your hydrogen news tracker: the AGENT.

What makes this an "agent" and not just a script?
  A normal script (like phase 1 and 2) follows the steps YOU wrote, in the
  order YOU wrote them. An agent hands the to-do list to an AI model and lets
  IT decide the steps:

      1. We tell the AI: "here is the weekly job, and here are the tools
         you may use" (a tool is just one of our Python functions).
      2. The AI replies: "call fetch_new_articles". It does NOT run anything
         itself - it just asks.
      3. Our code runs that function for real and shows the AI the result.
      4. The AI looks at the result and picks the next step ("now call
         write_weekly_digest"), or decides the job is finished.

  Steps 2-4 repeat in a loop until the AI says it is done. That loop - model
  picks a tool, sees the result, picks again - is the whole idea behind every
  AI agent, from this 150-line file to the big commercial ones.

  Your phase 1 and 2 scripts become the agent's tools, unchanged:
      fetch_news.py   -> tool "fetch_new_articles"
      digest_news.py  -> tool "write_weekly_digest"

Setup (one time):
  pip install requests
  You need your free Gemini API key in an environment variable (the same one
  phase 2 uses):
    Windows (Command Prompt):   setx GEMINI_API_KEY "paste-your-key-here"
                                  (close and reopen the terminal after)
    Mac/Linux:                  export GEMINI_API_KEY="paste-your-key-here"
  Get a free key at https://aistudio.google.com -> "Get API key".

How to run:
  python agent.py           # the real weekly job, end to end, one command
  python agent.py --mock    # practice mode: a pretend AI drives the loop,
                            # no key or internet needed - watch how the
                            # agent loop works before your key is ready
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import requests

# --- Settings you can play with ----------------------------------------------

# Same free-tier model phase 2 uses. Keep them in sync.
MODEL = "gemini-3.5-flash-lite"
API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"

RETRY_WAIT_SECONDS = 30   # if Google says "slow down" (429), wait this long
MAX_RETRIES = 3           # ...and retry this many times before giving up

MAX_STEPS = 8             # safety net: an agent loop must always be able to
                          # stop. If the AI keeps asking for tools forever,
                          # we bail out politely instead of looping forever.

SCRIPT_DIR = Path(__file__).parent
FETCH_SCRIPT = SCRIPT_DIR / "fetch_news.py"     # phase 1 = the "fetch" tool
DIGEST_SCRIPT = SCRIPT_DIR / "digest_news.py"   # phase 2 = the "digest" tool
LATEST_RUN_FILE = SCRIPT_DIR / "latest_run.json"

# --- The tools we hand to the AI ----------------------------------------------
#
# This list is the AI's menu. For each tool we describe, in plain English,
# what it does - the model reads these descriptions to decide which tool to
# use and when. The actual work is done by the Python functions further down.

TOOLS = [{
    "functionDeclarations": [
        {
            "name": "fetch_new_articles",
            "description": (
                "Download the latest India green-hydrogen news (runs phase 1, "
                "fetch_news.py). Saves the new articles to latest_run.json. "
                "Returns how many new articles were found and their headlines. "
                "Always run this FIRST in the weekly job."
            ),
            "parameters": {"type": "OBJECT", "properties": {}},
        },
        {
            "name": "write_weekly_digest",
            "description": (
                "Write this week's digest (runs phase 2, digest_news.py): the AI "
                "groups the new articles into Policy / Subsidies / Tenders / "
                "Industry with one-line summaries and saves a dated digest file. "
                "Only run this AFTER fetch_new_articles, and only if it found "
                "new articles."
            ),
            "parameters": {"type": "OBJECT", "properties": {}},
        },
    ]
}]

# The job description we give the agent. Being specific here is most of the
# work of getting a good result.
GOAL = """You run the weekly hydrogen-news job for a student tracking India's
green hydrogen policy. Do it in order:

1. Call fetch_new_articles to get this week's new articles.
2. If it found 1 or more new articles, call write_weekly_digest.
   If it found 0 new articles, do NOT write a digest - just say nothing new
   was found.
3. Reply with a short, friendly summary of what you did (2-3 sentences),
   including the digest file name if one was written.
"""

# --- Tool 1: fetch new articles (wraps phase 1) --------------------------------

def tool_fetch_new_articles(mock):
    """Run fetch_news.py as a separate program, then read what it saved.

    Running it with subprocess means phase 1 stays exactly as it is - this
    file just presses its "start" button and reads the output file.
    """
    if mock:
        # Practice mode: pretend phase 1 found these, so the loop has
        # something to work with without touching the network.
        sample = [
            {"title": "India will lead world in green hydrogen production, says Nitin Gadkari",
             "url": "https://example.com/1", "source": "moneycontrol.com", "seendate": "20261023T120000Z"},
            {"title": "Cabinet clears subsidy scheme for hydrogen electrolysers",
             "url": "https://example.com/2", "source": "example.in", "seendate": "20261024T090000Z"},
            {"title": "MNRE opens bids for green hydrogen hubs",
             "url": "https://example.com/3", "source": "example.in", "seendate": "20261025T150000Z"},
        ]
        LATEST_RUN_FILE.write_text(json.dumps(sample, indent=2), encoding="utf-8")
        return {"new_count": len(sample),
                "headlines": [a["title"] for a in sample],
                "note": "(mock mode: sample articles, no real download)"}

    if not FETCH_SCRIPT.exists():
        return {"error": f"I can't find {FETCH_SCRIPT.name} next to agent.py. "
                         "Put phase 1 in the same folder."}

    # GDELT rate-limits, so phase 1 can take 1-3 minutes. Give it 5.
    ok, output = run_script(FETCH_SCRIPT, timeout=300)
    if not ok:
        return {"error": "fetch_news.py did not finish cleanly. Its output:",
                "output": output[-800:]}   # last bit of output is the useful part

    if not LATEST_RUN_FILE.exists():
        return {"error": "fetch_news.py ran but latest_run.json is missing."}

    articles = json.loads(LATEST_RUN_FILE.read_text(encoding="utf-8", errors="replace"))
    return {"new_count": len(articles),
            "headlines": [a.get("title", "(no title)") for a in articles]}

# --- Tool 2: write the digest (wraps phase 2) ----------------------------------

def tool_write_digest(mock):
    """Run digest_news.py, then find the digest file it saved."""
    if not DIGEST_SCRIPT.exists():
        return {"error": f"I can't find {DIGEST_SCRIPT.name} next to agent.py. "
                         "Put phase 2 in the same folder."}

    # In mock mode we pass --mock along so phase 2 also skips its real AI call.
    args = ["--mock"] if mock else []
    ok, output = run_script(DIGEST_SCRIPT, extra_args=args, timeout=180)
    if not ok:
        return {"error": "digest_news.py did not finish cleanly. Its output:",
                "output": output[-800:]}

    # Phase 2 saves files named digest-YYYY-MM-DD.md - grab the newest one.
    digests = sorted(SCRIPT_DIR.glob("digest-*.md"),
                     key=lambda p: p.stat().st_mtime)
    if not digests:
        return {"error": "digest_news.py ran but no digest-*.md file appeared.",
                "output": output[-800:]}

    newest = digests[-1]
    lines = newest.read_text(encoding="utf-8", errors="replace").splitlines()
    preview = "\n".join(lines[:12])   # just the top, so the AI sees a taste
    return {"digest_file": newest.name, "preview": preview}

# --- Running the phase scripts --------------------------------------------------

def run_script(path, extra_args=None, timeout=180):
    """Run one of the phase scripts and capture everything it prints.

    Returns (True, output) if it exited happily, (False, output) otherwise.
    """
    cmd = [sys.executable, str(path)] + (extra_args or [])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                encoding="utf-8", errors="replace",
                                timeout=timeout, cwd=SCRIPT_DIR)
    except subprocess.TimeoutExpired:
        return False, f"{path.name} ran for more than {timeout} seconds and I stopped it."
    output = (result.stdout or "") + (result.stderr or "")
    return result.returncode == 0, output.strip()

def run_tool(name, mock):
    """The dispatcher: turn the AI's tool choice into a real function call.

    Whatever happens, we always return a dictionary - even errors go back to
    the model as data, so it can react ('that failed, I should stop') instead
    of the program crashing.
    """
    if name == "fetch_new_articles":
        return tool_fetch_new_articles(mock)
    if name == "write_weekly_digest":
        return tool_write_digest(mock)
    # The model asked for a tool that does not exist. Rare, but tell it so
    # instead of crashing - it will usually correct itself.
    return {"error": f"There is no tool called '{name}'. "
                     "Use fetch_new_articles or write_weekly_digest."}

# --- Talking to Gemini -----------------------------------------------------------

def get_api_key():
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        print("I need your free Gemini API key first. It takes 2 minutes:")
        print()
        print("  1. Go to https://aistudio.google.com and sign in.")
        print('  2. Click "Get API key", then "Create API key", and copy it.')
        print("  3. Hand it to me through an environment variable:")
        print()
        print('     Windows (Command Prompt):  setx GEMINI_API_KEY "your-key"')
        print("        (close and reopen the terminal after)")
        print('     Mac/Linux:                 export GEMINI_API_KEY="your-key"')
        print()
        print("Then run me again. (No key yet? Try:  python agent.py --mock)")
        sys.exit(1)
    return key

def call_gemini(contents, api_key):
    """Send the conversation so far to Gemini and return its reply.

    'contents' is the whole chat history: our goal, the model's tool requests,
    and our tool results, oldest first. Each loop round we add to it and send
    it all again - that is how the model "remembers" what already happened.
    """
    body = {"contents": contents, "tools": TOOLS}
    for attempt in range(1, MAX_RETRIES + 2):
        try:
            response = requests.post(
                API_URL,
                params={"key": api_key},
                json=body,
                timeout=60,
            )
        except requests.RequestException as exc:
            print(f"I could not reach Google at all ({exc}).")
            print("Check your internet connection and try again.")
            sys.exit(1)

        if response.status_code == 200:
            return response.json()

        if response.status_code == 429 and attempt <= MAX_RETRIES:
            print(f"Google asked us to slow down - waiting {RETRY_WAIT_SECONDS}s "
                  f"(try {attempt} of {MAX_RETRIES})...")
            time.sleep(RETRY_WAIT_SECONDS)
            continue

        if response.status_code in (400, 401, 403):
            # A 401/403 usually means the key really is wrong, but a 400 can
            # also mean Google did not like the REQUEST itself. The old
            # version always blamed the key, which sent us chasing the wrong
            # problem. So: show Google's own explanation first - it says
            # exactly what it rejected.
            print(f"Google said no (HTTP {response.status_code}). Its explanation:")
            print()
            print(response.text[:500])
            print()
            if response.status_code in (401, 403) or "API key" in response.text:
                print("It mentions the key - grab a fresh one at")
                print("https://aistudio.google.com and update your")
                print("GEMINI_API_KEY environment variable, then run me again.")
            else:
                print("That is about the request, not your key. Copy the")
                print("explanation above and share it when asking for help.")
        elif response.status_code == 429:
            print("Google's free tier is busy right now (too many requests).")
            print("Wait a few minutes and run me again - nothing is broken.")
        else:
            print(f"Unexpected answer from Google (HTTP {response.status_code}):")
            print(response.text[:400])
        sys.exit(1)

# --- The pretend AI, for --mock mode ---------------------------------------------

def mock_model_reply(step):
    """Canned 'model' answers so you can watch the loop with no key.

    Round 0 the pretend AI asks for the fetch tool, round 1 for the digest
    tool, round 2 it declares the job done. Same shapes as real Gemini
    replies, so the loop code below cannot tell the difference.
    """
    if step == 0:
        return {"candidates": [{"content": {"role": "model", "parts": [
            {"functionCall": {"name": "fetch_new_articles", "args": {}}}]}}]}
    if step == 1:
        return {"candidates": [{"content": {"role": "model", "parts": [
            {"functionCall": {"name": "write_weekly_digest", "args": {}}}]}}]}
    return {"candidates": [{"content": {"role": "model", "parts": [
        {"text": "Weekly job done! I fetched 3 new articles and wrote the "
                 "digest to a dated file. (mock mode: this summary is canned)"}]}}]}

# --- The agent loop itself ---------------------------------------------------------

def agent_loop(mock, api_key=None):
    """THE AGENT. This one function is the whole point of phase 3.

    Look how small it is: a conversation, a loop, and an if. Everything else
    in this file is plumbing.
    """
    contents = [{"role": "user", "parts": [{"text": GOAL}]}]

    for step in range(MAX_STEPS):
        # 1. Ask the model what to do next (real AI, or the pretend one).
        reply = mock_model_reply(step) if mock else call_gemini(contents, api_key)  # real AI needs the key
        parts = reply["candidates"][0]["content"]["parts"]

        # Keep the model's reply in the history so it remembers its own plan.
        contents.append({"role": "model", "parts": parts})

        # 2. Did it ask us to run any tools?
        tool_calls = [p["functionCall"] for p in parts if "functionCall" in p]

        if not tool_calls:
            # No tool request = the model is talking to us = job finished.
            final_words = "".join(p.get("text", "") for p in parts)
            print("\n--- The agent finished ---")
            print(final_words.strip() or "(the model ended without a message)")
            return

        # 3. Run each tool it asked for, and hand the results back.
        for call in tool_calls:
            name = call.get("name", "")
            print(f"\n[agent] The AI decided to use tool: {name}")
            result = run_tool(name, mock)
            print(f"[agent] Tool result: {json.dumps(result)[:300]}")

            # The official format for returning a tool result to Gemini:
            # a "user" message whose part holds the functionResponse.
            # (Google's API only accepts the roles "user" and "model" - an
            # earlier version of this file used role "function" here, and
            # Google answered every such request with HTTP 400.)
            contents.append({"role": "user", "parts": [{
                "functionResponse": {
                    "name": name,
                    "response": result,
                }}]})

    print(f"\nThe agent used {MAX_STEPS} rounds without finishing, so I stopped")
    print("it (this is the safety net, not an error). Just run me again.")

# --- Start here ---------------------------------------------------------------------

def main():
    mock = "--mock" in sys.argv
    if mock:
        print("(mock mode: a pretend AI is driving - no key, no real download)\n")
        agent_loop(mock=True)
        return

    # Real mode needs the key BEFORE the loop starts (the loop uses it).
    api_key = get_api_key()
    print(f"Starting the weekly hydrogen-news agent (model: {MODEL})...")
    agent_loop(mock=False, api_key=api_key)

if __name__ == "__main__":
    main()