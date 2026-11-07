#!/usr/bin/env python3
"""
digest_news.py - Phase 2 of your hydrogen news tracker.

What it does:
  1. Reads latest_run.json - the new articles fetch_news.py (phase 1) found.
  2. Sends that shortlist to Google's Gemini AI (free tier).
  3. Gemini writes a plain-English digest: grouped into Policy / Subsidies /
     Tenders / Industry, one line per article, top 3 starred.
  4. Prints the digest and saves it to a dated file, e.g. digest-2026-11-07.md.

Setup (one time):
  pip install requests        # same library phase 1 uses

  Then you need a FREE Gemini API key - think of it as a password that lets
  your script talk to Google's AI:
    1. Go to https://aistudio.google.com and sign in with a Google account.
    2. Click "Get API key", then "Create API key".
    3. Copy the key and hand it to this script through an environment
       variable (so the key never lives inside the code):

       Windows (Command Prompt):   setx GEMINI_API_KEY "paste-your-key-here"
                                     (close and reopen the terminal after)
       Mac/Linux:                  export GEMINI_API_KEY="paste-your-key-here"

How to run:
  python fetch_news.py        # first, so there are fresh articles
  python digest_news.py

Try it WITHOUT a key first:
  python digest_news.py --mock
  Mock mode skips the real AI call and uses a built-in sample answer, so you
  can see exactly what the script does end to end before your key is ready.

A note on trust: AI models sometimes invent details. The digest is a
starting point - the original article (linked under each line) is the
source of truth.
"""

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

# --- Settings you can play with ---------------------------------------------

# Which Gemini model to ask. "gemini-3.5-flash-lite" is the sensible free-tier
# choice: about 500 free requests per day (the bigger Flash models give you
# only ~20). Limits change, so if Google renames things, update it here -
# the format is always https://generativelanguage.googleapis.com/v1beta/models/<model>:generateContent
MODEL = "gemini-3.5-flash-lite"

API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"

RETRY_WAIT_SECONDS = 30   # if Google says "slow down" (429), wait this long
MAX_RETRIES = 3           # ...and try again this many times before giving up

# latest_run.json lives next to this script; fetch_news.py writes it.
LATEST_RUN_FILE = Path(__file__).with_name("latest_run.json")
MOCK_DIR = Path(__file__).with_name("demo")
MOCK_LATEST_RUN_FILE = MOCK_DIR / "latest_run-SAMPLE-MOCK.json"

# --- The mock (practice mode) ------------------------------------------------

# A pretend Gemini answer, used when you run:  python digest_news.py --mock
# It lets you test everything EXCEPT the real network call.
MOCK_DIGEST = """## Top 3 this week

1. **India will lead world in green hydrogen production, says Nitin Gadkari** - the Union minister said India is on track to become the world's top green hydrogen producer.
2. **MNRE opens bids for green hydrogen hubs** - the ministry invited companies to bid for setting up hydrogen production hubs in three states.
3. **Cabinet clears subsidy scheme for hydrogen electrolysers** - manufacturers will get government support to build electrolyser plants in India.

## Policy
- **India will lead world in green hydrogen production, says Nitin Gadkari** - minister outlines the national mission's production targets. (moneycontrol.com)

## Subsidies
- **Cabinet clears subsidy scheme for hydrogen electrolysers** - new incentives for companies making electrolysers locally. (example.in)

## Tenders
- **MNRE opens bids for green hydrogen hubs** - companies can now bid to build hydrogen hubs in three states. (example.in)

## Industry
- No industry news in this batch.
"""

# Sample articles, used in --mock mode when there is no latest_run.json yet.
MOCK_ARTICLES = [
    {"title": "India will lead world in green hydrogen production, says Nitin Gadkari",
     "url": "https://example.com/1", "source": "moneycontrol.com", "seendate": "20261023T120000Z"},
    {"title": "Cabinet clears subsidy scheme for hydrogen electrolysers",
     "url": "https://example.com/2", "source": "example.in", "seendate": "20261024T090000Z"},
    {"title": "MNRE opens bids for green hydrogen hubs",
     "url": "https://example.com/3", "source": "example.in", "seendate": "20261025T150000Z"},
]


# --- Step 1: read the articles phase 1 found ---------------------------------

def load_articles(mock_mode=False):
    """Read articles from the real file or the separate practice file.

    Returns a list of dicts with title, url, source and seendate.
    """
    article_file = MOCK_LATEST_RUN_FILE if mock_mode else LATEST_RUN_FILE
    if not article_file.exists():
        print("I can't find latest_run.json next to this script.")
        print("That file is written by phase 1, so run this first:")
        print()
        print("    python fetch_news.py")
        print()
        print("Then run me again. (Or try me out with:  python digest_news.py --mock)")
        sys.exit(1)

    articles = json.loads(article_file.read_text(encoding="utf-8", errors="replace"))
    return articles


# --- Step 2: build the prompt (the instructions we send to the AI) -----------

def build_prompt(articles):
    """Turn the article list into clear instructions for Gemini.

    A 'prompt' is just the message we send the model. Being specific here is
    90% of getting a good answer back.
    """
    # One numbered line per article, with everything the model is allowed to use.
    lines = []
    for i, article in enumerate(articles, start=1):
        lines.append(
            f"{i}. {article.get('title', '(no title)')}\n"
            f"   Source: {article.get('source', 'unknown')}\n"
            f"   Link: {article.get('url', '')}"
        )
    article_block = "\n".join(lines)

    return f"""You are helping a student follow India's green hydrogen policy news.

Below are the latest news articles. Write a weekly digest in Markdown:

- Group the articles under exactly these headings, in this order:
  ## Policy, ## Subsidies, ## Tenders, ## Industry.
  Put "## Top 3 this week" first, listing the 3 most important articles.
- One line per article: its title in bold, then a dash, then a one-sentence
  plain-English summary a beginner can follow, then the source in brackets.
- If a group has no articles, write "No news in this group this week."
- Use ONLY the articles below. Never invent facts, numbers or quotes.
- Keep the whole digest under 250 words.

Articles:
{article_block}
"""


# --- Step 3: get the API key --------------------------------------------------

def get_api_key():
    """Read the Gemini API key from the environment.

    We keep the key OUT of the code on purpose: code gets shared, keys
    shouldn't. If it's missing, explain how to get one and stop politely.
    """
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if key:
        return key

    print("No Gemini API key found - the script needs one to talk to the AI.")
    print()
    print("Getting one is free and takes about 2 minutes:")
    print("  1. Go to https://aistudio.google.com and sign in with a Google account.")
    print("  2. Click 'Get API key', then 'Create API key', and copy it.")
    print("  3. Tell your computer about it (an 'environment variable'):")
    print()
    print('     Windows (Command Prompt):  setx GEMINI_API_KEY "your-key-here"')
    print("        then close and reopen the terminal.")
    print('     Mac/Linux:                 export GEMINI_API_KEY="your-key-here"')
    print()
    print("Then run me again. Want a preview without a key? Try:")
    print("    python digest_news.py --mock")
    sys.exit(1)


# --- Step 4: call Gemini ------------------------------------------------------

def call_gemini(prompt, api_key):
    """Send the prompt to Gemini and return the digest text.

    The request format is the standard Gemini 'generateContent' one:
    we POST JSON with our prompt inside, and the answer comes back inside
    a 'candidates' list.
    """
    body = {"contents": [{"parts": [{"text": prompt}]}]}
    headers = {"x-goog-api-key": api_key}

    for attempt in range(1, MAX_RETRIES + 2):   # first try + retries
        try:
            response = requests.post(API_URL, headers=headers, json=body, timeout=60)
        except requests.exceptions.RequestException:
            # No internet, DNS trouble, Google unreachable...
            print("Couldn't reach Google - check your internet connection")
            print("and try again in a minute.")
            sys.exit(1)

        if response.status_code == 429:
            # "Too many requests": the free tier has per-minute and per-day
            # limits. Wait politely and retry, like phase 1 does with GDELT.
            if attempt <= MAX_RETRIES:
                print(f"Google asked us to slow down. Waiting {RETRY_WAIT_SECONDS}s "
                      f"(try {attempt} of {MAX_RETRIES + 1})...")
                time.sleep(RETRY_WAIT_SECONDS)
                continue
            print("Google's free tier is used up for now (daily or per-minute limit).")
            print("Wait an hour and try again - the limit resets on its own.")
            sys.exit(1)

        if response.status_code in (400, 401, 403):
            print("Google rejected the API key (it may be mistyped or deleted).")
            print("Get a fresh one at https://aistudio.google.com and update the")
            print("GEMINI_API_KEY environment variable.")
            sys.exit(1)

        if response.status_code != 200:
            print(f"Unexpected answer from Google (status {response.status_code}):")
            print(response.text[:300])
            sys.exit(1)

        # Pull the text out of the response. It can arrive in several 'parts',
        # so join them all together.
        data = response.json()
        try:
            parts = data["candidates"][0]["content"]["parts"]
            return "".join(part.get("text", "") for part in parts).strip()
        except (KeyError, IndexError, TypeError):
            print("Gemini answered, but not with text (it may have refused the prompt).")
            print("Raw response:", json.dumps(data)[:300])
            sys.exit(1)


# --- Step 5: save and show the digest -----------------------------------------

def save_digest(digest_text, article_count, mock_mode=False):
    """Save a real digest or a clearly labeled practice digest."""
    today = datetime.now().strftime("%Y-%m-%d")
    if mock_mode:
        MOCK_DIR.mkdir(exist_ok=True)
        path = MOCK_DIR / f"digest-SAMPLE-MOCK-{today}.md"
        header = (f"# SAMPLE/MOCK Hydrogen news digest - {today}\n"
                  f"_SAMPLE/MOCK: based on {article_count} sample article(s); not a real AI summary._\n"
                  "_For practice only - AI can make mistakes; linked articles are the source of truth._\n\n")
    else:
        path = Path(__file__).with_name(f"digest-{today}.md")
        header = (f"# Hydrogen news digest - {today}\n"
                  f"_Based on {article_count} new article(s), summarised by {MODEL}._\n"
                  "_AI can make mistakes - the linked articles are the source of truth._\n\n")
    path.write_text(header + digest_text + "\n", encoding="utf-8")
    return path


# --- Main: tie the steps together ----------------------------------------------

def main():
    # Use UTF-8 so Windows can print symbols like ₹.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    # "--mock" = practice mode: everything runs except the real AI call.
    mock_mode = "--mock" in sys.argv

    if mock_mode and not MOCK_LATEST_RUN_FILE.exists():
        print("(mock mode: no sample file yet, using built-in sample articles)\n")
        articles = MOCK_ARTICLES
    else:
        articles = load_articles(mock_mode=mock_mode)

    if not articles:
        print("No new articles in latest_run.json - nothing to digest.")
        print("Run python fetch_news.py on a day with fresh news, then try again.")
        return

    print(f"Building a digest from {len(articles)} article(s)...\n")
    prompt = build_prompt(articles)

    if mock_mode:
        print("(mock mode: skipping the real Gemini call and using a sample answer)\n")
        digest_text = MOCK_DIGEST
    else:
        api_key = get_api_key()
        print(f"Asking Gemini ({MODEL}) to write the digest...")
        digest_text = call_gemini(prompt, api_key)

    print("=" * 70)
    print(digest_text)
    print("=" * 70)

    path = save_digest(digest_text, len(articles), mock_mode=mock_mode)
    print(f"\nSaved to {path.name} (next to this script).")
    print("Remember: skim the linked originals before quoting any of this.")


if __name__ == "__main__":
    main()