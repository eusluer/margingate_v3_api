# test_telegram.py
import logging
import json
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

# Ayarları yükle
with open('config.json', 'r') as f:
    config = json.load(f)
TOKEN = config['telegram']['token']

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("TEST BAŞARILI! /start komutu çalışıyor.")

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("ECHO TESTİ BAŞARILI! Mesaj: " + update.message.text)

def main():
    if "YOUR_TELEGRAM" in TOKEN:
        logging.critical("Lütfen config.json dosyasındaki Telegram token'ı güncelleyin.")
        return

    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

    logging.info("Basit test botu başlatıldı...")
    application.run_polling()

if __name__ == '__main__':
    main()