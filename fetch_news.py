#!/usr/bin/env python3
"""
fetch_news.py - Phase 1 of your hydrogen news tracker.

What it does (no AI yet - that is phase 2):
  1. Asks the GDELT news database for recent articles about green hydrogen
     in India (policy, subsidies, tenders, the national mission).
  2. Filters out articles that are not really on-topic.
  3. Skips articles you have already seen (remembered in a small JSON file).
  4. Prints this week's shortlist, newest first.

How to run it:
  pip install requests        # one time, installs the only extra library
  python fetch_news.py

Every run shows only NEW articles. To see everything again, delete
the seen_articles.json file it creates next to this script.

It also writes latest_run.json with the new articles' details. That is
the handoff to phase 2 (digest_news.py), which reads it and asks an AI
to write your weekly digest.
"""

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

# --- Settings you can play with ---------------------------------------------

# What we search for. GDELT query language:
#   "two words"  = exact phrase
#   OR           = any of these
#   sourcecountry:IN = only articles from Indian news sites
SEARCH_QUERY = '"hydrogen" (policy OR subsidy OR subsidies OR tender OR MNRE OR mission) sourcecountry:IN'

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

MAX_ARTICLES = 25          # how many to pull from GDELT in one go
RETRY_WAIT_SECONDS = 30    # GDELT rate-limits heavily; wait this long between retries
MAX_RETRIES = 4            # give up after this many tries

# GDELT already matched the policy/money words somewhere in the article text,
# so for the final shortlist we only require the TITLE to say "hydrogen" -
# that keeps out articles where hydrogen was just a passing mention.

# Where we remember what we have already shown you.
SEEN_FILE = Path(__file__).with_name("seen_articles.json")
# Phase 2 handoff: digest_news.py reads this file, always next to the scripts.
LATEST_RUN_FILE = Path(__file__).with_name("latest_run.json")

# --- The actual work ---------------------------------------------------------


def make_printing_safe():
    """Stop Windows from crashing this script on fancy characters.

    News headlines often contain characters like curly quotes or the rupee
    sign. Some Windows terminals use an old character set (called cp1252)
    that does not know those characters - and the old version of this script
    CRASHED with a UnicodeEncodeError the first time one appeared.

    The fix: switch printing to UTF-8 (the modern character set that knows
    every character), and if an odd character still cannot be shown, replace
    it with a '?' instead of crashing. You lose one character, not the run.
    """
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        # Very old Python or an unusual terminal: printing still works,
        # just without this extra safety net.
        pass


def load_seen_urls():
    """Read the list of article URLs we already showed you."""
    if not SEEN_FILE.exists():
        return set()
    try:
        with SEEN_FILE.open("r", encoding="utf-8") as f:
            return set(json.load(f))
    except (json.JSONDecodeError, OSError):
        # A broken or unreadable file should not crash the script -
        # worst case you see some articles twice.
        return set()


def save_seen_urls(urls):
    """Remember the article URLs so we never show them twice."""
    try:
        with SEEN_FILE.open("w", encoding="utf-8") as f:
            json.dump(sorted(urls), f, indent=2)
    except OSError as e:
        print(f"(warning: could not save seen list: {e})")


def save_latest_run(articles):
    """Write the new articles to latest_run.json for phase 2 (digest_news.py).

    We keep the useful fields only: title, link, source and date.
    """
    latest = []
    for article in articles:
        latest.append({
            "title": article.get("title", ""),
            "url": article.get("url", ""),
            "source": article.get("domain", ""),
            "seendate": article.get("seendate", ""),
        })
    LATEST_RUN_FILE.write_text(json.dumps(latest, indent=2), encoding="utf-8")


def fetch_from_gdelt():
    """
    Ask GDELT for matching articles.
    Returns a list of article dicts, or None if we could not get an answer.
    GDELT only answers a few requests per minute per network, so we wait
    and retry politely when it tells us to slow down.
    """
    params = {
        "query": SEARCH_QUERY,
        "mode": "artlist",       # plain list of articles
        "maxrecords": MAX_ARTICLES,
        "format": "json",
        "sort": "datedesc",      # newest first
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(
                GDELT_URL,
                params=params,
                timeout=30,
                headers={"User-Agent": "hydrogen-tracker-learning-project/1.0"},
            )
        except requests.RequestException as e:
            print(f"Could not reach GDELT (network problem): {e}")
            return None

        if response.status_code == 200:
            try:
                data = response.json()
            except json.JSONDecodeError:
                # GDELT sometimes answers 200 with a plain-text error
                # instead of JSON. Treat it like a failed try.
                print("GDELT answered, but not with data. Retrying...")
            else:
                return data.get("articles", [])

        elif response.status_code == 429:
            # 429 = "too many requests". Normal for GDELT; wait and retry.
            print(f"GDELT asked us to slow down "
                  f"(attempt {attempt} of {MAX_RETRIES}). "
                  f"Waiting {RETRY_WAIT_SECONDS}s...")
        else:
            print(f"GDELT returned an unexpected status: {response.status_code}")

        if attempt < MAX_RETRIES:
            time.sleep(RETRY_WAIT_SECONDS)

    print("GDELT stayed busy after several tries. Run the script again in a few minutes.")
    return None


def is_relevant(article):
    """Keep only articles whose title is actually about hydrogen."""
    title = (article.get("title") or "").lower()
    return "hydrogen" in title


def main():
    # First thing: make printing crash-proof on Windows (see the function).
    make_printing_safe()

    print("Fetching the latest India green-hydrogen news from GDELT...")
    print("(this can take a minute if GDELT is busy)\n")

    articles = fetch_from_gdelt()
    if articles is None:
        sys.exit(1)  # a non-zero exit code = "something went wrong"

    if not articles:
        print("GDELT found no matching articles right now.")
        print("Try widening SEARCH_QUERY or running again later.")
        return

    seen = load_seen_urls()
    fresh = []
    for article in articles:
        url = article.get("url", "")
        if url and url not in seen and is_relevant(article):
            fresh.append(article)

    if not fresh:
        print(f"Nothing new - you have already seen all {len(articles)} matching articles.")
        save_latest_run([])   # phase 2 will see an empty list and say so
        return

    # Hand the new articles to phase 2 (digest_news.py reads this file).
    save_latest_run(fresh)

    print(f"Found {len(fresh)} new article(s):\n")
    print("=" * 70)

    for i, article in enumerate(fresh, start=1):
        # GDELT dates look like 20261107T183000Z; make them human-friendly.
        raw_date = article.get("seendate", "")
        try:
            when = datetime.strptime(raw_date, "%Y%m%dT%H%M%SZ")
            when = when.replace(tzinfo=timezone.utc)
            date_text = when.strftime("%d %b %Y, %I:%M %p UTC")
        except ValueError:
            date_text = raw_date or "date unknown"

        print(f"{i}. {article.get('title', '(no title)')}")
        print(f"   {article.get('domain', 'unknown source')} - {date_text}")
        print(f"   {article.get('url', '')}")
        print()

    print("=" * 70)
    print("Open the links, skim, and note the ones worth your digest.")

    # Remember everything we saw, new or old, for next time.
    seen.update(a.get("url", "") for a in articles if a.get("url"))
    save_seen_urls(seen)


if __name__ == "__main__":
    main()