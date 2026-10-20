
import os
import json
import hashlib
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta
from urllib.parse import quote_plus

import requests
import feedparser
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# Separate webhook for the news channel
WEBHOOK = os.environ["DISCORD_NEWS_WEBHOOK_URL"]

# Remember which articles have already been posted
HISTORY_FILE = Path("posted_articles.json")

# Search Google News across publishers, using the Australian English edition
QUERY = '"Tate McRae" when:7d'
FEED_URL = (
    "https://news.google.com/rss/search?q="
    + quote_plus(QUERY)
    + "&hl=en-AU&gl=AU&ceid=AU:en"
)

PINK = 0xDFA6C8


def article_key(entry):
    """Create a stable identifier to prevent repeat posts."""
    identifier = entry.get("id") or entry.get("link")

    if not identifier:
        identifier = entry.get("title", "Untitled article")

    return hashlib.sha256(
        identifier.strip().encode("utf-8")
    ).hexdigest()


def published_time(entry):
    """Return a readable publication date."""
    published = entry.get("published_parsed")

    if published:
        return time.strftime(
            "%d %b %Y, %H:%M UTC",
            published,
        )

    return "Publication date unavailable"


def source_name(entry, title):
    """Get the publisher name when Google News supplies it."""
    source = entry.get("source", {}).get("title", "")

    if source:
        suffix = " - " + source

        if title.endswith(suffix):
            title = title[:-len(suffix)]

        return title.strip(), source

    # Google News titles often end with ' - Publisher'
    if " - " in title:
        headline, publisher = title.rsplit(" - ", 1)
        return headline.strip(), publisher.strip()

    return title.strip(), "Google News"

def get_article_image(url):
    """Find the article's preview image."""
    try:
        response = requests.get(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (compatible; TateMcRaeNewsBot/1.0)"
                )
            },
            timeout=15,
        )
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        # Try the most common image preview tags
        image_tag = (
            soup.find("meta", property="og:image")
            or soup.find("meta", attrs={"name": "twitter:image"})
        )

        if image_tag and image_tag.get("content"):
            image_url = urljoin(
                response.url,
                image_tag["content"].strip()
            )

            if image_url.startswith("https://"):
                return image_url

    except Exception as error:
        print(f"Could not retrieve article image: {error}")

    return None

def post_article(entry):
    """Post one article with its image when available."""
    title = entry.get("title", "Untitled article")
    link = entry.get("link", "")

    if not link:
        print(f"Skipping article without a link: {title}")
        return False

    title, publisher = source_name(entry, title)
    date = published_time(entry)

    # Find the article's front-page image
    image_url = get_article_image(link)

    embed = {
        "author": {
            "name": "TATE MCRAE  •  NEWS UPDATE"
        },
        "title": title[:250],
        "url": link,
        "description": (
            f"📰 **Source:** {publisher}\n"
            f"📅 **Published:** {date}\n\n"
            f"[Read the full article]({link})"
        ),
        "color": PINK,
        "footer": {
            "text": "Tate McRae News  •  New article"
        },
    }

    # Add the large article image if one was found
    if image_url:
        embed["image"] = {"url": image_url}
    else:
        print(f"No preview image found for: {title}")

    response = requests.post(
        WEBHOOK,
        json={"embeds": [embed]},
        timeout=30,
    )

    response.raise_for_status()
    print(f"Posted: {title}")
    return True


def main():
    # Load previously posted article history
    first_run = not HISTORY_FILE.exists()

    if HISTORY_FILE.exists():
        try:
            seen = json.loads(
                HISTORY_FILE.read_text(encoding="utf-8")
            )
        except (json.JSONDecodeError, OSError):
            seen = {}
    else:
        seen = {}

    # Retrieve the latest Google News results
    response = requests.get(
        FEED_URL,
        headers={"User-Agent": "TateMcRaeNewsBot/1.0"},
        timeout=30,
    )
    response.raise_for_status()

    feed = feedparser.parse(response.content)

    if not feed.entries:
        print("No news articles found in this check.")

    # Newest articles first
    entries = sorted(
        feed.entries,
        key=lambda entry: (
            time.mktime(entry.published_parsed)
            if entry.get("published_parsed")
            else 0
        ),
        reverse=True,
    )

    now = datetime.now(timezone.utc).isoformat()

    if first_run:
        # First run: post up to the 5 newest articles,
        # and mark older results as already seen.
        # This prevents a huge backlog from flooding Discord.
        print("First run: setting up article history.")

        for entry in entries[5:]:
            seen[article_key(entry)] = now

        candidates = entries[:5]
    else:
        # Later runs: only articles not seen before
        candidates = [
            entry for entry in entries
            if article_key(entry) not in seen
        ][:10]

    posted_count = 0

    for entry in candidates:
        key = article_key(entry)

        try:
            if post_article(entry):
                seen[key] = now
                posted_count += 1

        except requests.RequestException as error:
            print(
                f"Could not post article "
                f"{entry.get('title', 'Unknown')}: {error}"
            )

    # Keep the history file manageable
    seen = dict(list(seen.items())[-2000:])

    HISTORY_FILE.write_text(
        json.dumps(seen, indent=2),
        encoding="utf-8",
    )

    print(f"Finished. Articles posted this run: {posted_count}")


if __name__ == "__main__":
    main()
