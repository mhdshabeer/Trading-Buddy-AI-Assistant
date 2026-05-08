# src/mcp_servers/notion_mcp.py
import asyncio
import os
import sys
import httpx
from mcp.server import Server
from mcp.server.models import InitializationOptions
import mcp.server.stdio
import mcp.types as types
from dotenv import load_dotenv

load_dotenv()

NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")

if not NOTION_API_KEY or not NOTION_DATABASE_ID:
    print("Error: NOTION_API_KEY and NOTION_DATABASE_ID must be set in .env", file=sys.stderr)
    sys.exit(1)

def safe_text(value) -> str:
    """Convert None or non-string to empty string."""
    return value if isinstance(value, str) else ""

async def create_journal_page(trade_data: dict) -> str:
    direction = trade_data.get("direction", "").capitalize()
    
    properties = {
        "Trade ID": {"title": [{"text": {"content": safe_text(trade_data.get("trade_id", "N/A"))}}]},
        "Date": {"date": {"start": trade_data.get("trade_date")}},
        "Asset": {"select": {"name": safe_text(trade_data.get("asset", "Unknown"))}},
        "Direction": {"select": {"name": direction if direction else "Unknown"}},
        "Lot Size": {"number": trade_data.get("lot_size", 0)},
        "Entry Price": {"number": trade_data.get("entry_price", 0)},
        "Exit Price": {"number": trade_data.get("exit_price", 0)},
        "Profit/Loss": {"number": trade_data.get("profit_loss", 0)},
        "HTF Bias": {"select": {"name": safe_text(trade_data.get("htf_bias", "neutral"))}},
        "Trade Logic": {"rich_text": [{"text": {"content": safe_text(trade_data.get("trade_logic", ""))}}]},
        "Confluences": {"rich_text": [{"text": {"content": safe_text(trade_data.get("confluences", ""))}}]},
        "Psychology During": {"rich_text": [{"text": {"content": safe_text(trade_data.get("psychology_during", ""))}}]},
        "Psychology After": {"rich_text": [{"text": {"content": safe_text(trade_data.get("psychology_after", ""))}}]},
        "Mistake": {"rich_text": [{"text": {"content": safe_text(trade_data.get("mistake", ""))}}]},
        "Learning": {"rich_text": [{"text": {"content": safe_text(trade_data.get("learning", ""))}}]}
    }
    
    url = "https://api.notion.com/v1/pages"
    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }
    payload = {
        "parent": {"database_id": NOTION_DATABASE_ID},
        "properties": properties
    }
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            return "✅ Notion page created"
    except httpx.HTTPStatusError as e:
        error_body = e.response.text
        return f"❌ Notion API error (status {e.response.status_code}): {error_body}"
    except Exception as e:
        return f"❌ Notion error: {str(e)}"

app = Server("notion-server")

@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="create_journal_page",
            description="Create a readable journal page in Notion from trade data",
            inputSchema={
                "type": "object",
                "properties": {
                    "trade_data": {"type": "object", "description": "Complete trade entry dict"}
                },
                "required": ["trade_data"]
            }
        )
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "create_journal_page":
        result = await create_journal_page(arguments["trade_data"])
        return [types.TextContent(type="text", text=result)]
    raise ValueError(f"Unknown tool: {name}")

async def main():
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())