
import os
import re
import pandas as pd
import requests

URL = (
    "https://kworb.net/spotify/artist/"
    "45dkTj5sMRSjrmBSBeiHym_songs.html"
)

WEBHOOK = os.environ["DISCORD_WEBHOOK_URL"]


def number(value):
    """Extract a number from a displayed value."""
    match = re.search(r"\d[\d,]*", str(value))
    if not match:
        raise ValueError(f"Couldn't read number: {value}")
    return int(match.group(0).replace(",", ""))


def safe_number(value):
    """Return zero for missing values, for sorting only."""
    if pd.isna(value) or not re.search(r"\d", str(value)):
        return 0
    return number(value)


response = requests.get(
    URL,
    headers={"User-Agent": "Mozilla/5.0 TateStatsBot/1.0"},
    timeout=30,
)
response.raise_for_status()

page = response.text
tables = pd.read_html(page)

# Find the summary table.
summary = None

for table in tables:
    if table.empty:
        continue

    first_column = table.iloc[:, 0].astype(str).str.strip()
    labels = set(first_column)

    if "Streams" in labels and "Daily" in labels:
        summary = table
        break

if summary is None:
    raise ValueError("Could not find the Spotify summary table on Kworb.")

first_column = summary.iloc[:, 0].astype(str).str.strip()

total_row = summary.loc[first_column == "Streams"].iloc[0]
daily_row = summary.loc[first_column == "Daily"].iloc[0]

total_streams = number(total_row.iloc[1])
daily_streams = number(daily_row.iloc[1])

# Find the song table.
songs = None

for table in tables:
    columns = [str(column).strip().lower() for column in table.columns]

    if (
        any("song title" in column for column in columns)
        and any(column == "daily" for column in columns)
    ):
        songs = table.copy()
        break

if songs is None:
    raise ValueError("Could not find the song table on Kworb.")

def find_column(columns, phrase):
    for column in columns:
        if phrase in str(column).lower():
            return column
    raise ValueError(f"Missing column: {phrase}")


title_col = find_column(songs.columns, "song title")
daily_col = find_column(songs.columns, "daily")

songs["_daily_number"] = songs[daily_col].map(safe_number)

top_songs = songs.sort_values(
    "_daily_number", ascending=False
).head(5)

song_lines = "\n".join(
    f"• **{row[title_col]}** — {row['_daily_number']:,} streams"
    for _, row in top_songs.iterrows()
)

# Find the source reporting date, if Kworb includes it.
date_match = re.search(
    r"Last updated:\s*(\d{4}/\d{2}/\d{2})",
    page,
)

source_date = (
    date_match.group(1)
    if date_match
    else "Check source page for reporting date"
)

message = (
    "📊 **TATE MCRAE — DAILY SPOTIFY STATS**\n"
    f"**Source reporting date:** {source_date}\n\n"
    f"🎧 **Total streams:** {total_streams:,}\n"
    f"📈 **Daily streams:** {daily_streams:,}\n\n"
    f"**Top songs by daily streams**\n{song_lines}\n\n"
    f"🔗 [View Kworb source]({URL})"
)

if len(message) > 1900:
    raise ValueError("Report is too long for one Discord message.")

posted = requests.post(
    WEBHOOK,
    json={"content": message},
    timeout=30,
)
posted.raise_for_status()

print("Stats report posted successfully.")

