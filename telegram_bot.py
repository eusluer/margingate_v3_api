# telegram_bot.py

import os
import logging
import json
from supabase import create_client
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# --- AYARLAR ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - [TelegramBot] - %(message)s')
def load_config():
    with open('config.json', 'r') as f: return json.load(f)
def get_supabase_client(config):
    url = config['supabase']['url']
    key = config['supabase']['key']
    return create_client(url, key)

# --- KOMUTLAR ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    supabase = context.bot_data["supabase"]
    welcome_message = "Merhaba! Sinyal botuna hoş geldiniz.\n\nAboneliğiniz başlatıldı. ✅\n\nAbonelikten ayrılmak için /unsubscribe kullanabilirsiniz."
    try:
        supabase.table('subscribers').upsert({'telegram_chat_id': chat_id, 'is_active': True}, on_conflict='telegram_chat_id').execute()
        await update.message.reply_text(welcome_message)
        logging.info(f"/start ile yeni abone: {chat_id}")
    except Exception as e:
        logging.error(f"Otomatik abone etme hatası: {e}")
        await update.message.reply_text("❌ Abonelik sırasında bir hata oluştu. Lütfen daha sonra tekrar deneyin.")

async def unsubscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    supabase = context.bot_data["supabase"]
    try:
        supabase.table('subscribers').update({'is_active': False}).eq('telegram_chat_id', chat_id).execute()
        await update.message.reply_text("Abonelikten ayrıldınız.")
        logging.info(f"Abonelikten ayrılan: {chat_id}")
    except Exception as e:
        logging.error(f"Abonelikten ayrılma hatası: {e}")

# --- ANA ÇALIŞTIRMA ---
def main():
    config = load_config()
    token = config['telegram']['token']
    if "YOUR" in token:
        logging.critical("Telegram token ayarlanmamış!")
        return
    application = Application.builder().token(token).build()
    application.bot_data["supabase"] = get_supabase_client(config)
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("subscribe", start_command)) # /subscribe da /start gibi çalışsın
    application.add_handler(CommandHandler("unsubscribe", unsubscribe_command))
    logging.info("Telegram Botu başlatıldı ve dinlemede...")
    application.run_polling(stop_signals=None)

if __name__ == '__main__':
    main()