import asyncio
import base64
import logging
import mimetypes
import subprocess
import tempfile
from pathlib import Path

from openai import OpenAI, OpenAIError
from telethon import TelegramClient, events

from config import (
    AI_SYSTEM_PROMPT,
    API_HASH,
    API_ID,
    IGNORE_USERS,
    OPENAI_API_KEY,
    OPENAI_MODEL,
    OPENAI_TRANSCRIPTION_MODEL,
    PHONE_NUMBER,
    SESSION_NAME,
)


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
ai = OpenAI(api_key=OPENAI_API_KEY)


def transcribe_file(file_path):
    with file_path.open("rb") as media_file:
        transcription = ai.audio.transcriptions.create(
            model=OPENAI_TRANSCRIPTION_MODEL,
            file=media_file,
        )
    return transcription.text.strip()


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
    image_data = base64.b64encode(frame_path.read_bytes()).decode("ascii")
    response = ai.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Briefly describe the important visible content in this video frame."},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{image_data}"},
                    },
                ],
            }
        ],
        max_tokens=150,
    )
    return response.choices[0].message.content.strip()


async def understand_message(event, work_dir):
    message = event.message
    parts = []
    if message.raw_text.strip():
        parts.append(f"Text/caption: {message.raw_text.strip()}")

    if not (message.voice or message.audio or message.video):
        return "\n".join(parts) or "The sender sent an empty message."

    media_path = Path(await event.download_media(file=str(work_dir)))
    try:
        if message.video:
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

    return "\n".join(parts)


def generate_reply(message_content):
    response = ai.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": AI_SYSTEM_PROMPT},
            {"role": "user", "content": message_content},
        ],
        temperature=0.5,
        max_tokens=250,
    )
    return response.choices[0].message.content.strip()


@client.on(events.NewMessage(incoming=True))
async def handle_incoming_message(event):
    if not event.is_private or event.sender_id in IGNORE_USERS:
        return

    try:
        with tempfile.TemporaryDirectory() as temporary_directory:
            message_content = await understand_message(event, Path(temporary_directory))
            reply = await asyncio.to_thread(generate_reply, message_content)
        await event.reply(reply)
        logger.info("Sent AI reply to %s", event.sender_id)
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, OpenAIError) as error:
        logger.exception("Could not process message from %s: %s", event.sender_id, error)
        await event.reply("I received your message, but I could not process it automatically. I will reply when I can.")


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