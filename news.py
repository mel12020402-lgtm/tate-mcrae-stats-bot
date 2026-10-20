
import os
import json
import hashlib
import time
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import quote_plus, urljoin, urlparse

import requests
import feedparser
from bs4 import BeautifulSoup
from googlenewsdecoder import gnewsdecoder


# ==================================================
# SETTINGS
# ==================================================

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


# ==================================================
# ARTICLE HELPERS
# ==================================================

def article_key(entry):
    link = entry.get("link", "").strip()
    title = entry.get("title", "").strip()
    return hashlib.sha256(
        (link or title).encode("utf-8")
    ).hexdigest()


def published_time(entry):
    published = entry.get("published_parsed")

    if published:
        try:
            date = datetime(*published[:6], tzinfo=timezone.utc)
            return date.strftime("%d %b %Y")
        except (TypeError, ValueError):
            pass

    return "Date unavailable"


def source_name(entry, title):
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

    return title.strip(), (publisher or "News source").strip()


# ==================================================
# RESOLVE GOOGLE NEWS LINKS
# ==================================================

def resolve_article_url(url):
    """Try to decode a Google News URL into a publisher URL."""
    try:
        result = gnewsdecoder(url)

        if isinstance(result, dict):
            print(f"Decoder response: {result}")

            success = (
                result.get("status") is True
                or result.get("success") is True
            )

            original_url = (
                result.get("decoded_url")
                or result.get("url")
            )

            if original_url:
                original_url = original_url.strip()
                host = urlparse(original_url).netloc.lower()

                if (
                    success
                    and host
                    and "news.google.com" not in host
                    and original_url.startswith(("https://", "http://"))
                ):
                    print(f"Resolved publisher: {original_url}")
                    return original_url

    except Exception as error:
        print(f"Decoder error: {error}")

    # Try following ordinary HTTP redirects as a second attempt.
    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=20,
            allow_redirects=True,
            stream=True,
        )

        final_url = response.url
        response.close()

        host = urlparse(final_url).netloc.lower()

        if (
            host
            and "news.google.com" not in host
            and final_url.startswith(("https://", "http://"))
        ):
            print(f"Resolved through redirect: {final_url}")
            return final_url

    except requests.RequestException as error:
        print(f"Redirect resolution failed: {error}")

    print("WARNING: Publisher link could not be resolved.")
    return url


# ==================================================
# IMAGE HELPERS
# ==================================================

def is_good_image_url(image_url):
    if not image_url:
        return False

    if not image_url.startswith(("https://", "http://")):
        return False

    parsed = urlparse(image_url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()

    # Reject Google-hosted previews and Google News logos.
    if (
        "news.google.com" in host
        or "googleusercontent.com" in host
        or "gstatic.com" in host
    ):
        return False

    if any(
        word in path
        for word in (
            "favicon",
            "logo",
            "placeholder",
            "default-avatar",
        )
    ):
        return False

    return True


def get_article_image(url):
    """Find an image on the publisher's article page."""
    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=20,
        )
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        # Prefer the publisher's social preview metadata.
        for attribute, value in (
            ("property", "og:image"),
            ("property", "og:image:secure_url"),
            ("name", "twitter:image"),
        ):
            tag = soup.find("meta", attrs={attribute: value})

            if tag and tag.get("content"):
                image_url = urljoin(
                    response.url,
                    tag["content"].strip(),
                )

                if is_good_image_url(image_url):
                    print(f"Publisher preview image: {image_url}")
                    return image_url

        # If metadata isn't usable, inspect article images.
        article = soup.find("article") or soup.find("main")

        if article:
            for img in article.find_all("img"):
                description = " ".join([
                    str(img.get("alt", "")),
                    str(img.get("class", "")),
                    str(img.get("id", "")),
                ]).lower()

                if any(
                    word in description
                    for word in ("logo", "avatar", "icon", "favicon")
                ):
                    continue

                candidates = [
                    img.get("data-src"),
                    img.get("data-original"),
                    img.get("data-lazy-src"),
                    img.get("src"),
                ]

                srcset = img.get("srcset", "")

                if srcset:
                    for item in srcset.split(","):
                        parts = item.strip().split()
                        if parts:
                            candidates.append(parts[0])

                for candidate in candidates:
                    if not candidate:
                        continue

                    image_url = urljoin(
                        response.url,
                        candidate.strip(),
                    )

                    if is_good_image_url(image_url):
                        print(f"Publisher article image: {image_url}")
                        return image_url

        print("No suitable publisher image found.")
        return None

    except Exception as error:
        print(f"Image retrieval error: {error}")
        return None


# ==================================================
# POST TO DISCORD
# ==================================================

def post_article(entry):
    title = entry.get("title", "Untitled article")
    google_link = entry.get("link", "")

    if not google_link:
        print(f"Skipping article without a link: {title}")
        return False

    link = resolve_article_url(google_link)
    title, publisher = source_name(entry, title)
    date = published_time(entry)

image_url = get_article_image(link)

if not image_url:
    image_url = HOUSEWIFE_BACKUP_IMAGE
    print("Using the Housewife backup image.")

print(f"FINAL IMAGE URL: {image_url}")

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
    print(f"Article link: {link}")
    print(f"Image link: {image_url}")

    return True


# ==================================================
# MAIN BOT
# ==================================================

def main():
    print("Starting Tate McRae News Bot!")

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

    try:
        response = requests.get(
            FEED_URL,
            headers=HEADERS,
            timeout=30,
        )

        print(f"Google News HTTP status: {response.status_code}")
        response.raise_for_status()

        feed = feedparser.parse(response.content)

        print(f"Feed entries found: {len(feed.entries)}")
        print(f"Previously recorded articles: {len(seen)}")

    except requests.RequestException as error:
        print(f"ERROR fetching Google News: {error}")
        raise

    if not feed.entries:
        print("No articles found in the feed.")
        return

    entries = sorted(
        feed.entries,
        key=lambda entry: (
            entry.get("published_parsed") or time.gmtime(0)
        ),
        reverse=True,
    )

    now = datetime.now(timezone.utc).isoformat()

    if first_run:
        print("First run: setting up article history.")
        candidates = entries[:MAX_FIRST_RUN_POSTS]

        for entry in entries[MAX_FIRST_RUN_POSTS:]:
            seen[article_key(entry)] = now
    else:
        candidates = [
            entry for entry in entries
            if article_key(entry) not in seen
        ][:MAX_POSTS_PER_RUN]

    print(f"New articles selected to post: {len(candidates)}")

    posted = 0

    for entry in candidates:
        key = article_key(entry)

        try:
            if post_article(entry):
                seen[key] = now
                posted += 1

        except requests.RequestException as error:
            print(
                f"ERROR processing "
                f"{entry.get('title', 'Untitled')}: {error}"
            )

        except Exception as error:
            print(
                f"Unexpected error processing "
                f"{entry.get('title', 'Untitled')}: {error}"
            )

    if len(seen) > MAX_HISTORY_ITEMS:
        seen = dict(list(seen.items())[-MAX_HISTORY_ITEMS:])

    with HISTORY_FILE.open("w", encoding="utf-8") as file:
        json.dump(seen, file, indent=2)

    print(f"Finished! Articles posted: {posted}")


if __name__ == "__main__":
    main()
