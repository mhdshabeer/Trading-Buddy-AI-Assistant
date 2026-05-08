# src/agent/orchestrator.py
import asyncio
import json
import os
import sys
import uuid
from collections import deque
from dotenv import load_dotenv
from langchain_mcp_adapters.client import MultiServerMCPClient
from src.services.digest import generate_digest
from src.services.voice import transcribe_voice
from src.services.psychology import extract_trade_psychology
from src.services.mt5_poller import mt5_polling_task
from src.services.queue_worker import queue_worker
from src.utils.helpers import load_processed_tickets, clean_extracted
from src.services.analytics import ask_question

load_dotenv()

# ---------- Helper to extract text from MCP response ----------
def extract_text_from_mcp_response(response) -> str:
    """Extract the text string from an MCP tool response (ToolMessage or list of TextContent)."""
    if hasattr(response, 'content'):
        return response.content
    elif isinstance(response, list) and len(response) > 0:
        first = response[0]
        if hasattr(first, 'text'):
            return first.text
        elif isinstance(first, dict) and 'text' in first:
            return first['text']
    return str(response)

# ---------- Shared state ----------
state = {
    "trade_queue": deque(),
    "current_trade": None,
    "awaiting_psychology": False,
    "processing_lock": asyncio.Lock(),
    "last_processed_tickets": load_processed_tickets()
}

async def run():
    client = MultiServerMCPClient({
        "telegram": {
            "command": sys.executable,
            "args": ["src/mcp_servers/telegram_mcp.py"],
            "transport": "stdio"
        },
        "postgresql": {
            "command": sys.executable,
            "args": ["src/mcp_servers/postgresql_mcp.py"],
            "transport": "stdio"
        },
        "mt5": {
            "command": sys.executable,
            "args": ["src/mcp_servers/mt5_mcp.py"],
            "transport": "stdio"
        },
        "notion": {
            "command": sys.executable,
            "args": ["src/mcp_servers/notion_mcp.py"],
            "transport": "stdio"
        }
    })

    tools = await client.get_tools()
    poll_tool = next((t for t in tools if t.name == "poll_updates"), None)
    send_tool = next((t for t in tools if t.name == "send_message"), None)
    insert_tool = next((t for t in tools if t.name == "insert_trade"), None)
    notion_tool = next((t for t in tools if t.name == "create_journal_page"), None)

    if not poll_tool or not send_tool or not insert_tool:
        print("❌ Required tools not found")
        return

    mt5_tools = [t for t in tools if t.name == "get_closed_trades"]
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    allowed_commands = {"digest", "/digest", "news", "/news", "skip", "/skip"}

    print("Listening for messages... Commands: /digest, /news, /skip")
    print("MT5 polling active...\n")

    mt5_task = asyncio.create_task(mt5_polling_task(mt5_tools, send_tool, state))
    queue_task = asyncio.create_task(queue_worker(send_tool, insert_tool, notion_tool, state))

    while True:
        result = await poll_tool.ainvoke({})
        content = result.content if hasattr(result, 'content') else result

        updates_raw = []
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and "text" in item:
                    try:
                        parsed = json.loads(item["text"])
                        if isinstance(parsed, list):
                            updates_raw.extend(parsed)
                    except:
                        pass
        elif isinstance(content, str):
            try:
                parsed = json.loads(content)
                if isinstance(parsed, list):
                    updates_raw = parsed
            except:
                pass

        for upd in updates_raw:
            msg_type = upd.get("type")
            print(f"📩 Received: {upd}")

            if msg_type == "text":
                text = upd.get("text", "").strip().lower()
                # Handle /skip or skip
                if text in ["skip", "/skip"]:
                    if state["awaiting_psychology"] and state["current_trade"] is not None:
                        print("   → Skipped current trade")
                        await send_tool.ainvoke({"text": f"⏭️ Skipped {state['current_trade'].get('asset', 'trade')}."})
                        state["awaiting_psychology"] = False
                        state["current_trade"] = None
                    else:
                        await send_tool.ainvoke({"text": "ℹ️ No pending trade to skip."})
                    continue
                # Handle digest / news commands
                if text in allowed_commands:
                    print("   → Generating digest...")
                    digest = await generate_digest()
                    await send_tool.ainvoke({"text": digest})
                    print("   → Digest sent.")
                    continue
                # Handle psychology response if waiting
                if state["awaiting_psychology"] and state["current_trade"] is not None:
                    print("   → Processing as psychology entry (text)...")
                    extracted = await extract_trade_psychology(text)
                    extracted = clean_extracted(extracted)
                    complete_entry = {**state["current_trade"], **extracted}
                    complete_entry["trade_id"] = f"{complete_entry['trade_date']}_{complete_entry['asset']}_{uuid.uuid4().hex[:6]}"
                    print(f"   → Complete entry: {json.dumps(complete_entry, indent=2)}")
                    db_result = await insert_tool.ainvoke({"trade_data": complete_entry})
                    db_text = extract_text_from_mcp_response(db_result)
                    db_success = "✅ Trade inserted successfully" in db_text
                    notion_success = False
                    if notion_tool:
                        notion_result = await notion_tool.ainvoke({"trade_data": complete_entry})
                        notion_text = extract_text_from_mcp_response(notion_result)
                        notion_success = "✅ Notion page created" in notion_text
                    clean_msg = f"✅ Journal saved for {complete_entry.get('asset')}.\nPostgreSQL: {'✅' if db_success else '❌'}\nNotion: {'✅' if notion_success else '❌'}"
                    await send_tool.ainvoke({"text": clean_msg})
                    state["awaiting_psychology"] = False
                    state["current_trade"] = None
                    continue
                # Otherwise treat as analytics query
                print(f"   → Treating as analytics query: {text}")
                answer = await ask_question(text)
                await send_tool.ainvoke({"text": answer})
                # No extra invalid input print

            elif msg_type == "voice":
                file_id = upd.get("file_id")
                print("   → Voice message detected, transcribing...")
                transcript = await transcribe_voice(bot_token, file_id)
                print(f"   → Transcription: {transcript}")
                if state["awaiting_psychology"] and state["current_trade"] is not None:
                    print("   → Processing as psychology entry (voice)...")
                    extracted = await extract_trade_psychology(transcript)
                    extracted = clean_extracted(extracted)
                    complete_entry = {**state["current_trade"], **extracted}
                    complete_entry["trade_id"] = f"{complete_entry['trade_date']}_{complete_entry['asset']}_{uuid.uuid4().hex[:6]}"
                    db_result = await insert_tool.ainvoke({"trade_data": complete_entry})
                    db_text = extract_text_from_mcp_response(db_result)
                    db_success = "✅ Trade inserted successfully" in db_text
                    notion_success = False
                    if notion_tool:
                        notion_result = await notion_tool.ainvoke({"trade_data": complete_entry})
                        notion_text = extract_text_from_mcp_response(notion_result)
                        notion_success = "✅ Notion page created" in notion_text
                    clean_msg = f"✅ Journal saved for {complete_entry.get('asset')}.\nPostgreSQL: {'✅' if db_success else '❌'}\nNotion: {'✅' if notion_success else '❌'}"
                    await send_tool.ainvoke({"text": clean_msg})
                    state["awaiting_psychology"] = False
                    state["current_trade"] = None
                else:
                    await send_tool.ainvoke({"text": f"📝 Transcription:\n{transcript}"})
            else:
                print(f"   → Unhandled type: {msg_type}")

        await asyncio.sleep(2)

    await asyncio.gather(mt5_task, queue_task)

if __name__ == "__main__":
    asyncio.run(run())