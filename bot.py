 import logging
import os
import io
import asyncio
from aiohttp import web
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)
import qrcode
from qrcode.constants import ERROR_CORRECT_H
from PIL import Image

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get('BOT_TOKEN')

# QR Types
QR_TYPES = [
    ("🔗 URL / Website",  "url"),
    ("📝 Plain Text",     "text"),
    ("📶 WiFi Network",   "wifi"),
    ("👤 Contact (vCard)", "vcard"),
    ("📧 Email",          "email"),
    ("📞 Phone Call",     "phone"),
    ("💬 SMS",            "sms"),
]

# Color themes (fg, bg)
THEMES = [
    ("⚫ Classic (B/W)",    ((0, 0, 0),       (255, 255, 255))),
    ("🔵 Ocean Blue",       ((30, 80, 180),   (255, 255, 255))),
    ("🟣 Purple",           ((118, 30, 180),  (255, 255, 255))),
    ("🟢 Green",            ((39, 130, 80),   (255, 255, 255))),
    ("🔴 Red",              ((180, 40, 40),   (255, 255, 255))),
    ("⚪ Inverted",         ((255, 255, 255), (20, 20, 30))),
]


# ---------- Helpers ----------

def main_menu_markup() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("⚡ Create QR Code", callback_data="menu_create")],
        [InlineKeyboardButton("ℹ️ Help", callback_data="menu_help")],
    ]
    return InlineKeyboardMarkup(keyboard)


def type_markup() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(lbl, callback_data=f"type_{key}")] for lbl, key in QR_TYPES]
    rows.append([InlineKeyboardButton("🏠 Main Menu", callback_data="menu_home")])
    return InlineKeyboardMarkup(rows)


def theme_markup() -> InlineKeyboardMarkup:
    rows = []
    for i in range(0, len(THEMES), 2):
        row = []
        for j, (lbl, _) in enumerate(THEMES[i:i+2]):
            row.append(InlineKeyboardButton(lbl, callback_data=f"theme_{i+j}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("🏠 Main Menu", callback_data="menu_home")])
    return InlineKeyboardMarkup(rows)


def reset_user_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    for key in ('mode', 'qr_type', 'qr_data', 'qr_step', 'qr_inputs'):
        context.user_data.pop(key, None)


# ---------- Commands ----------

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info(f"User {user.id} started the bot")
    reset_user_state(context)

    welcome = (
        "👋 *Welcome to QR Code Generator Bot!*\n\n"
        "I create QR codes for anything 🚀\n\n"
        "✨ *Supports:*\n"
        "• 🔗 URLs & websites\n"
        "• 📝 Plain text\n"
        "• 📶 WiFi (auto-connect)\n"
        "• 👤 Contact cards (vCard)\n"
        "• 📧 Emails, 📞 Phone, 💬 SMS\n\n"
        "🎨 6 color themes available\n\n"
        "Tap below to begin:"
    )
    await update.message.reply_text(welcome, reply_markup=main_menu_markup(), parse_mode='Markdown')


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "ℹ️ *How to use*\n\n"
        "1. Tap ⚡ *Create QR Code*\n"
        "2. Pick the QR type\n"
        "3. Send the required info\n"
        "4. Choose a color theme\n"
        "5. Get your QR code (PNG)\n\n"
        "💡 *WiFi format:* You'll be asked for SSID, password & security type\n"
        "💡 *vCard:* Name, phone, email, organization\n\n"
        "Use /cancel anytime to reset."
    )
    if update.message:
        await update.message.reply_text(text, parse_mode='Markdown', reply_markup=main_menu_markup())
    else:
        await update.callback_query.edit_message_text(
            text, parse_mode='Markdown', reply_markup=main_menu_markup()
        )


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_user_state(context)
    await update.message.reply_text(
        "❌ Cancelled. Use /start to begin again.",
        reply_markup=main_menu_markup(),
    )


# ---------- Menu callbacks ----------

async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "menu_home":
        reset_user_state(context)
        await query.edit_message_text(
            "🏠 *Main Menu*\nChoose an option below:",
            reply_markup=main_menu_markup(),
            parse_mode='Markdown',
        )

    elif data == "menu_help":
        await help_command(update, context)

    elif data == "menu_create":
        await query.edit_message_text(
            "⚡ *Create QR Code*\n\nPick the type of QR code:",
            reply_markup=type_markup(),
            parse_mode='Markdown',
        )

    elif data.startswith("type_"):
        qtype = data.split("_", 1)[1]
        context.user_data['qr_type'] = qtype
        context.user_data['qr_inputs'] = {}
        context.user_data['qr_step'] = 0
        prompt = get_next_prompt(qtype, 0)
        context.user_data['mode'] = 'collecting'
        await query.edit_message_text(
            f"📥 *{prompt['title']}*\n\n{prompt['ask']}\n\n_Use /cancel to abort._",
            parse_mode='Markdown',
        )

    elif data.startswith("theme_"):
        idx = int(data.split("_", 1)[1])
        await do_generate(update, context, idx)


# ---------- Step-by-step input flow ----------

STEPS = {
    "url": [
        {"title": "URL", "ask": "Send the URL (e.g. `https://example.com`)", "key": "url"},
    ],
    "text": [
        {"title": "Text", "ask": "Send the text to encode (max 500 chars).", "key": "text"},
    ],
    "wifi": [
        {"title": "WiFi Name", "ask": "Send the WiFi network name (SSID).", "key": "ssid"},
        {"title": "WiFi Password", "ask": "Send the WiFi password.\nSend `none` if it's an open network.", "key": "password"},
        {"title": "Security Type", "ask": "Send the security type: `WPA`, `WEP`, or `nopass`", "key": "security"},
    ],
    "vcard": [
        {"title": "Full Name", "ask": "Send the full name.", "key": "name"},
        {"title": "Phone", "ask": "Send the phone number (e.g. `+1234567890`).\nSend `skip` to omit.", "key": "phone"},
        {"title": "Email", "ask": "Send the email address.\nSend `skip` to omit.", "key": "email"},
        {"title": "Organization", "ask": "Send the organization/company.\nSend `skip` to omit.", "key": "org"},
    ],
    "email": [
        {"title": "Email Address", "ask": "Send the email address (e.g. `hello@example.com`).", "key": "email"},
        {"title": "Subject", "ask": "Send the email subject.\nSend `skip` to omit.", "key": "subject"},
        {"title": "Body", "ask": "Send the email body.\nSend `skip` to omit.", "key": "body"},
    ],
    "phone": [
        {"title": "Phone Number", "ask": "Send the phone number (e.g. `+1234567890`).", "key": "phone"},
    ],
    "sms": [
        {"title": "Phone Number", "ask": "Send the recipient phone number.", "key": "phone"},
        {"title": "Message", "ask": "Send the SMS message text.\nSend `skip` to omit.", "key": "message"},
    ],
}


def get_next_prompt(qtype: str, step: int):
    return STEPS[qtype][step]


def get_total_steps(qtype: str):
    return len(STEPS[qtype])


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('mode') != 'collecting':
        return

    qtype = context.user_data.get('qr_type')
    step = context.user_data.get('qr_step', 0)
    inputs = context.user_data.get('qr_inputs', {})

    text = (update.message.text or "").strip()
    if not text:
        await update.message.reply_text("⚠️ Empty input. Try again or /cancel.")
        return

    prompt = STEPS[qtype][step]
    key = prompt["key"]

    # Lightweight validation
    if qtype == "url" and key == "url":
        if not (text.startswith("http://") or text.startswith("https://")):
            text = "https://" + text
    if qtype == "text" and len(text) > 500:
        await update.message.reply_text("⚠️ Too long (max 500 chars). Try again or /cancel.")
        return
    if qtype == "wifi" and key == "security":
        if text.upper() not in ("WPA", "WEP", "NOPASS"):
            await update.message.reply_text("⚠️ Must be WPA, WEP, or nopass. Try again.")
            return
        text = text.upper()

    inputs[key] = text
    context.user_data['qr_inputs'] = inputs

    # Next step
    next_step = step + 1
    if next_step < get_total_steps(qtype):
        context.user_data['qr_step'] = next_step
        nxt = STEPS[qtype][next_step]
        await update.message.reply_text(
            f"✅ Got it.\n\n📥 *{nxt['title']}*\n\n{nxt['ask']}",
            parse_mode='Markdown',
        )
    else:
        # All inputs collected → ask for theme
        context.user_data['mode'] = 'theme_select'
        await update.message.reply_text(
            "🎨 All inputs collected!\n\nNow choose a color theme:",
            reply_markup=theme_markup(),
        )


# ---------- QR data builder ----------

def build_qr_data(qtype: str, inputs: dict) -> str:
    if qtype == "url":
        return inputs["url"]

    if qtype == "text":
        return inputs["text"]

    if qtype == "wifi":
        ssid = inputs["ssid"]
        pwd = inputs["password"]
        sec = inputs["security"]
        if sec == "NOPASS" or pwd.lower() == "none":
            return f"WIFI:T:nopass;S:{ssid};;"
        return f"WIFI:T:{sec};S:{ssid};P:{pwd};;"

    if qtype == "vcard":
        name = inputs.get("name", "")
        phone = inputs.get("phone", "")
        email = inputs.get("email", "")
        org = inputs.get("org", "")
        lines = ["BEGIN:VCARD", "VERSION:3.0", f"FN:{name}", f"N:{name};;;;"]
        if phone and phone.lower() != "skip":
            lines.append(f"TEL:{phone}")
        if email and email.lower() != "skip":
            lines.append(f"EMAIL:{email}")
        if org and org.lower() != "skip":
            lines.append(f"ORG:{org}")
        lines.append("END:VCARD")
        return "\n".join(lines)

    if qtype == "email":
        email = inputs["email"]
        subject = inputs.get("subject", "")
        body = inputs.get("body", "")
        params = []
        if subject and subject.lower() != "skip":
            params.append(f"subject={subject.replace(' ', '%20')}")
        if body and body.lower() != "skip":
            params.append(f"body={body.replace(' ', '%20')}")
        q = ("?" + "&".join(params)) if params else ""
        return f"mailto:{email}{q}"

    if qtype == "phone":
        return f"tel:{inputs['phone']}"

    if qtype == "sms":
        phone = inputs["phone"]
        msg = inputs.get("message", "")
        if msg and msg.lower() != "skip":
            return f"SMSTO:{phone}:{msg}"
        return f"sms:{phone}"

    return ""


# ---------- QR generation ----------

def generate_qr_image(data: str, fg, bg) -> bytes:
    qr = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_H,
        box_size=20,
        border=2,
    )
    qr.add_data(data)
    qr.make(fit=True)

    img = qr.make_image(fill_color=fg, back_color=bg).convert("RGB")

    # Resize to a clean 1024x1024 (with some padding)
    target = 1024
    img = img.resize((target, target), Image.NEAREST)

    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()


async def do_generate(update: Update, context: ContextTypes.DEFAULT_TYPE, theme_idx: int):
    query = update.callback_query
    qtype = context.user_data.get('qr_type')
    inputs = context.user_data.get('qr_inputs')

    if not qtype or not inputs:
        await query.edit_message_text("⚠️ Missing data. Start again.", reply_markup=main_menu_markup())
        return

    chat_id = query.message.chat_id
    await query.edit_message_text("⏳ Generating QR code…")

    try:
        data = build_qr_data(qtype, inputs)
        if not data:
            raise ValueError("Could not build QR data.")

        _, (fg, bg) = THEMES[theme_idx]

        loop = asyncio.get_event_loop()
        out_bytes = await loop.run_in_executor(
            None, generate_qr_image, data, fg, bg
        )

        type_label = next((lbl for lbl, k in QR_TYPES if k == qtype), qtype)
        out_name = f"qr_{qtype}.png"

        # Preview as photo + file
        await context.bot.send_photo(
            chat_id=chat_id,
            photo=InputFile(io.BytesIO(out_bytes), filename=out_name),
            caption=f"✅ *QR Code Ready!*\n\nType: {type_label}",
            parse_mode='Markdown',
        )
        # Also send as document for hi-res download
        await context.bot.send_document(
            chat_id=chat_id,
            document=InputFile(io.BytesIO(out_bytes), filename=out_name),
            caption="📥 Hi-res PNG (1024×1024)",
            reply_markup=main_menu_markup(),
        )

    except Exception as e:
        logger.error(f"QR generation failed: {e}")
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"❌ Failed: {e}",
            reply_markup=main_menu_markup(),
        )
    finally:
        reset_user_state(context)


# ---------- Dummy web server (keeps Render Web Service alive) ----------

async def health(request):
    return web.Response(text="Bot is running")


async def run_web():
    port = int(os.environ.get("PORT", 10000))
    app = web.Application()
    app.router.add_get("/", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Health server listening on port {port}")


# ---------- Runner ----------

async def run_bot():
    if not BOT_TOKEN:
        logger.critical("FATAL: BOT_TOKEN is missing!")
        return

    try:
        application = Application.builder().token(BOT_TOKEN).build()

        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("cancel", cancel_command))
        application.add_handler(CallbackQueryHandler(menu_callback))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

        await run_web()

        logger.info("Bot is now polling...")
        await application.initialize()
        await application.start()
        await application.updater.start_polling(drop_pending_updates=True)

        stop_event = asyncio.Event()
        await stop_event.wait()

    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
    finally:
        if 'application' in locals():
            await application.stop()
            await application.shutdown()


def main():
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
    except Exception as e:
        logger.error(f"Main loop error: {e}")


if __name__ == '__main__':
    main()
