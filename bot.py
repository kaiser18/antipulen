import asyncio
import io
import logging
import os
import re
from pathlib import Path

import discord
import pytesseract
from dotenv import load_dotenv
from PIL import Image, ImageOps

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("image-moderator")

TOKEN = os.getenv("DISCORD_TOKEN")
REPLY_TEXT = os.getenv(
    "MODERATION_REPLY",
    "Please stop sending images containing those words.",
)
MAX_IMAGE_BYTES = int(os.getenv("MAX_IMAGE_BYTES", str(10 * 1024 * 1024)))
TESSERACT_CMD = os.getenv("TESSERACT_CMD")

if TESSERACT_CMD:
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD

BLOCKED_PHRASES = ("gamer igrica", "toddy", "todor", "gamer", "gejmer")
BLOCKED_PATTERNS = tuple(
    re.compile(rf"\b{re.escape(term).replace(r'\ ', r'\s+')}\b")
    for term in BLOCKED_PHRASES
)


def is_image_attachment(attachment: discord.Attachment) -> bool:
    if attachment.content_type and attachment.content_type.startswith("image/"):
        return True
    return Path(attachment.filename).suffix.lower() in {
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
        ".bmp",
        ".gif",
        ".tif",
        ".tiff",
    }


def normalize_text(text: str) -> str:
    text = text.casefold()
    text = re.sub(r"[^\w]+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def find_blocked_terms(text: str) -> list[str]:
    normalized = normalize_text(text)
    return [term for term, pattern in zip(BLOCKED_PHRASES, BLOCKED_PATTERNS) if pattern.search(normalized)]


def extract_text(image_bytes: bytes) -> str:
    with Image.open(io.BytesIO(image_bytes)) as image:
        image = ImageOps.exif_transpose(image).convert("L")
        image = ImageOps.autocontrast(image)
        image = image.resize((image.width * 2, image.height * 2))
        return pytesseract.image_to_string(image, config="--psm 6")


class ImageModerator(discord.Client):
    async def on_ready(self) -> None:
        logger.info("Logged in as %s (%s)", self.user, self.user.id if self.user else "unknown")

    async def on_message(self, message: discord.Message) -> None:
        if message.author == self.user:
            return

        blocked_terms = find_blocked_terms(message.content)
        if blocked_terms:
            logger.info(
                "Removing message %s from %s; detected: %s",
                message.id,
                message.author,
                ", ".join(blocked_terms),
            )
            try:
                await message.reply(REPLY_TEXT, mention_author=False)
            except discord.HTTPException:
                logger.exception("Could not send moderation reply for message %s", message.id)
            try:
                await message.delete()
            except discord.HTTPException:
                logger.exception("Could not delete message %s", message.id)
            return

        for attachment in message.attachments:
            if not is_image_attachment(attachment):
                continue
            if attachment.size > MAX_IMAGE_BYTES:
                logger.warning("Skipped oversized image %s from %s", attachment.filename, message.author)
                continue

            try:
                image_bytes = await attachment.read()
                ocr_text = await asyncio.to_thread(extract_text, image_bytes)
                blocked_terms = find_blocked_terms(ocr_text)
            except Exception:
                logger.exception("OCR failed for %s", attachment.filename)
                continue

            if not blocked_terms:
                continue

            logger.info(
                "Removing message %s from %s; detected: %s",
                message.id,
                message.author,
                ", ".join(blocked_terms),
            )
            try:
                await message.reply(REPLY_TEXT, mention_author=False)
            except discord.HTTPException:
                logger.exception("Could not send moderation reply for message %s", message.id)
            try:
                await message.delete()
            except discord.HTTPException:
                logger.exception("Could not delete message %s", message.id)
            return


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("DISCORD_TOKEN is missing. Copy .env.example to .env and add your bot token.")

    intents = discord.Intents.default()
    intents.message_content = True
    client = ImageModerator(intents=intents)
    client.run(TOKEN)
