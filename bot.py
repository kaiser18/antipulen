import asyncio
import io
import ipaddress
import logging
import os
import re
import socket
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import aiohttp
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
MAX_LINKS = int(os.getenv("MAX_LINKS", "5"))
HTTP_TIMEOUT_SECONDS = float(os.getenv("HTTP_TIMEOUT_SECONDS", "10"))
MAX_REDIRECTS = 3
TESSERACT_CMD = os.getenv("TESSERACT_CMD")

if TESSERACT_CMD:
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD

BLOCKED_PHRASES = ("gamer igrica", "toddy", "todor", "gamer", "gejmer")
BLOCKED_PATTERNS = tuple(
    re.compile(re.escape(term).replace(r"\ ", r"\s+"))
    for term in BLOCKED_PHRASES
)
URL_PATTERN = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)


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


def linked_image_urls(text: str) -> list[str]:
    urls = []
    for url in URL_PATTERN.findall(text):
        url = url.rstrip(".,!?;:)]}")
        if url and url not in urls:
            urls.append(url)
    return urls[:MAX_LINKS]


def is_public_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
            return False
        if parsed.port not in {None, 80, 443} or not parsed.hostname:
            return False
    except ValueError:
        return False

    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return False
    return all(ipaddress.ip_address(address[4][0]).is_global for address in addresses)


async def download_linked_image(session: aiohttp.ClientSession, url: str) -> bytes | None:
    try:
        timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT_SECONDS)
        for _ in range(MAX_REDIRECTS + 1):
            if not await asyncio.to_thread(is_public_url, url):
                logger.warning("Skipped unsafe or invalid image URL: %s", url)
                return None

            async with session.get(url, timeout=timeout, allow_redirects=False) as response:
                if response.status in {301, 302, 303, 307, 308}:
                    location = response.headers.get("Location")
                    if not location:
                        return None
                    url = urljoin(url, location)
                    continue
                if response.status != 200:
                    logger.warning("Image URL returned HTTP %s: %s", response.status, url)
                    return None
                if response.content_length and response.content_length > MAX_IMAGE_BYTES:
                    logger.warning("Skipped oversized linked image: %s", url)
                    return None

                image_bytes = bytearray()
                async for chunk in response.content.iter_chunked(64 * 1024):
                    image_bytes.extend(chunk)
                    if len(image_bytes) > MAX_IMAGE_BYTES:
                        logger.warning("Skipped oversized linked image: %s", url)
                        return None
                return bytes(image_bytes)
        return None
    except (aiohttp.ClientError, asyncio.TimeoutError):
        logger.exception("Could not download image URL: %s", url)
        return None


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

        urls = linked_image_urls(message.content)
        if urls:
            async with aiohttp.ClientSession() as session:
                for url in urls:
                    image_bytes = await download_linked_image(session, url)
                    if image_bytes is None:
                        continue
                    try:
                        ocr_text = await asyncio.to_thread(extract_text, image_bytes)
                        blocked_terms = find_blocked_terms(ocr_text)
                    except Exception:
                        logger.exception("OCR failed for linked image %s", url)
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
