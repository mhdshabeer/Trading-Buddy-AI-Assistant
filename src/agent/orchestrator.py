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

# ---------- Text message processor (handles commands, psychology, analytics) ----------
async def process_text_message(text: str, send_tool, insert_tool, notion_tool):
    """Handle a text message (or transcribed voice) that is not a skip command."""
    lower_text = text.strip().lower()
    # Ignore empty
    if not lower_text:
        return
    
    # Commands: digest, news
    if lower_text in ["digest", "/digest", "news", "/news"]:
        print("   → Generating digest...")
        digest = await generate_digest()
        await send_tool.ainvoke({"text": digest})
        print("   → Digest sent.")
        return
    
    # If awaiting psychology and there's a current trade, treat as psychology entry
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
        
        db_status_msg = ""
        if not db_success:
            db_status_msg = f"\n⚠️ Postgres Details: {db_text}" # Capture raw SQL error
            
        notion_success = False
        notion_status_msg = ""
        if notion_tool:
            notion_result = await notion_tool.ainvoke({"trade_data": complete_entry})
            notion_text = extract_text_from_mcp_response(notion_result)
            notion_success = "✅ Notion page created" in notion_text
            if not notion_success:
                notion_status_msg = f"\n⚠️ Notion Details: {notion_text}"
        
        # Combine everything into the final message
        clean_msg = (
            f"✅ Journal saved for {complete_entry.get('asset')}.\n"
            f"PostgreSQL: {'✅' if db_success else '❌'}{db_status_msg}\n"
            f"Notion: {'✅' if notion_success else '❌'}{notion_status_msg}"
        )
        await send_tool.ainvoke({"text": clean_msg})
        state["awaiting_psychology"] = False
        state["current_trade"] = None
        return
    
    # Otherwise treat as analytics query
    print(f"   → Treating as analytics query: {text}")
    answer = await ask_question(text)
    await send_tool.ainvoke({"text": answer})

# ---------- Main orchestrator ----------
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
    print("Voice commands (say 'news' or ask a question) are also supported.\n")

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
                # /skip handled here because it's simple
                if text in ["skip", "/skip"]:
                    if state["awaiting_psychology"] and state["current_trade"] is not None:
                        print("   → Skipped current trade")
                        await send_tool.ainvoke({"text": f"⏭️ Skipped {state['current_trade'].get('asset', 'trade')}."})
                        state["awaiting_psychology"] = False
                        state["current_trade"] = None
                    else:
                        await send_tool.ainvoke({"text": "ℹ️ No pending trade to skip."})
                    continue
                # All other text messages go to the processor
                await process_text_message(text, send_tool, insert_tool, notion_tool)

            elif msg_type == "voice":
                file_id = upd.get("file_id")
                print("   → Voice message detected, transcribing...")
                transcript = await transcribe_voice(bot_token, file_id)
                print(f"   → Transcription: {transcript}")
                # Treat the transcript as text input, but we must handle /skip? Unlikely, but we can call the same processor.
                # However, skip is not a voice command; we'll just process as normal text.
                lower_transcript = transcript.strip().lower()
                if lower_transcript in ["skip", "/skip"]:
                    # If someone says "skip" voice, handle it
                    if state["awaiting_psychology"] and state["current_trade"] is not None:
                        print("   → Skipped current trade (via voice)")
                        await send_tool.ainvoke({"text": f"⏭️ Skipped {state['current_trade'].get('asset', 'trade')}."})
                        state["awaiting_psychology"] = False
                        state["current_trade"] = None
                    else:
                        await send_tool.ainvoke({"text": "ℹ️ No pending trade to skip."})
                else:
                    await process_text_message(transcript, send_tool, insert_tool, notion_tool)
            else:
                print(f"   → Unhandled type: {msg_type}")

        await asyncio.sleep(2)

    await asyncio.gather(mt5_task, queue_task)

if __name__ == "__main__":
    asyncio.run(run())