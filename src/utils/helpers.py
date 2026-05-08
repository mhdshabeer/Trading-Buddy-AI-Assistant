# src/utils/helpers.py
import os
import json
import re
from datetime import datetime, timezone
import pytz

PROCESSED_TICKETS_FILE = "processed_tickets.json"

def load_processed_tickets() -> set:
    if os.path.exists(PROCESSED_TICKETS_FILE):
        try:
            with open(PROCESSED_TICKETS_FILE, "r") as f:
                data = json.load(f)
                return set(data)
        except:
            return set()
    return set()

def save_processed_tickets(tickets: set):
    with open(PROCESSED_TICKETS_FILE, "w") as f:
        json.dump(list(tickets), f)

def clean_extracted(data: dict) -> dict:
    optional_fields = ["htf_bias", "trade_logic", "confluences", "psychology_during", "psychology_after", "mistake", "learning"]
    for field in optional_fields:
        if field in data and data[field] == "":
            data[field] = None
    return data

def utc_to_ist(time_str: str) -> str:
    if not time_str or time_str == "Time TBA":
        return "Time TBA"
    try:
        if 'T' in time_str and ('+' in time_str or '-' in time_str[10:]):
            dt_utc = datetime.fromisoformat(time_str).astimezone(pytz.UTC)
        elif re.match(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', time_str):
            dt_utc = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=pytz.UTC)
        else:
            return "Time TBA"
        ist = pytz.timezone('Asia/Kolkata')
        return dt_utc.astimezone(ist).strftime("%I:%M %p").lstrip('0')
    except:
        return "Time TBA"