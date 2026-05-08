# src/services/psychology.py
import json
import os
from groq import Groq

async def extract_trade_psychology(text: str) -> dict:
    prompt = f"""You are a trading journal assistant. Extract ONLY the following fields from the user's text. Return ONLY valid JSON, no extra text.

Fields:
- htf_bias (string, "bullish", "bearish", or "neutral", if not mentioned use null)
- trade_logic (string, short sentence explaining why you took the trade)
- confluences (string, e.g., "Fair Value Gap , OrderBlock , Strong candle close , double top")
- psychology_during (string, how you felt while trade was open)
- psychology_after (string, how you felt after closing)
- mistake (string, e.g., "early/rushed entry", "held too long", "greedy", "early sell")
- learning (string, what to improve next time)

User text: {text}

JSON:
"""
    groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    completion = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        response_format={"type": "json_object"}
    )
    content = completion.choices[0].message.content
    try:
        return json.loads(content)
    except Exception as e:
        return {"error": "Failed to parse LLM output", "raw": content, "exception": str(e)}