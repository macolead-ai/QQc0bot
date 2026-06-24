import logging
import os
import asyncio
from aiohttp import web
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get('BOT_TOKEN')

# ---------- Funcionalidade de Lembrete ----------

async def send_reminder(context: ContextTypes.DEFAULT_TYPE):
    """Envia o lembrete a cada 4 horas"""
    job = context.job
    keyboard = [
        [InlineKeyboardButton("Clique para participar já 🟢", url="https://t.me/NM_NunoMoraiss89")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    texto = "🔔 Lembrete: Não fique de fora! Junte-se à nossa comunidade exclusiva e comece a receber as melhores análises.\n\nhttps://t.me/NM_NunoMoraiss89"
    
    try:
        await context.bot.send_message(chat_id=job.chat_id, text=texto, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Erro ao enviar lembrete para {job.chat_id}: {e}")

# ---------- Commands ----------

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info(f"Utilizador {user.id} iniciou o bot")

    # 1. Enviar a mensagem principal de boas-vindas
    welcome_text = (
        "Antes de mais, obrigado por estar aqui. 🙏 Agradecemos imenso por ter dedicado o seu tempo para se juntar a este espaço. Seja por acaso ou por recomendação de um amigo, saiba que agora faz parte de algo especial. 💫\n\n"
        "Este não é apenas mais um grupo de apostas. ❌ Esta é uma comunidade construída sobre uma paixão partilhada: o amor pelo jogo ⚽🏀, a emoção da análise 📊 e a procura de decisões informadas e inteligentes. 🧠 Não acreditamos na sorte cega. 🎲 Acreditamos na preparação, na investigação e na disciplina. 📚 E é exatamente isso que oferecemos todos os dias. 💪"
    )
    await update.message.reply_text(welcome_text)

    # 2. Esperar 2 segundos
    await asyncio.sleep(2)

    # 3. Enviar o link do canal com o botão
    keyboard = [
        [InlineKeyboardButton("Clique para participar já 🟢", url="https://t.me/NM_NunoMoraiss89")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("https://t.me/NM_NunoMoraiss89", reply_markup=reply_markup)

    # 4. Agendar o lembrete a cada 4 horas (14400 segundos)
    if context.job_queue:
        # Remover lembretes antigos para não duplicar se a pessoa clicar em /start várias vezes
        current_jobs = context.job_queue.get_jobs_by_name(str(user.id))
        for job in current_jobs:
            job.schedule_removal()
        
        # Agendar a repetição de 4 em 4 horas (4 * 60 * 60 = 14400)
        context.job_queue.run_repeating(
            send_reminder, 
            interval=14400, 
            first=14400, 
            chat_id=user.id, 
            name=str(user.id)
        )
    else:
        logger.warning("Job queue não está a funcionar. Verifique se tem 'apscheduler' instalado.")

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
