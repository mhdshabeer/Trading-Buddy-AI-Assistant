# src/services/mt5_poller.py
import asyncio
import json
from datetime import datetime
from src.utils.helpers import save_processed_tickets

async def mt5_polling_task(mt5_tools, send_tool, state):
    get_trades_tool = next((t for t in mt5_tools if t.name == "get_closed_trades"), None)
    if not get_trades_tool:
        print("❌ MT5 polling: get_closed_trades tool not found")
        return
    print("MT5 polling started (every 5 seconds)...")
    while True:
        try:
            result = await get_trades_tool.ainvoke({"days_back": 1})
            content = result.content if hasattr(result, 'content') else result
            trades = []
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and "text" in item:
                        try:
                            parsed = json.loads(item["text"])
                            if isinstance(parsed, list):
                                trades.extend(parsed)
                        except:
                            pass
            elif isinstance(content, str):
                try:
                    parsed = json.loads(content)
                    if isinstance(parsed, list):
                        trades = parsed
                except:
                    pass
            for trade in trades:
                profit = trade.get("profit", 0.0)
                if profit == 0.0:
                    continue
                ticket = trade.get("ticket")
                pos_id = trade.get("position_id", ticket)
                if pos_id and pos_id not in state["last_processed_tickets"]:
                    state["last_processed_tickets"].add(pos_id)
                    save_processed_tickets(state["last_processed_tickets"])
                    symbol = trade.get("symbol", "UNKNOWN")
                    action = trade.get("action", "buy")
                    direction = "long" if action == "buy" else "short"
                    volume = trade.get("volume", 0.0)
                    exit_price = trade.get("price", 0.0)
                    trade_date = datetime.now().strftime("%Y-%m-%d")
                    pending = {
                        "trade_date": trade_date,
                        "asset": symbol,
                        "lot_size": volume,
                        "entry_price": exit_price,
                        "exit_price": exit_price,
                        "direction": direction,
                        "profit_loss": profit,
                        "ticket": ticket
                    }
                    state["trade_queue"].append(pending)
                    print(f"   → Trade {pos_id} (profit: {profit}) added to queue (size: {len(state['trade_queue'])})")
        except Exception as e:
            print(f"⚠️ MT5 polling error: {e}")
        await asyncio.sleep(5)