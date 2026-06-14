# src/mcp_servers/mt5_mcp.py
import asyncio
import json
import sys
from datetime import datetime, timedelta
import MetaTrader5 as mt5
from mcp.server import Server
from mcp.server.models import InitializationOptions
import mcp.server.stdio
import mcp.types as types

# ---------- Helper to initialize MT5 ----------
def init_mt5() -> bool:
    if not mt5.initialize():
        print(f"MT5 init failed: {mt5.last_error()}", file=sys.stderr)
        return False
    print("MT5 initialized", file=sys.stderr)
    return True

# ---------- Tool implementations ----------
async def get_account_balance() -> str:
    account = mt5.account_info()
    if account is None:
        return "Failed to fetch account info"
    return f"{account.balance} {account.currency}"

async def get_closed_trades(days_back: int = 30) -> str:
    """
    Returns JSON list of closed trades (deals) from the last N days.
    Each trade includes: ticket, symbol, action, volume, price, profit.
    """
    to_date = datetime.now()
    from_date = to_date - timedelta(days=days_back)
    deals = mt5.history_deals_get(from_date, to_date)
    if deals is None:
        return json.dumps([])
    result = []
    for deal in deals:
        # Only include actual buy/sell deals (skip deposits/withdrawals)
        if deal.type in [mt5.DEAL_TYPE_BUY, mt5.DEAL_TYPE_SELL]:
            entry_price = deal.price  # Default fallback
            position_id = deal.position_id
            
            # Query all deals tied to this exact position lifecycle
            position_deals = mt5.history_deals_get(position=position_id)
            if position_deals and len(position_deals) >= 2:
                # Sort them by time so the earliest deal is always the entry
                sorted_deals = sorted(position_deals, key=lambda d: d.time)
                entry_price = sorted_deals[0].price  # True entry price!
            result.append({
                "ticket": deal.ticket,
                "position_id": deal.position_id,
                "symbol": deal.symbol,
                "action": "buy" if deal.type == mt5.DEAL_TYPE_BUY else "sell",
                "volume": deal.volume,
                "price": deal.price,        # This is the execution price of THIS deal (Exit)
                "entry_price": entry_price,  # This is the TRUE calculated entry price
                "profit": deal.profit
            })
    return json.dumps(result, indent=2)

async def get_open_positions() -> str:
    """Returns JSON list of currently open positions with P&L."""
    positions = mt5.positions_get()
    if positions is None:
        return json.dumps([])
    result = []
    for pos in positions:
        result.append({
            "ticket": pos.ticket,
            "symbol": pos.symbol,
            "action": "buy" if pos.type == mt5.POSITION_TYPE_BUY else "sell",
            "volume": pos.volume,
            "open_price": pos.price_open,
            "current_price": pos.price_current,
            "profit": pos.profit
        })
    return json.dumps(result, indent=2)

# ---------- MCP Server ----------
app = Server("mt5-server")

@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="get_account_balance",
            description="Returns the current account balance with currency",
            inputSchema={"type": "object", "properties": {}, "required": []}
        ),
        types.Tool(
            name="get_closed_trades",
            description="Retrieve closed trades from the last N days (default 30). Returns a JSON list.",
            inputSchema={
                "type": "object",
                "properties": {
                    "days_back": {
                        "type": "integer",
                        "description": "Number of days to look back",
                        "default": 30
                    }
                },
                "required": []
            }
        ),
        types.Tool(
            name="get_open_positions",
            description="Get currently open positions with P&L. Returns a JSON list.",
            inputSchema={"type": "object", "properties": {}, "required": []}
        )
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "get_account_balance":
        result = await get_account_balance()
        return [types.TextContent(type="text", text=result)]
    elif name == "get_closed_trades":
        days_back = arguments.get("days_back", 30)
        result = await get_closed_trades(days_back)
        return [types.TextContent(type="text", text=result)]
    elif name == "get_open_positions":
        result = await get_open_positions()
        return [types.TextContent(type="text", text=result)]
    else:
        raise ValueError(f"Unknown tool: {name}")

async def main():
    if not init_mt5():
        return
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )

if __name__ == "__main__":
    asyncio.run(main())