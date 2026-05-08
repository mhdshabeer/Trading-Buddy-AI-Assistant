# scripts/clear_trade_history.py
import asyncio
import os
import sys
from dotenv import load_dotenv
import asyncpg
import httpx

load_dotenv()

# ---------- PostgreSQL clearance ----------
async def clear_postgresql():
    print("Connecting to PostgreSQL...")
    conn = await asyncpg.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        database=os.getenv("POSTGRES_DB", "trading_buddy"),
        user=os.getenv("POSTGRES_USER", "postgres"),
        password=os.getenv("POSTGRES_PASSWORD", "")
    )
    print("Truncating trades table...")
    await conn.execute("TRUNCATE TABLE trades RESTART IDENTITY;")
    print("✅ PostgreSQL trades table cleared.")
    await conn.close()

# ---------- Notion clearance ----------
async def clear_notion():
    NOTION_API_KEY = os.getenv("NOTION_API_KEY")
    NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")
    if not NOTION_API_KEY or not NOTION_DATABASE_ID:
        print("⚠️ Notion credentials missing. Skipping Notion clearance.")
        return

    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }
    
    url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=headers, json={})
        data = response.json()
        if "results" not in data:
            print(f"❌ Failed to fetch Notion pages: {data}")
            return
        page_ids = [page["id"] for page in data["results"]]
        print(f"Found {len(page_ids)} pages in Notion database.")
        if not page_ids:
            print("No pages to archive.")
            return

        for pid in page_ids:
            delete_url = f"https://api.notion.com/v1/pages/{pid}"
            archive_payload = {"archived": True}
            resp = await client.patch(delete_url, headers=headers, json=archive_payload)
            if resp.status_code == 200:
                print(f"   Archived page {pid[:8]}...")
            else:
                print(f"   Failed to archive {pid[:8]}: {resp.text}")
    print("✅ Notion journal pages archived.")

# ---------- Confirmation ----------
async def confirm() -> bool:
    print("\n⚠️  WARNING: This will DELETE ALL TRADE DATA from PostgreSQL and ARCHIVE ALL Notion journal pages.")
    print("This action cannot be undone for PostgreSQL (Notion pages can be restored from trash for 30 days).")
    response = input("Type 'yes' to continue: ")
    return response.lower() == "yes"

# ---------- Main ----------
async def main():
    if not await confirm():
        print("Operation cancelled.")
        return
    print("Clearing trade history from PostgreSQL and Notion...")
    await clear_postgresql()
    await clear_notion()
    print("\n✅ All trade data cleared.")

if __name__ == "__main__":
    asyncio.run(main())