
import os
import requests
from billboard_charts import fetch_chart

# Discord webhook from your GitHub repository secret
WEBHOOK = os.environ["DISCORD_WEBHOOK_URL"]

# Discord role ID to ping
ROLE_ID = "1570273188007379024"

# Tate McRae banner image
IMAGE_URL = (
    "https://cloudimages.broadwayworld.com/columnpiccloud/"
    "Tate-McRae-Announces-Sophomore-Album-Think-Later-2024-"
    "Global-Think-Later-Tour--1699270565.jpg"
)

# Billboard charts to check
CHARTS = {
    "Billboard Hot 100": {
        "slug": "hot-100",
        "url": "https://www.billboard.com/charts/hot-100/",
    },
    "Billboard 200 (Albums)": {
        "slug": "billboard-200",
        "url": "https://www.billboard.com/charts/billboard-200/",
    },
    "Billboard Global 200": {
        "slug": "billboard-global-200",
        "url": "https://ca.billboard.com/charts/billboard-global-200",
    },
}

# Collect the chart results
lines = []

for chart_name, chart_info in CHARTS.items():
    url = chart_info["url"]
    slug = chart_info["slug"]

    lines.append(f"**[{chart_name}]({url})**")

    try:
        entries = fetch_chart(slug)

        if not entries:
            lines.append("Chart data unavailable.\n")
            continue

        chart_date = entries[0].get(
            "Date", "Latest published chart"
        )
        lines.append(f"*Chart date: {chart_date}*")

        matches = [
            entry for entry in entries
            if "tate mcrae" in str(
                entry.get("Artist", "")
            ).lower()
        ]

        if not matches:
            lines.append(
                "No Tate McRae entries found in this chart.\n"
            )
            continue

        for entry in matches:
            rank = entry.get("Rank", "?")
            song = entry.get("Song", "Unknown title")
            previous = entry.get("Last Week")
            peak = entry.get("Peak Position", "?")
            weeks = entry.get("Weeks on Chart", "?")

            if previous in (None, 0, "0", "-"):
                movement = "NEW / RE-ENTRY"
            else:
                try:
                    change = int(previous) - int(rank)

                    if change > 0:
                        movement = f"↑ Up {change} places"
                    elif change < 0:
                        movement = f"↓ Down {abs(change)} places"
                    else:
                        movement = "↔ Unchanged"

                except (TypeError, ValueError):
                    movement = "Movement unavailable"

            lines.append(
                f"• **#{rank} — {song}**\n"
                f"  {movement} · Peak #{peak} · "
                f"Weeks on chart: {weeks}"
            )

        lines.append("")

    except Exception as error:
        print(f"Error fetching {chart_name}: {error}")
        lines.append("Chart data temporarily unavailable.\n")

# Prepare the chart text
description = "\n".join(lines)

if len(description) > 4000:
    description = description[:3950] + "\n\nReport shortened."

# Send the role ping and chart report
response = requests.post(
    WEBHOOK,
    json={
        "content": f"<@&{ROLE_ID}>",
        "allowed_mentions": {
            "parse": [],
            "roles": [ROLE_ID]
        },
        "embeds": [
            {
                "author": {
                    "name": "TATE MCRAE • WEEKLY CHART REPORT"
                },
                "title": "📊 Billboard Chart Update",
                "description": description,
                "image": {"url": IMAGE_URL},
                "color": 0xDFA6C8,
                "footer": {
                    "text": "Tate McRae • Billboard chart tracking"
                },
            }
        ]
    },
    timeout=30,
)

response.raise_for_status()

print("Successfully posted Tate McRae's weekly Billboard chart update!")
