# src/main.py
import asyncio
from src.agent.orchestrator import run

if __name__ == "__main__":
    asyncio.run(run())