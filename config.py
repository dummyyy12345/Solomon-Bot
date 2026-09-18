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
GEMINI_API_KEY = required_setting("GEMINI_API_KEY")
SESSION_NAME = os.getenv("TELEGRAM_SESSION_NAME", "telegram_user")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
GEMINI_TRANSCRIPTION_MODEL = os.getenv("GEMINI_TRANSCRIPTION_MODEL", GEMINI_MODEL)
MEMORY_DB_PATH = os.getenv("MEMORY_DB_PATH", "telegram_memory.db")
MEMORY_TURNS = int(os.getenv("MEMORY_TURNS", "8"))
QUIET_HOURS = os.getenv("QUIET_HOURS", "")
REPLY_DELAY_MIN = float(os.getenv("REPLY_DELAY_MIN", "0.8"))
REPLY_DELAY_MAX = float(os.getenv("REPLY_DELAY_MAX", "2.2"))
AWAY_MESSAGE = os.getenv(
	"AWAY_MESSAGE",
	"I am away right now, but I have received your message and will get back to you when I can.",
)
AI_SYSTEM_PROMPT = os.getenv(
	"AI_SYSTEM_PROMPT",
	"You are replying to my Telegram messages while I am unavailable. "
	"Write like a real person sending a quick, thoughtful Telegram message. "
	"Keep the tone warm, casual, and natural, using contractions where appropriate. "
	"Respond directly to what the person said in 2 to 4 concise sentences. "
	"Do not sound like an AI assistant, customer support agent, or formal announcement. "
	"Do not use generic openings like 'It sounds like' unless they genuinely fit. "
	"Do not claim to be me, make commitments, or invent facts. "
	"If the message is unclear, ask one natural clarifying question.",
)
IGNORE_USERS = {
	int(user_id.strip())
	for user_id in os.getenv("TELEGRAM_IGNORE_USERS", "").split(",")
	if user_id.strip()
}