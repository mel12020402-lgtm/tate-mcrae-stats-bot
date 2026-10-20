
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


# ============================================================
# SETTINGS
# ============================================================

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


# ============================================================
# ARTICLE HELPERS
# ============================================================

def article_key(entry):
    """Create a stable ID to help prevent duplicate posts."""
    identifier = entry.get("id") or entry.get("link")

    if not identifier:
        identifier = entry.get("title", "Untitled article")

    return hashlib.sha256(
        identifier.strip().encode("utf-8")
    ).hexdigest()


def published_time(entry):
    """Format the article publication date."""
    published = entry.get("published_parsed")

    if published:
        return time.strftime("%d %b %Y, %H:%M UTC", published)

    return "Publication date unavailable"


def source_name(entry, title):
    """Extract the publisher name from the RSS entry."""
    source = (entry.get("source") or {}).get("title", "")

    if source:
        suffix = " - " + source

        if title.endswith(suffix):
            title = title[:-len(suffix)]

        return title.strip(), source

    if " - " in title:
        headline, publisher = title.rsplit(" - ", 1)
        return headline.strip(), publisher.strip()

    return title.strip(), "Google News"


# ============================================================
# ARTICLE IMAGE FINDER
# ============================================================

def get_article_image(url):
    """
    Resolve the Google News link, then look for an image
    on the publisher's article page.

    Some publishers block automated requests or don't expose
    their featured image, so an image isn't always available.
    """
    try:
        # Resolve the Google News redirect.
        result = gnewsdecoder(url, interval=1, timeout=15)

        if (
            not result
            or not result.get("success")
            or not result.get("decoded_url")
        ):
            print("Could not resolve Google News link.")
            return None

        article_url = result["decoded_url"]
        print(f"Resolved article: {article_url}")

        # Download the publisher's webpage.
        response = requests.get(
            article_url,
            headers=HEADERS,
            timeout=15,
        )
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        def valid_image(value):
            """Accept likely image URLs and reject obvious site icons."""
            if not isinstance(value, str) or not value.strip():
                return None

            value = urljoin(response.url, value.strip())

            if not value.startswith("https://"):
                return None

            if any(
                word in value.lower()
                for word in (
                    "logo",
                    "avatar",
                    "favicon",
                    "tracking",
                )
            ):
                return None

            return value

        # 1. Look for image links used by the publisher.
        for tag in soup.select('a[href*="/v3/re/new_assets/"]'):
            image_url = valid_image(tag.get("href"))

            if image_url:
                print(f"Found article image: {image_url}")
                return image_url

        # 2. Look inside the article content.
        article = soup.find("article") or soup.find("main")

        if article:
            for img in article.find_all("img"):
                for attribute in (
                    "src",
                    "data-src",
                    "data-original",
                    "data-lazy-src",
                ):
                    image_url = valid_image(img.get(attribute))

                    if image_url:
                        print(f"Found article-body image: {image_url}")
                        return image_url

                # Some sites use responsive image sources.
                srcset = img.get("srcset")

                if srcset:
                    first_image = srcset.split(",")[0].strip().split()[0]
                    image_url = valid_image(first_image)

                    if image_url:
                        print(f"Found responsive article image: {image_url}")
                        return image_url

        # 3. Fall back to social preview metadata.
        for attribute, value in (
            ("property", "og:image"),
            ("name", "twitter:image"),
        ):
            tag = soup.find("meta", attrs={attribute: value})

            if tag:
                image_url = valid_image(tag.get("content"))

                if image_url:
                    print(f"Using preview image: {image_url}")
                    return image_url

        print("No suitable article image was found.")
        return None

    except Exception as error:
        print(f"Could not retrieve article image: {error}")
        return None


# ============================================================
# DISCORD POSTING
# ============================================================


def post_article(entry):
    """Post one article as a pink Discord embed."""
    title = entry.get("title", "Untitled article")
    link = entry.get("link", "")

    if not link:
        print(f"Skipping article without a link: {title}")
        return False

    title, publisher = source_name(entry, title)
    date = published_time(entry)

    # Try the article image first.
    image_url = get_article_image(link)

    # Use the Housewife cover if no suitable image is found.
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
        timeout=30,
    )
    response.raise_for_status()

    print(f"Posted: {title}")
    return True


# ============================================================
# MAIN NEWS CHECK
# ============================================================

def main():
    """Fetch news, skip duplicates, and post new articles."""
    first_run = not HISTORY_FILE.exists()

    # Load previously posted article IDs.
    if HISTORY_FILE.exists():
        try:
            seen = json.loads(
                HISTORY_FILE.read_text(encoding="utf-8")
            )

            if not isinstance(seen, dict):
                seen = {}

        except (json.JSONDecodeError, OSError):
            seen = {}
    else:
        seen = {}

    # Fetch the Google News RSS feed.
    response = requests.get(
        FEED_URL,
        headers=HEADERS,
        timeout=30,
    )
    response.raise_for_status()

    feed = feedparser.parse(response.content)

    if not feed.entries:
        print("No news articles found.")
        return

    # Sort newest articles first.
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
        print("First run: setting up article history.")

        # Post up to five recent articles, and mark older
        # results as seen so the channel isn't flooded.
        candidates = entries[:MAX_FIRST_RUN_POSTS]

        for entry in entries[MAX_FIRST_RUN_POSTS:]:
            seen[article_key(entry)] = now

    else:
        # Only select articles that haven't been posted before.
        candidates = [
            entry
            for entry in entries
            if article_key(entry) not in seen
        ][:MAX_POSTS_PER_RUN]

    posted_count = 0

    for entry in candidates:
        key = article_key(entry)

        try:
            if post_article(entry):
                seen[key] = now
                posted_count += 1

        except requests.RequestException as error:
            # Don't mark failed posts as seen; they can be retried.
            print(
                f"Could not post "
                f"{entry.get('title', 'Unknown article')}: {error}"
            )

    # Keep the history file manageable.
    seen = dict(list(seen.items())[-MAX_HISTORY_ITEMS:])

    HISTORY_FILE.write_text(
        json.dumps(seen, indent=2),
        encoding="utf-8",
    )

    print(f"Finished! Articles posted: {posted_count}")


if __name__ == "__main__":
    main()
