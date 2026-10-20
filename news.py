
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


# ==================================================
# ARTICLE HELPERS
# ==================================================

def article_key(entry):
    """Create a unique ID for an article."""
    link = entry.get("link", "").strip()
    title = entry.get("title", "").strip()

    return hashlib.sha256(
        (link or title).encode("utf-8")
    ).hexdigest()


def published_time(entry):
    """Format the article's publication date."""
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
    """Get the publisher name and clean the headline."""
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


# ==================================================
# RESOLVE GOOGLE NEWS LINKS
# ==================================================

def resolve_article_url(url):
    """Try to get the original publisher's article URL."""
    try:
        decoded = gnewsdecoder(url)

        if isinstance(decoded, dict) and decoded.get("status"):
            original_url = (
                decoded.get("decoded_url")
                or decoded.get("url")
            )

            if original_url:
                host = urlparse(original_url).netloc.lower()

                if (
                    host
                    and "news.google.com" not in host
                    and original_url.startswith(("https://", "http://"))
                ):
                    print(f"Publisher article: {original_url}")
                    return original_url

    except Exception as error:
        print(f"Link decoding failed: {error}")

    print("Using the original Google News link.")
    return url


# ==================================================
# IMAGE HELPERS
# ==================================================

def is_good_image_url(image_url):
    """Reject obvious logos, icons and Google News image links."""
    if not image_url:
        return False

    if not image_url.startswith(("https://", "http://")):
        return False

    parsed = urlparse(image_url)
    host = parsed.netloc.lower()
    image_text = (
        parsed.path + " " + parsed.query
    ).lower()

    # Don't use Google News pages as embed images.
    if "news.google.com" in host:
        return False

    # Avoid obvious logos, icons and tiny site graphics.
    unwanted_terms = [
        "favicon",
        "google-news-logo",
        "google_news_logo",
        "site-logo",
        "site_logo",
        "placeholder",
        "default-avatar",
    ]

    if any(term in image_text for term in unwanted_terms):
        return False

    return True


def get_article_image(url):
    """Find the best available article image."""
    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=20
        )
        response.raise_for_status()

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        # First, check the publisher's social-sharing images.
        # These are often the full-sized article photographs.
        for attribute, value in [
            ("property", "og:image"),
            ("name", "twitter:image"),
            ("property", "og:image:secure_url"),
        ]:
            tag = soup.find(
                "meta",
                attrs={attribute: value}
            )

            if tag and tag.get("content"):
                image_url = urljoin(
                    url,
                    tag["content"].strip()
                )

                if is_good_image_url(image_url):
                    print(f"Found article preview image: {image_url}")
                    return image_url

        # Next, search images within the article itself.
        article = soup.find("article")

        if not article:
            article = soup.find("main")

        if article:
            images = article.find_all("img")

            # Prefer images with larger declared dimensions.
            def image_size(img):
                try:
                    width = int(img.get("width", 0))
                    height = int(img.get("height", 0))
                    return width * height
                except (TypeError, ValueError):
                    return 0

            images.sort(
                key=image_size,
                reverse=True
            )

            for img in images:
                description = " ".join([
                    str(img.get("alt", "")),
                    str(img.get("class", "")),
                    str(img.get("id", "")),
                ]).lower()

                if any(
                    word in description
                    for word in [
                        "logo",
                        "avatar",
                        "icon",
                        "favicon",
                    ]
                ):
                    continue

                candidates = [
                    img.get("data-src"),
                    img.get("data-original"),
                    img.get("data-lazy-src"),
                    img.get("src"),
                ]

                # Also check responsive image sources.
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
                        url,
                        candidate.strip()
                    )

                    if is_good_image_url(image_url):
                        print(f"Found article image: {image_url}")
                        return image_url

        print("No suitable article image found.")
        return None

    except Exception as error:
        print(f"Image search failed: {error}")
        return None


# ==================================================
# POST AN ARTICLE TO DISCORD
# ==================================================

def post_article(entry):
    """Create and send a pink Discord news embed."""
    title = entry.get("title", "Untitled article")
    google_link = entry.get("link", "")

    if not google_link:
        print(f"Skipping article without a link: {title}")
        return False

    # Resolve the Google News redirect if possible.
    link = resolve_article_url(google_link)

    title, publisher = source_name(entry, title)
    date = published_time(entry)

    # Search the original publisher's page for its image.
    image_url = get_article_image(link)

    # Use the backup cover if no suitable image is found.
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
    print(f"Article link: {link}")
    print(f"Image link: {image_url}")

    return True


# ==================================================
# MAIN BOT
# ==================================================

def main():
    print("Starting Tate McRae News Bot!")

    # Load the article history so old stories aren't reposted.
    first_run = not HISTORY_FILE.exists()

    try:
        with HISTORY_FILE.open(
            "r",
            encoding="utf-8"
        ) as file:
            seen = json.load(file)

        if not isinstance(seen, dict):
            seen = {}

    except (json.JSONDecodeError, OSError):
        seen = {}

    if not seen:
        first_run = True

    # Fetch Google News.
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
        print(f"ERROR fetching Google News: {error}")
        raise

    if not feed.entries:
        print("No articles found in the Google News feed.")
        return

    # Sort articles from newest to oldest.
    entries = sorted(
        feed.entries,
        key=lambda entry: (
            entry.get("published_parsed") or time.gmtime(0)
        ),
        reverse=True
    )

    now = datetime.now(timezone.utc).isoformat()

    # Select new articles to post.
    if first_run:
        print("First run: setting up article history.")

        candidates = entries[:MAX_FIRST_RUN_POSTS]

        # Mark older stories as seen without posting them.
        for entry in entries[MAX_FIRST_RUN_POSTS:]:
            seen[article_key(entry)] = now

    else:
        candidates = [
            entry
            for entry in entries
            if article_key(entry) not in seen
        ][:MAX_POSTS_PER_RUN]

    print(
        f"New articles selected to post: {len(candidates)}"
    )

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
                f"Unexpected article error "
                f"for {entry.get('title', 'Untitled')}: {error}"
            )

    # Limit the size of the saved history.
    if len(seen) > MAX_HISTORY_ITEMS:
        seen = dict(
            list(seen.items())[-MAX_HISTORY_ITEMS:]
        )

    # Save the history.
    try:
        with HISTORY_FILE.open(
            "w",
            encoding="utf-8"
        ) as file:
            json.dump(seen, file, indent=2)

    except OSError as error:
        print(f"ERROR saving article history: {error}")
        raise

    print(f"Finished! Articles posted: {posted}")


if __name__ == "__main__":
    main()
