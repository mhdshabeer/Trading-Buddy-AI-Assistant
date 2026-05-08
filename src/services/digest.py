# src/services/digest.py
import os
from datetime import datetime
import httpx
from groq import Groq
from src.utils.helpers import utc_to_ist

async def generate_digest() -> str:
    today_date = datetime.now().strftime("%A, %B %d, %Y")
    today_str = datetime.now().strftime("%Y-%m-%d")

    eco_url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
    high_impact_events = []
    all_events_summary = []
    news_items = []

    async with httpx.AsyncClient(timeout=10) as client:
        # 1. Economic calendar
        resp = await client.get(eco_url)
        data = resp.json()
        today_events = [e for e in data if e.get('date', '')[:10] == today_str]
        for event in today_events:
            country = event.get('country', '')
            title = event.get('title', '')
            impact = event.get('impact', '')
            full_datetime = event.get('date', '')
            time_ist = utc_to_ist(full_datetime)
            if impact == 'High':
                high_impact_events.append(f"{country} - {title} - {time_ist}")
            all_events_summary.append(f"{country} {title} ({impact} impact)")

        # 2. Market news (Finnhub)
        finnhub_key = os.getenv("FINNHUB_API_KEY")
        if finnhub_key:
            news_url = f"https://finnhub.io/api/v1/news?category=forex&token={finnhub_key}"
            resp = await client.get(news_url)
            articles = resp.json()
            for art in articles[:3]:
                news_items.append(f"- {art['headline']}")
        else:
            news_items = ["No Finnhub API key found."]

    # Build prompt and call Groq (outside the client block)
    eco_summary = "\n".join(all_events_summary) if all_events_summary else "No economic events today."
    news_text = "\n".join(news_items) if news_items else "No news available."

    prompt = f"""You are a trading assistant. Based ONLY on the following market news (ignore economic calendar events, as they are already listed separately), write ONE short paragraph (max 100 words) focusing on:

- Major geopolitical events (e.g., conflicts, ceasefire talks, diplomatic tensions)
- Central bank communications (e.g., Fed, ECB, BOJ speeches, rate cut hints)
- Macroeconomic shifts affecting forex, crypto, gold, and commodities (NOT individual stocks)
- Any broad market sentiment drivers

DO NOT mention economic data releases (like PMI, NFP, CPI, Retail Sales) – they are already shown in the red‑folder list above.
DO NOT mention individual company news or stock‑specific updates.

Market news:
{news_text}

Write a concise, actionable paragraph. End with a one‑sentence trading recommendation.
"""

    groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    completion = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )
    paragraph = completion.choices[0].message.content

    if high_impact_events:
        events_list = "\n".join(f"🔴 {line}" for line in high_impact_events)
        red_section = f"**Red‑folder news today (IST):**\n{events_list}"
    else:
        red_section = "No high‑impact economic events today."

    return f"📅 {today_date}\n\n{red_section}\n\n{paragraph}"