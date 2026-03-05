"""Chatbot-specific upload helpers."""

from pathlib import Path

CHATBOT_UPLOAD_DIR = Path(__file__).resolve().parent / 'static' / 'chatbot_uploads'
CHATBOT_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
