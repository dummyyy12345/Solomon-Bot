import os

from dotenv import load_dotenv


load_dotenv()


def required_setting(name):
	value = os.getenv(name)
	if not value:
		raise RuntimeError(
		f"Missing {name}. Copy .env.example to .env and fill in your Telegram settings."
	)
	return value


API_ID = int(required_setting("TELEGRAM_API_ID"))
API_HASH = required_setting("TELEGRAM_API_HASH")
PHONE_NUMBER = required_setting("TELEGRAM_PHONE_NUMBER")
OPENAI_API_KEY = required_setting("OPENAI_API_KEY")
SESSION_NAME = os.getenv("TELEGRAM_SESSION_NAME", "telegram_user")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_TRANSCRIPTION_MODEL = os.getenv("OPENAI_TRANSCRIPTION_MODEL", "whisper-1")
AI_SYSTEM_PROMPT = os.getenv(
	"AI_SYSTEM_PROMPT",
	"You are replying to my Telegram messages while I am unavailable. "
	"Write a helpful, natural reply based only on the message content. "
	"Do not claim to be me, make commitments, or invent facts. "
	"If the message is unclear, ask one concise clarifying question.",
)
IGNORE_USERS = {
	int(user_id.strip())
	for user_id in os.getenv("TELEGRAM_IGNORE_USERS", "").split(",")
	if user_id.strip()
}