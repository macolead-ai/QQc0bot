import os
import io
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import qrcode
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("bot")

# ============================================================
# Health server (Render/Railway need an open port)
# ============================================================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"QR Bot alive.")
    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
    def log_message(self, format, *args):
        return

def run_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    log.info(f"Health server on port {port}")
    server.serve_forever()

# ============================================================
# Modes — what the user is currently entering
# ============================================================
MODES = {
    "url":   "🔗 Send me the URL (e.g. https://example.com)",
    "text":  "📝 Send me the text to encode",
    "phone": "📞 Send me the phone number (e.g. +1234567890)",
    "email": "📧 Send me the email address",
    "wifi":  "📶 Send me your WiFi info in this format:\n\n`SSID | PASSWORD`\n\nExample: `MyWiFi | MySecretPass123`",
    "vcard": "💳 Send me contact info in this format:\n\n`Name | Phone | Email`\n\nExample: `John Doe | +1234567890 | john@example.com`",
}

def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 URL / Website", callback_data="mode_url"),
         InlineKeyboardButton("📝 Plain Text", callback_data="mode_text")],
        [InlineKeyboardButton("📞 Phone Number", callback_data="mode_phone"),
         InlineKeyboardButton("📧 Email", callback_data="mode_email")],
        [InlineKeyboardButton("📶 WiFi Password", callback_data="mode_wifi"),
         InlineKeyboardButton("💳 Contact (vCard)", callback_data="mode_vcard")],
    ])

def back_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="home")]])

# ============================================================
# Build QR data string from raw input
# ============================================================
def build_qr_data(mode: str, raw: str) -> str:
    raw = raw.strip()
    if mode == "url":
        if not raw.startswith(("http://", "https://")):
            raw = "https://" + raw
        return raw
    if mode == "text":
        return raw
    if mode == "phone":
        return f"tel:{raw}"
    if mode == "email":
        return f"mailto:{raw}"
    if mode == "wifi":
        parts = [p.strip() for p in raw.split("|", 1)]
        if len(parts) != 2:
            raise ValueError("Format: `SSID | PASSWORD`")
        ssid, password = parts
        return f"WIFI:T:WPA;S:{ssid};P:{password};;"
    if mode == "vcard":
        parts = [p.strip() for p in raw.split("|")]
        if len(parts) < 3:
            raise ValueError("Format: `Name | Phone | Email`")
        name, phone, email = parts[0], parts[1], parts[2]
        return (
            "BEGIN:VCARD\nVERSION:3.0\n"
            f"FN:{name}\n"
            f"TEL:{phone}\n"
            f"EMAIL:{email}\n"
            "END:VCARD"
        )
    return raw

# ============================================================
# Generate QR code as PNG bytes
# ============================================================
def make_qr(data: str) -> bytes:
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=12,
        border=4,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()

# ============================================================
# Handlers
# ============================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("mode", None)
    await update.message.reply_text(
        "👋 *QR Code Generator*\n\nPick what kind of QR code to make:",
        reply_markup=main_menu(),
        parse_mode="Markdown",
    )

async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "home":
        context.user_data.pop("mode", None)
        await query.edit_message_text(
            "👋 *QR Code Generator*\n\nPick what kind of QR code to make:",
            reply_markup=main_menu(),
            parse_mode="Markdown",
        )
        return

    if data.startswith("mode_"):
        mode = data.split("_", 1)[1]
        context.user_data["mode"] = mode
        await query.edit_message_text(
            MODES.get(mode, "Send me your input"),
            reply_markup=back_kb(),
            parse_mode="Markdown",
        )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = context.user_data.get("mode")
    if not mode:
        await update.message.reply_text(
            "Tap a button to start. Use /start.",
            reply_markup=main_menu(),
        )
        return

    try:
        data = build_qr_data(mode, update.message.text)
    except ValueError as e:
        await update.message.reply_text(f"⚠️ {e}", parse_mode="Markdown")
        return

    try:
        png = make_qr(data)
        bio = io.BytesIO(png)
        bio.name = "qrcode.png"
        await update.message.reply_photo(
            photo=InputFile(bio, filename="qrcode.png"),
            caption=f"✅ QR code ready ({len(data)} chars encoded).",
            reply_markup=main_menu(),
        )
    except Exception as e:
        log.error(f"QR generation failed: {e}")
        await update.message.reply_text(f"❌ Failed to generate: {e}")
    finally:
        context.user_data.pop("mode", None)

# ============================================================
# Main
# ============================================================
def main():
    token = os.environ.get("BOT_TOKEN")
    if not token:
        log.critical("BOT_TOKEN env var missing!")
        return

    threading.Thread(target=run_health_server, daemon=True).start()

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(menu_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    log.info("QR Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
