# Discord OCR Image Moderator

This bot uses Tesseract OCR to inspect image attachments. If an image contains `gamer igrica`, `toddy`, `todor`, `gamer`, or `gejmer`, it replies with a warning and deletes the original message.

## Setup on Windows

1. Install Python 3.11 or newer.
2. Install Tesseract OCR, for example from [UB Mannheim](https://github.com/UB-Mannheim/tesseract/wiki).
3. Create a Discord application and bot in the [Discord Developer Portal](https://discord.com/developers/applications).
4. Enable **Message Content Intent** under the bot's Privileged Gateway Intents.
5. Invite the bot with these server permissions: **View Channel**, **Read Message History**, **Send Messages**, and **Manage Messages**.
6. In this folder, create and activate a virtual environment:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

7. Copy `.env.example` to `.env` and set `DISCORD_TOKEN`. If Tesseract is not on `PATH`, set `TESSERACT_CMD` to its executable path, commonly `C:\Program Files\Tesseract-OCR\tesseract.exe`.
8. Start the bot:

   ```powershell
   python bot.py
   ```

The bot only processes image attachments and skips images larger than `MAX_IMAGE_BYTES` (10 MiB by default). OCR failures are logged and do not delete the message.
