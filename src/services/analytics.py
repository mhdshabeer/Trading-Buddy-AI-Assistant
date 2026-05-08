# src/services/analytics.py
import os
import asyncpg
import json
from groq import Groq

# ---------- Database connection ----------
_pool = None

async def get_pool():
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            host=os.getenv("POSTGRES_HOST", "localhost"),
            port=int(os.getenv("POSTGRES_PORT", "5432")),
            database=os.getenv("POSTGRES_DB", "trading_buddy"),
            user=os.getenv("POSTGRES_USER", "postgres"),
            password=os.getenv("POSTGRES_PASSWORD", ""),
            min_size=1,
            max_size=5
        )
    return _pool

# ---------- Schema description for LLM ----------
TABLE_SCHEMA = """
Table name: trades
Columns:
- trade_date (DATE) – date the trade was closed
- asset (TEXT) – currency pair or instrument (e.g., EURUSD, BTCUSDm)
- lot_size (REAL) – volume traded
- entry_price (REAL)
- exit_price (REAL)
- direction (TEXT) – 'long' or 'short'
- profit_loss (REAL) – positive for profit, negative for loss
- htf_bias (TEXT) – 'bullish', 'bearish', or 'neutral'
- trade_logic (TEXT) – short sentence about why the trade was taken
- confluences (TEXT) – comma-separated (e.g., 'FVG, OB')
- psychology_during (TEXT)
- psychology_after (TEXT)
- mistake (TEXT)
- learning (TEXT)
- created_at (TIMESTAMP) – when the record was inserted
"""

SQL_GENERATION_PROMPT = """
You are a PostgreSQL query generator. Given a user's question about trading data, output ONLY a valid SQL SELECT query that answers it. Do not include any explanation or extra text.

Use the following table schema:
{TABLE_SCHEMA}

Rules:
- Only SELECT queries allowed (no INSERT, UPDATE, DELETE, DROP, etc.)
- Use standard PostgreSQL syntax.
- Return only the SQL query, nothing else.

Examples:
Question: "What's my total profit for April 2025?"
SQL: SELECT SUM(profit_loss) FROM trades WHERE trade_date BETWEEN '2025-04-01' AND '2025-04-30';

Question: "Show me win rate when psychology during was scared"
SQL: SELECT COUNT(CASE WHEN profit_loss > 0 THEN 1 END) * 100.0 / COUNT(*) AS win_rate FROM trades WHERE psychology_during = 'scared';

Question: "How many trades did I take last week?"
SQL: SELECT COUNT(*) FROM trades WHERE trade_date >= CURRENT_DATE - INTERVAL '7 days';

Now generate SQL for the following question. Return ONLY the SQL query.
Question: {question}
SQL:
"""

ANSWER_FORMAT_PROMPT = """
You are a trading assistant. Given a user's question and the raw result from a SQL query (as JSON), write a short, friendly answer (one sentence if possible). Use numbers directly from the result.

Question: {question}
SQL result: {result}

Answer:
"""

async def ask_question(question: str) -> str:
    """Process a natural language question and return an answer."""
    # 1. Generate SQL using Groq
    groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    completion = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": SQL_GENERATION_PROMPT.format(TABLE_SCHEMA=TABLE_SCHEMA, question=question)}],
        temperature=0.1,
    )
    sql = completion.choices[0].message.content.strip()
    # Remove any markdown formatting if present
    if sql.startswith("```sql"):
        sql = sql.split("```sql")[1].split("```")[0].strip()
    elif sql.startswith("```"):
        sql = sql.split("```")[1].split("```")[0].strip()
    
    # 2. Execute SQL
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            rows = await conn.fetch(sql)
        except Exception as e:
            return f"❌ SQL error: {e}\nGenerated SQL: {sql}"
    
    # Convert rows to list of dicts for JSON
    result_data = [dict(row) for row in rows]
    result_json = json.dumps(result_data, default=str)
    
    # 3. Format answer with LLM
    completion = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": ANSWER_FORMAT_PROMPT.format(question=question, result=result_json)}],
        temperature=0.3,
    )
    answer = completion.choices[0].message.content.strip()
    return answer