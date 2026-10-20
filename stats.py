import os
import requests
from billboard_charts import fetch_chart

WEBHOOK = os.environ["DISCORD_WEBHOOK_URL"]

CHARTS = {
    "Billboard Hot 100": "hot-100",
    "Billboard 200 (albums)": "billboard-200",
    "Billboard Global 200": "global-200",
}

lines = ["📊 **TATE MCRAE — BILLBOARD CHART UPDATE**"]

for chart_name, slug in CHARTS.items():
    lines.append(f"\n**{chart_name}**")

    try:
        entries = fetch_chart(slug)

        if not entries:
            lines.append("Could not retrieve chart entries.")
            continue

        chart_date = entries[0].get("Date", "Latest published chart")
        matches = [
            entry for entry in entries
            if "tate mcrae" in str(entry.get("Artist", "")).lower()
        ]

        lines.append(f"*Chart date: {chart_date}*")

        if not matches:
            lines.append("No Tate McRae entries in this chart.")
            continue

        for entry in matches:
            rank = entry.get("Rank", "?")
            title = entry.get("Song", "Unknown title")
            previous = entry.get("Last Week")
            peak = entry.get("Peak Position", "?")
            weeks = entry.get("Weeks on Chart", "?")

            if previous in (None, 0, "0"):
                movement = "NEW / RE-ENTRY"
            elif str(previous) == str(rank):
                movement = "↔ unchanged"
            else:
                try:
                    change = int(previous) - int(rank)
                    movement = (
                        f"↑ {change} places" if change > 0
                        else f"↓ {abs(change)} places"
                    )
                except (TypeError, ValueError):
                    movement = "Movement unavailable"

            lines.append(
                f"• **#{rank}** — {title}\n"
                f"  {movement} · Peak #{peak} · "
                f"Weeks on chart: {weeks}"
            )

    except Exception as error:
        print(f"Chart error for {chart_name}: {error}")
        lines.append("Chart data temporarily unavailable.")

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
