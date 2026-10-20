
import os
import json
import hashlib
import time
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import quote_plus, urljoin

import requests
import feedparser
from bs4 import BeautifulSoup
from googlenewsdecoder import gnewsdecoder


# --------------------------------------------------
# SETTINGS
# --------------------------------------------------

WEBHOOK = os.environ["DISCORD_NEWS_WEBHOOK_URL"]

HISTORY_FILE = Path("posted_articles.json")

QUERY = '"Tate McRae" when:7d'

FEED_URL = (
    "https://news.google.com/rss/search?q="
    + quote_plus(QUERY)
    + "&hl=en-AU&gl=AU&ceid=AU:en"
)

PINK = 0xDFA6C8

HOUSEWIFE_BACKUP_IMAGE = (
    "https://www.billboard.com/wp-content/uploads/2026/10/"
    "tate-mcrae-housewife-press-billboard-1800.jpg"
    "?w=942&h=628&crop=1"
)

MAX_FIRST_RUN_POSTS = 5
MAX_POSTS_PER_RUN = 10
MAX_HISTORY_ITEMS = 2000

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"
    )
}


# --------------------------------------------------
# ARTICLE HELPERS
# --------------------------------------------------

def article_key(entry):
    """Create a consistent ID for each article."""
    link = entry.get("link", "").strip()
    title = entry.get("title", "").strip()
    article_id = link or title

    return hashlib.sha256(
        article_id.encode("utf-8")
    ).hexdigest()


def published_time(entry):
    """Format the article publication date."""
    published = entry.get("published_parsed")

    if published:
        try:
            date = datetime(
                *published[:6],
                tzinfo=timezone.utc
            )
            return date.strftime("%d %b %Y")
        except (TypeError, ValueError):
            pass

    return "Date unavailable"


def source_name(entry, title):
    """Separate the article headline from its publisher."""
    source = entry.get("source", {})
    publisher = ""

    if hasattr(source, "get"):
        publisher = source.get("title", "")

    if publisher:
        suffix = " - " + publisher

        if title.endswith(suffix):
            title = title[:-len(suffix)]

    elif " - " in title:
        title, publisher = title.rsplit(" - ", 1)

    if not publisher:
        publisher = "News source"

    return title.strip(), publisher.strip()


# --------------------------------------------------
# FIND ARTICLE IMAGES
# --------------------------------------------------

def get_article_image(url):
    """Try to find the main image on an article page."""
    article_url = url

    try:
        decoded = gnewsdecoder(url)

        if isinstance(decoded, dict):
            if decoded.get("status") and decoded.get("decoded_url"):
                article_url = decoded["decoded_url"]

    except Exception as error:
        print(f"Could not decode article URL: {error}")

    try:
        response = requests.get(
            article_url,
            headers=HEADERS,
            timeout=20
        )
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        # First choice: the article's official preview image.
        for attribute, value in [
            ("property", "og:image"),
            ("name", "twitter:image"),
        ]:
            tag = soup.find("meta", attrs={attribute: value})

            if tag and tag.get("content"):
                image_url = urljoin(
                    article_url,
                    tag["content"].strip()
                )

                if image_url.startswith(("http://", "https://")):
                    return image_url

        # Second choice: images inside the article.
        article = soup.find("article")

        if not article:
            article = soup.find("main")

        if article:
            for img in article.find_all("img"):
                for attribute in [
                    "src",
                    "data-src",
                    "data-original",
                    "data-lazy-src",
                ]:
                    image_url = img.get(attribute)

                    if image_url:
                        image_url = urljoin(
                            article_url,
                            image_url.strip()
                        )

                        if image_url.startswith(
                            ("http://", "https://")
                        ):
                            return image_url

                # Some sites store images in srcset.
                srcset = img.get("srcset", "")

                if srcset:
                    image_url = srcset.split(",")[0].strip().split(" ")[0]
                    image_url = urljoin(article_url, image_url)

                    if image_url.startswith(
                        ("http://", "https://")
                    ):
                        return image_url

        print(f"No article image found: {article_url}")
        return None

    except Exception as error:
        print(f"Could not retrieve article image: {error}")
        return None


# --------------------------------------------------
# SEND ARTICLE TO DISCORD
# --------------------------------------------------

def post_article(entry):
    """Post one article as a pink Discord embed."""
    title = entry.get("title", "Untitled article")
    link = entry.get("link", "")

    if not link:
        print(f"Skipping article without a link: {title}")
        return False

    title, publisher = source_name(entry, title)
    date = published_time(entry)

    image_url = get_article_image(link)

    if not image_url:
        image_url = HOUSEWIFE_BACKUP_IMAGE
        print("Using the Housewife backup image.")

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
        "image": {
            "url": image_url
        },
    }

    response = requests.post(
        WEBHOOK,
        json={"embeds": [embed]},
        timeout=30
    )

    response.raise_for_status()

    print(f"Posted: {title}")
    return True


# --------------------------------------------------
# MAIN NEWS BOT
# --------------------------------------------------

def main():
    print("Starting Tate McRae News Bot...")

    # Load previously recorded articles.
    first_run = not HISTORY_FILE.exists()

    try:
        with HISTORY_FILE.open("r", encoding="utf-8") as file:
            seen = json.load(file)

        if not isinstance(seen, dict):
            seen = {}

    except (json.JSONDecodeError, OSError):
        seen = {}

    if not seen:
        first_run = True

    # Fetch the Google News RSS feed.
    try:
        response = requests.get(
            FEED_URL,
            headers=HEADERS,
            timeout=30
        )

        print(
            f"Google News HTTP status: {response.status_code}"
        )

        response.raise_for_status()

        feed = feedparser.parse(response.content)

        print(f"Feed entries found: {len(feed.entries)}")
        print(f"History file exists: {HISTORY_FILE.exists()}")
        print(f"Previously recorded articles: {len(seen)}")

    except requests.RequestException as error:
        print(f"ERROR: Could not fetch Google News: {error}")
        raise

    if not feed.entries:
        print("No articles were returned by Google News.")
        return

    # Put the newest articles first.
    entries = sorted(
        feed.entries,
        key=lambda entry: (
            entry.get("published_parsed") or time.gmtime(0)
        ),
        reverse=True
    )

    now = datetime.now(timezone.utc).isoformat()

    # Choose articles to post.
    if first_run:
        print("First run: setting up article history.")

        candidates = entries[:MAX_FIRST_RUN_POSTS]

        # Record older articles without posting them all.
        for entry in entries[MAX_FIRST_RUN_POSTS:]:
            seen[article_key(entry)] = now

    else:
        candidates = [
            entry
            for entry in entries
            if article_key(entry) not in seen
        ][:MAX_POSTS_PER_RUN]

    print(f"New articles selected to post: {len(candidates)}")

    # Post the selected articles.
    posted = 0

    for entry in candidates:
        key = article_key(entry)

        try:
            if post_article(entry):
                seen[key] = now
                posted += 1

        except requests.RequestException as error:
            print(
                f"ERROR posting article "
                f"{entry.get('title', 'Untitled')}: {error}"
            )

        except Exception as error:
            print(
                f"Unexpected error for "
                f"{entry.get('title', 'Untitled')}: {error}"
            )

    # Keep the history file from growing indefinitely.
    if len(seen) > MAX_HISTORY_ITEMS:
        seen = dict(
            list(seen.items())[-MAX_HISTORY_ITEMS:]
        )

    # Save article history.
    try:
        with HISTORY_FILE.open("w", encoding="utf-8") as file:
            json.dump(seen, file, indent=2)

    except OSError as error:
        print(f"ERROR saving article history: {error}")
        raise

    print(f"Finished! Articles posted: {posted}")


if __name__ == "__main__":
    main()
