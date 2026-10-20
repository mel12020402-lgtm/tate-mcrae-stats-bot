
import os
import requests
from billboard_charts import fetch_chart

WEBHOOK = os.environ["DISCORD_WEBHOOK_URL"]

CHARTS = {
    "Billboard Hot 100": {
        "slug": "hot-100",
        "url": "https://www.billboard.com/charts/hot-100/",
    },
    "Billboard 200 (albums)": {
        "slug": "billboard-200",
        "url": "https://www.billboard.com/charts/billboard-200/",
    },
    "Billboard Global 200": {
        "slug": "billboard-global-200",
        "url": "https://ca.billboard.com/charts/billboard-global-200",
    },
}

lines = ["📊 **TATE MCRAE — BILLBOARD CHART UPDATE**"]

for chart_name, details in CHARTS.items():
    slug = details["slug"]
    url = details["url"]

    lines.append(f"\n**[{chart_name}]({url})**")

    try:
        entries = fetch_chart(slug)

        if not entries:
            lines.append("Chart entries unavailable.")
            continue

        chart_date = entries[0].get(
            "Date", "Latest published chart"
        )
        matches = [
            entry for entry in entries
            if "tate mcrae" in str(
                entry.get("Artist", "")
            ).lower()
        ]

        lines.append(f"*Chart date: {chart_date}*")

        if not matches:
            lines.append(
                "No Tate McRae entries found in the retrieved chart."
            )
            continue

        for entry in matches:
            rank = entry.get("Rank", "?")
            title = entry.get("Song", "Unknown title")
            previous = entry.get("Last Week")
            peak = entry.get("Peak Position", "?")
            weeks = entry.get("Weeks on Chart", "?")

            if previous in (None, 0, "0", "-"):
                movement = "NEW / RE-ENTRY"
            elif str(previous) == str(rank):
                movement = "↔ Unchanged"
            else:
                try:
                    change = int(previous) - int(rank)
                    if change > 0:
                        movement = f"↑ {change} places"
                    else:
                        movement = f"↓ {abs(change)} places"
                except (TypeError, ValueError):
                    movement = "Movement unavailable"

            lines.append(
                f"• **#{rank}** — {title}\n"
                f"  {movement} · Peak #{peak} · "
                f"Weeks on chart: {weeks}"
            )

    except Exception as error:
        print(f"Chart error for {chart_name}: {error}")
        lines.append(
            "Chart data temporarily unavailable. "
            "Check the workflow logs for details."
        )

message = "\n".join(lines)

if len(message) > 1900:
    message = message[:1850] + "\n\nReport shortened."

response = requests.post(
    WEBHOOK,
    json={"content": message},
    timeout=30,
)
response.raise_for_status()

print("Billboard chart report posted.")
