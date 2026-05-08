# src/services/voice.py
import os
import httpx
from faster_whisper import WhisperModel

WHISPER_MODEL_SIZE = "base"
model = WhisperModel(WHISPER_MODEL_SIZE, device="cpu", compute_type="int8")

async def download_voice_file(bot_token: str, file_id: str) -> bytes:
    async with httpx.AsyncClient() as client:
        get_file = await client.get(
            f"https://api.telegram.org/bot{bot_token}/getFile",
            params={"file_id": file_id}
        )
        file_data = get_file.json()
        if not file_data.get("ok"):
            raise Exception(f"Failed to get file: {file_data}")
        file_path = file_data["result"]["file_path"]
        download_url = f"https://api.telegram.org/file/bot{bot_token}/{file_path}"
        resp = await client.get(download_url)
        return resp.content

async def transcribe_voice(bot_token: str, file_id: str) -> str:
    ogg_bytes = await download_voice_file(bot_token, file_id)
    temp_path = f"temp_voice_{file_id}.ogg"
    try:
        with open(temp_path, "wb") as f:
            f.write(ogg_bytes)
        segments, _ = model.transcribe(temp_path, language="en", beam_size=3)
        text = " ".join(segment.text for segment in segments)
        return text if text.strip() else "(no speech detected)"
    except Exception as e:
        return f"Transcription error: {e}"
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)