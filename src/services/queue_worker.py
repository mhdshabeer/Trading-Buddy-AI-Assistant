# src/services/queue_worker.py
import asyncio

async def queue_worker(send_tool, insert_tool, notion_tool, state):
    while True:
        if not state["trade_queue"]:
            await asyncio.sleep(1)
            continue
        async with state["processing_lock"]:
            if state["current_trade"] is not None:
                await asyncio.sleep(1)
                continue
            state["current_trade"] = state["trade_queue"].popleft()
        profit = state["current_trade"].get("profit_loss", 0.0)
        symbol = state["current_trade"].get("asset", "UNKNOWN")
        profit_str = f"+${profit:.2f}" if profit >= 0 else f"-${abs(profit):.2f}"
        await send_tool.ainvoke({"text": f"📊 *Trade closed:* {symbol} {profit_str}\nPlease explain your HTF bias, trade logic, confluences, psychology, mistake, and learning.\nType /skip to skip this trade."})
        state["awaiting_psychology"] = True
        while state["awaiting_psychology"]:
            await asyncio.sleep(1)