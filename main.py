import asyncio
import html
import logging
import mimetypes
import random
import sqlite3
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from telethon import TelegramClient, events

from config import (
    AI_SYSTEM_PROMPT,
    API_HASH,
    API_ID,
    IGNORE_USERS,
    GEMINI_API_KEY,
    GEMINI_MODEL,
    GEMINI_TRANSCRIPTION_MODEL,
    MEMORY_DB_PATH,
    MEMORY_TURNS,
    QUIET_HOURS,
    REPLY_DELAY_MAX,
    REPLY_DELAY_MIN,
    AWAY_MESSAGE,
    PHONE_NUMBER,
    SESSION_NAME,
)


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
ai = genai.Client(api_key=GEMINI_API_KEY)


def initialize_memory():
    with sqlite3.connect(MEMORY_DB_PATH) as database:
        database.execute(
            """
            CREATE TABLE IF NOT EXISTS conversation_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        database.execute(
            """
            CREATE INDEX IF NOT EXISTS conversation_messages_user_id
            ON conversation_messages (user_id, id)
            """
        )


def get_memory(user_id):
    with sqlite3.connect(MEMORY_DB_PATH) as database:
        rows = database.execute(
            """
            SELECT role, content
            FROM conversation_messages
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (user_id, MEMORY_TURNS * 2),
        ).fetchall()
    return list(reversed(rows))


def save_memory(user_id, role, content):
    with sqlite3.connect(MEMORY_DB_PATH) as database:
        database.execute(
            "INSERT INTO conversation_messages (user_id, role, content) VALUES (?, ?, ?)",
            (user_id, role, content),
        )
        database.execute(
            """
            DELETE FROM conversation_messages
            WHERE user_id = ?
              AND id NOT IN (
                  SELECT id
                  FROM conversation_messages
                  WHERE user_id = ?
                  ORDER BY id DESC
                  LIMIT ?
              )
            """,
            (user_id, user_id, MEMORY_TURNS * 2),
        )


def clear_memory(user_id):
    with sqlite3.connect(MEMORY_DB_PATH) as database:
        database.execute("DELETE FROM conversation_messages WHERE user_id = ?", (user_id,))


def quiet_hours_active():
    if not QUIET_HOURS:
        return False

    try:
        start_text, end_text = QUIET_HOURS.split("-", 1)
        current_time = datetime.now().time()
        start_time = datetime.strptime(start_text.strip(), "%H:%M").time()
        end_time = datetime.strptime(end_text.strip(), "%H:%M").time()
    except ValueError:
        logger.warning("Ignoring invalid QUIET_HOURS value: %s", QUIET_HOURS)
        return False

    if start_time <= end_time:
        return start_time <= current_time < end_time
    return current_time >= start_time or current_time < end_time


def format_message_with_memory(message_content, memory):
    if not memory:
        return message_content

    history = "\n".join(
        f"{role.title()}: {content}" for role, content in memory
    )
    return f"Conversation history:\n{history}\n\nCurrent message:\n{message_content}"


initialize_memory()


def transcribe_file(file_path):
    response = ai.models.generate_content(
        model=GEMINI_TRANSCRIPTION_MODEL,
        contents=[
            "Transcribe this audio exactly. Return only the transcription.",
            types.Part.from_bytes(
                data=file_path.read_bytes(),
                mime_type=mimetypes.guess_type(file_path.name)[0] or "audio/mpeg",
            ),
        ],
    )
    return response.text.strip()


def extract_video_audio(video_path, audio_path):
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-vn",
            "-acodec",
            "mp3",
            str(audio_path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )


def extract_video_frame(video_path, frame_path):
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-ss",
            "00:00:01",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            str(frame_path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )


def describe_video_frame(frame_path):
    response = ai.models.generate_content(
        model=GEMINI_MODEL,
        contents=[
            "Briefly describe the important visible content in this video frame.",
            types.Part.from_bytes(data=frame_path.read_bytes(), mime_type="image/jpeg"),
        ],
        config=types.GenerateContentConfig(max_output_tokens=150),
    )
    return response.text.strip()


def describe_image(image_path, question):
    response = ai.models.generate_content(
        model=GEMINI_MODEL,
        contents=[
            "Analyze this image to answer the user's question. "
            "Read visible text carefully when relevant, including names on identification documents. "
            f"User's question: {question or 'Briefly describe the important visible content.'}",
            types.Part.from_bytes(
                data=image_path.read_bytes(),
                mime_type=mimetypes.guess_type(image_path.name)[0] or "image/jpeg",
            ),
        ],
        config=types.GenerateContentConfig(max_output_tokens=300),
    )
    return response.text.strip()


async def understand_message(event, work_dir):
    message = event.message
    parts = []
    image_part = None
    if message.raw_text.strip():
        parts.append(f"Text/caption: {message.raw_text.strip()}")

    if not (message.photo or message.voice or message.audio or message.video):
        return "\n".join(parts) or "The sender sent an empty message.", image_part

    media_path = Path(await event.download_media(file=str(work_dir)))
    try:
        if message.photo:
            image_part = types.Part.from_bytes(
                data=media_path.read_bytes(),
                mime_type=mimetypes.guess_type(media_path.name)[0] or "image/jpeg",
            )
            parts.append("The user sent an image and wants an answer based on its contents.")
        elif message.video:
            frame_path = work_dir / "video_frame.jpg"
            await asyncio.to_thread(extract_video_frame, media_path, frame_path)
            frame_description = await asyncio.to_thread(describe_video_frame, frame_path)
            parts.append(f"Visible video content: {frame_description}")
            audio_path = work_dir / "video_audio.mp3"
            await asyncio.to_thread(extract_video_audio, media_path, audio_path)
            transcript = await asyncio.to_thread(transcribe_file, audio_path)
            parts.append(f"Transcribed video audio: {transcript}")
        else:
            transcript = await asyncio.to_thread(transcribe_file, media_path)
            parts.append(f"Transcribed audio: {transcript}")
    finally:
        for path in work_dir.iterdir():
            path.unlink(missing_ok=True)

    return "\n".join(parts), image_part


def generate_reply(message_content, memory, image_part=None):
    contents = [format_message_with_memory(message_content, memory)]
    if image_part is not None:
        contents.append(image_part)
    response = ai.models.generate_content(
        model=GEMINI_MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=AI_SYSTEM_PROMPT,
            temperature=0.5,
            max_output_tokens=600,
            thinking_config=types.ThinkingConfig(
                thinking_level=types.ThinkingLevel.MINIMAL,
            ),
        ),
    )
    return response.text.strip()


async def send_bot_reply(event, content):
    await event.reply(f"<b>Solomon's Bot:</b> {html.escape(content)}", parse_mode="html")


@client.on(events.NewMessage(outgoing=True, pattern=r"^/(clear|status)$"))
async def handle_control_command(event):
    if not event.is_private:
        return

    command = event.pattern_match.group(1)
    if command == "clear":
        await asyncio.to_thread(clear_memory, event.chat_id)
        await send_bot_reply(event, "Conversation memory cleared for this chat.")
        return

    memory_count = len(await asyncio.to_thread(get_memory, event.chat_id))
    quiet_status = "on" if quiet_hours_active() else "off"
    await send_bot_reply(
        event,
        f"Auto-reply is running. Memory messages: {memory_count}. Quiet hours: {quiet_status}.",
    )


@client.on(events.NewMessage(incoming=True))
async def handle_incoming_message(event):
    if not event.is_private or event.sender_id in IGNORE_USERS:
        return
    if quiet_hours_active():
        logger.info("Quiet hours active; skipped message from %s", event.sender_id)
        return

    try:
        async with client.action(event.chat_id, "typing"):
            with tempfile.TemporaryDirectory() as temporary_directory:
                message_content, image_part = await understand_message(
                    event,
                    Path(temporary_directory),
                )
                memory = await asyncio.to_thread(get_memory, event.sender_id)
                reply = await asyncio.to_thread(
                    generate_reply,
                    message_content,
                    memory,
                    image_part,
                )
            await asyncio.sleep(random.uniform(REPLY_DELAY_MIN, REPLY_DELAY_MAX))
        await asyncio.to_thread(save_memory, event.sender_id, "user", message_content)
        await asyncio.to_thread(save_memory, event.sender_id, "assistant", reply)
        await send_bot_reply(event, reply)
        logger.info("Sent AI reply to %s", event.sender_id)
    except genai_errors.APIError as error:
        if getattr(error, "code", None) == 429:
            logger.warning("AI service quota temporarily unavailable for %s", event.sender_id)
            await send_bot_reply(
                event,
                AWAY_MESSAGE,
            )
        else:
            logger.exception("Could not process message from %s: %s", event.sender_id, error)
            await send_bot_reply(event, AWAY_MESSAGE)
    except (OSError, subprocess.SubprocessError, ValueError, TypeError) as error:
        logger.exception("Could not process message from %s: %s", event.sender_id, error)
        await send_bot_reply(event, AWAY_MESSAGE)


async def main():
    await client.start(phone=PHONE_NUMBER)
    me = await client.get_me()
    logger.info("Automation is running for %s", getattr(me, "username", None) or me.id)
    await client.run_until_disconnected()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Automation stopped")