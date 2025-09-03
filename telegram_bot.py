# telegram_bot.py

import os
import logging
import json
from supabase import create_client, Client
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# --- AYARLAR ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def load_config():
    with open('config.json', 'r') as f:
        return json.load(f)

def get_supabase_client(config):
    url = config['supabase']['url']
    key = config['supabase']['key']
    return create_client(url, key)

# --- KOMUT FONKSİYONLARI ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Merhaba! Sinyal botuna hoş geldiniz.\n"
        "/subscribe - Sinyal bildirimlerini almak için abone olun.\n"
        "/unsubscribe - Abonelikten ayrılın."
    )

async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    username = update.message.from_user.username
    supabase = context.bot_data["supabase"]
    try:
        supabase.table('subscribers').upsert({
            'telegram_chat_id': chat_id,
            'username': username,
            'is_active': True
        }, on_conflict='telegram_chat_id').execute()
        await update.message.reply_text("✅ Başarıyla abone oldunuz! Yeni sinyaller size bildirilecektir.")
        logging.info(f"Yeni abone: {chat_id} ({username})")
    except Exception as e:
        logging.error(f"Abone olma hatası: {e}")
        await update.message.reply_text("❌ Abonelik sırasında bir hata oluştu.")

async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    supabase = context.bot_data["supabase"]
    try:
        supabase.table('subscribers').update({'is_active': False}).eq('telegram_chat_id', chat_id).execute()
        await update.message.reply_text("Abonelikten ayrıldınız. Artık bildirim almayacaksınız.")
        logging.info(f"Abonelikten ayrılan: {chat_id}")
    except Exception as e:
        logging.error(f"Abonelikten ayrılma hatası: {e}")
        await update.message.reply_text("❌ Abonelikten ayrılırken bir hata oluştu.")

# --- ANA ÇALIŞTIRMA ---
def main():
    config = load_config()
    token = config['telegram']['token']
    if "YOUR_TELEGRAM" in token:
        logging.critical("TELEGRAM_TOKEN config.json içinde ayarlanmamış!")
        return

    application = Application.builder().token(token).build()
    application.bot_data["supabase"] = get_supabase_client(config)
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("subscribe", subscribe))
    application.add_handler(CommandHandler("unsubscribe", unsubscribe))

    logging.info("Telegram Botu başlatıldı ve dinlemede...")
    application.run_polling()

if __name__ == '__main__':
    main()