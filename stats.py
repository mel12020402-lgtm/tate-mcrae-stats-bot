
import os
import re
from datetime import datetime, timezone

import pandas as pd
import requests

URL = (
    "https://kworb.net/spotify/artist/"
    "45dkTj5sMRSjrmBSBeiHym_songs.html"
)
WEBHOOK = os.environ["DISCORD_WEBHOOK_URL"]


def number(value):
    """Turn a displayed number into an integer."""
    match = re.search(r"\d[\d,]*", str(value))
    if not match:
        raise ValueError(f"Couldn't read number: {value}")
    return int(match.group(0).replace(",", ""))


response = requests.get(
    URL,
    headers={"User-Agent": "TateStatsDiscordBot/1.0"},
    timeout=30,
)
response.raise_for_status()

page = response.text
tables = pd.read_html(page)

# Find the summary table containing total and daily streams.
summary = None
for table in tables:
    first_column = table.iloc[:, 0].astype(str).str.strip()
    labels = set(first_column)
    if "Streams" in labels and "Daily" in labels:
        summary = table
        break

if summary is None:
    raise ValueError("Kworb's summary table was not recognised.")

first_column = summary.iloc[:, 0].astype(str).str.strip()
total_row = summary.loc[first_column == "Streams"].iloc[0]
daily_row = summary.loc[first_column == "Daily"].iloc[0]

total_streams = number(total_row.iloc[1])
daily_streams = number(daily_row.iloc[1])

# Find the individual-song table.
songs = None
for table in tables:
    columns = [str(c).lower() for c in table.columns]
    if any("song title" in c for c in columns) and any(
        c.strip() == "daily" for c in columns
    ):
        songs = table.copy()
        break

if songs is None:
    raise ValueError("Kworb's song table was not recognised.")

def find_column(columns, phrase):
    for column in columns:
        if phrase in str(column).lower():
            return column
    raise ValueError(f"Missing column: {phrase}")

title_col = find_column(songs.columns, "song title")
daily_col = find_column(songs.columns, "daily")

songs["_daily_number"] = songs[daily_col].map(number)
top_songs = songs.sort_values(
    "_daily_number", ascending=False
).head(5)

song_lines = "\n".join(
    f"• **{row[title_col]}** — {row['_daily_number']:,} streams"
    for _, row in top_songs.iterrows()
)

# Use the date displayed on the source page, if available.
date_match = re.search(
    r"Last updated:\s*(\d{4}/\d{2}/\d{2})", page
)
source_date = date_match.group(1) if date_match else "Date unavailable"

message = (
    "📊 **TATE MCRAE — DAILY SPOTIFY STATS**\n"
    f"**Source reporting date:** {source_date}\n\n"
    f"🎧 **Total streams:** {total_streams:,}\n"
    f"📈 **Daily streams:** {daily_streams:,}\n\n"
    f"**Top songs by daily streams**\n{song_lines}\n\n"
    f"🔗 [View Kworb source]({URL})"
)

if len(message) > 1900:
    raise ValueError("Report is too long for a single Discord message.")

posted = requests.post(
    WEBHOOK,
    json={"content": message},
    timeout=30,
)
posted.raise_for_status()
print("Stats report posted successfully.")
