# main.py (Otomatik Abonelikli Son Versiyon)

import os
import time
import logging
import json
import threading
import asyncio
from datetime import datetime
import pytz
import ccxt
import pandas as pd
import requests
from supabase import create_client, Client
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# --- 1: TEMEL AYARLAR VE YAPILANDIRMA ---
def setup_logging(log_file):
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - [%(threadName)s] - %(message)s', handlers=[logging.FileHandler(log_file), logging.StreamHandler()])
def load_config(filename='config.json'):
    with open(filename, 'r') as f: return json.load(f)
def get_supabase_client(config):
    url = config['supabase']['url']
    key = config['supabase']['key']
    if "YOUR_SUPABASE" in url or "YOUR_SUPABASE" in key:
        logging.critical("Supabase URL veya Key config.json içinde ayarlanmamış!")
        exit()
    return create_client(url, key)

# --- 2: SİNYAL ÜRETİCİ BÖLÜMÜ ---
def get_ny_4h_levels(symbol, for_date, exchange, ny_timezone):
    try:
        start_time = for_date.replace(hour=0, minute=0, second=0, microsecond=0)
        start_ts = int(start_time.timestamp() * 1000)
        ohlcv = exchange.fetch_ohlcv(symbol, '4h', since=start_ts, limit=1)
        if ohlcv:
            candle_start_time = datetime.fromtimestamp(ohlcv[0][0]/1000, tz=pytz.utc).astimezone(ny_timezone)
            if candle_start_time.date() == for_date.date() and candle_start_time.hour == 0:
                return ohlcv[0][2], ohlcv[0][3]
    except Exception as e:
        logging.error(f"[{symbol}] 4S seviyeleri alınamadı: {e}")
    return None, None
def find_new_signal(df, upper_limit, lower_limit, breakout_state):
    if df.empty or len(df) < 2: return None
    last_candle = df.iloc[-2]
    new_signal = None
    if not breakout_state['short_detected'] and last_candle['close'] > upper_limit:
        breakout_state['short_detected'] = True
        breakout_state['peak_price'] = last_candle['high']
    elif breakout_state['short_detected']:
        breakout_state['peak_price'] = max(breakout_state['peak_price'], last_candle['high'])
        if last_candle['close'] < upper_limit:
            entry_price, stop_loss = last_candle['close'], breakout_state['peak_price']
            if (stop_loss - entry_price) > 0:
                new_signal = {"type": "SHORT", "entry_price": entry_price, "stop_loss": stop_loss, "take_profit_2r": entry_price - 2 * (stop_loss - entry_price)}
            breakout_state['short_detected'] = False
    if not breakout_state['long_detected'] and last_candle['close'] < lower_limit:
        breakout_state['long_detected'] = True
        breakout_state['trough_price'] = last_candle['low']
    elif breakout_state['long_detected']:
        breakout_state['trough_price'] = min(breakout_state['trough_price'], last_candle['low'])
        if last_candle['close'] > lower_limit:
            entry_price, stop_loss = last_candle['close'], breakout_state['trough_price']
            if (entry_price - stop_loss) > 0:
                new_signal = {"type": "LONG", "entry_price": entry_price, "stop_loss": stop_loss, "take_profit_2r": entry_price + 2 * (entry_price - stop_loss)}
            breakout_state['long_detected'] = False
    return new_signal
def run_signal_generator(config, supabase):
    logging.info("Sinyal Üretici thread'i başlatıldı.")
    exchange = ccxt.binance()
    ny_timezone = pytz.timezone("America/New_York")
    breakout_states = {symbol: {'short_detected': False, 'long_detected': False, 'peak_price': 0, 'trough_price': 0} for symbol in config['symbols']}
    while True:
        try:
            response = supabase.table('signals').select('id, symbol, type, stop_loss, take_profit_2r').eq('status', 'active').execute()
            active_trades = response.data if response.data else []
            active_symbols = [trade['symbol'] for trade in active_trades]
            for trade in active_trades:
                try:
                    ticker = exchange.fetch_ticker(trade['symbol'])
                    last_price = ticker['last']
                    result = None
                    if trade['type'] == 'SHORT' and last_price >= trade['stop_loss']: result = 'sl_hit'
                    if trade['type'] == 'SHORT' and last_price <= trade['take_profit_2r']: result = 'tp_hit'
                    if trade['type'] == 'LONG' and last_price <= trade['stop_loss']: result = 'sl_hit'
                    if trade['type'] == 'LONG' and last_price >= trade['take_profit_2r']: result = 'tp_hit'
                    if result:
                        logging.info(f"[{trade['symbol']}] POZİSYON KAPANDI: {result}")
                        supabase.table('signals').update({'status': result}).eq('id', trade['id']).execute()
                except Exception as e:
                    logging.error(f"[{trade['symbol']}] Aktif işlem takibinde hata: {e}")
            symbols_to_scan = [s for s in config['symbols'] if s not in active_symbols]
            if symbols_to_scan:
                current_ny_time = datetime.now(ny_timezone)
                if 4 <= current_ny_time.hour:
                    for symbol in symbols_to_scan:
                        upper_limit, lower_limit = get_ny_4h_levels(symbol, current_ny_time, exchange, ny_timezone)
                        if not upper_limit: continue
                        ohlcv = exchange.fetch_ohlcv(symbol, '5m', limit=10)
                        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                        new_signal = find_new_signal(df, upper_limit, lower_limit, breakout_states[symbol])
                        if new_signal:
                            signal_data = {**new_signal, 'symbol': symbol, 'status': 'active', 'notified': False}
                            supabase.table('signals').insert(signal_data).execute()
                            logging.info(f"[{symbol}] YENİ SİNYAL: {signal_data}")
            time.sleep(config['loop_intervals']['signal_generator'])
        except Exception as e:
            logging.critical(f"Sinyal Üretici ana döngü hatası: {e}", exc_info=True)
            time.sleep(60)

# --- 3: TELEGRAM BOTU BÖLÜMÜ ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kullanıcı /start dediğinde OTOMATİK OLARAK ABONE EDER."""
    chat_id = update.message.chat_id
    username = update.message.from_user.username
    supabase = context.bot_data["supabase"]
    
    welcome_message = (
        "Merhaba! Sinyal botuna hoş geldiniz.\n\n"
        "Yeni sinyal bildirimleri için aboneliğiniz otomatik olarak başlatıldı. ✅\n\n"
        "Abonelikten ayrılmak isterseniz /unsubscribe komutunu kullanabilirsiniz."
    )
    
    try:
        supabase.table('subscribers').upsert({
            'telegram_chat_id': chat_id,
            'username': username,
            'is_active': True
        }, on_conflict='telegram_chat_id').execute()
        await update.message.reply_text(welcome_message)
        logging.info(f"/start komutu ile yeni abone: {chat_id} ({username})")
    except Exception as e:
        logging.error(f"Otomatik abone olma hatası: {e}")
        await update.message.reply_text("❌ Hoş geldiniz! Ancak abonelik sırasında bir hata oluştu. Lütfen /subscribe komutunu deneyin.")

async def subscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kullanıcı /subscribe dediğinde abone eder."""
    chat_id = update.message.chat_id
    username = update.message.from_user.username
    supabase = context.bot_data["supabase"]
    try:
        supabase.table('subscribers').upsert({'telegram_chat_id': chat_id, 'is_active': True}, on_conflict='telegram_chat_id').execute()
        await update.message.reply_text("✅ Başarıyla abone oldunuz! Yeni sinyaller size bildirilecektir.")
        logging.info(f"Manuel abone: {chat_id} ({username})")
    except Exception as e:
        logging.error(f"Abone olma hatası: {e}")
        await update.message.reply_text("❌ Abonelik sırasında bir hata oluştu.")

async def unsubscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    supabase = context.bot_data["supabase"]
    try:
        supabase.table('subscribers').update({'is_active': False}).eq('telegram_chat_id', chat_id).execute()
        await update.message.reply_text("Abonelikten ayrıldınız.")
        logging.info(f"Abonelikten ayrılan: {chat_id}")
    except Exception as e:
        logging.error(f"Abonelikten ayrılma hatası: {e}")
        await update.message.reply_text("❌ Abonelikten ayrılırken bir hata oluştu.")

async def async_telegram_main(config, supabase):
    token = config['telegram']['token']
    application = Application.builder().token(token).build()
    application.bot_data["supabase"] = supabase
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("subscribe", subscribe_command))
    application.add_handler(CommandHandler("unsubscribe", unsubscribe_command))
    async with application:
        logging.info("Telegram Botu başlatıldı ve dinlemede...")
        await application.start()
        await application.updater.start_polling(stop_signals=None)
        while True:
            await asyncio.sleep(3600)

def run_telegram_bot(config, supabase):
    logging.info("Telegram Bot thread'i başlatılıyor...")
    try:
        asyncio.run(async_telegram_main(config, supabase))
    except Exception as e:
        logging.critical(f"Telegram botu thread'inde kritik hata: {e}", exc_info=True)

# --- 4: BİLDİRİM DAĞITICI BÖLÜMÜ ---
def send_telegram_message(token, chat_id, message):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        logging.error(f"{chat_id}'ye mesaj gönderilemedi: {e}")

def run_notifier(config, supabase):
    logging.info("Bildirim Dağıtıcı thread'i başlatıldı.")
    token = config['telegram']['token']
    while True:
        try:
            # Kapanış bildirimi gönderilecekleri bul
            closed_response = supabase.table('signals').select('*').in_('status', ['tp_hit', 'sl_hit']).eq('closure_notified', False).execute()
            if closed_response.data:
                sub_response = supabase.table('subscribers').select('telegram_chat_id').eq('is_active', True).execute()
                subscribers = sub_response.data
                if subscribers:
                    for signal in closed_response.data:
                        result_icon = "✅" if signal['status'] == 'tp_hit' else "❌"
                        result_text = "TP OLDU" if signal['status'] == 'tp_hit' else "STOP OLDU"
                        msg = (f"{result_icon} *POZİSYON KAPANDI* {result_icon}\n\n"
                               f"*{signal['symbol']}* - *{signal['type']}*\n\n"
                               f"Sonuç: *{result_text}*")
                        for sub in subscribers: send_telegram_message(token, sub['telegram_chat_id'], msg)
                        supabase.table('signals').update({'closure_notified': True}).eq('id', signal['id']).execute()
                        logging.info(f"Sinyal ID {signal['id']} için KAPANIŞ bildirimi tamamlandı.")

            # Yeni sinyal bildirimi gönderilecekleri bul
            new_response = supabase.table('signals').select('*').eq('notified', False).execute()
            if new_response.data:
                sub_response = supabase.table('subscribers').select('telegram_chat_id').eq('is_active', True).execute()
                subscribers = sub_response.data
                if subscribers:
                    for signal in new_response.data:
                        msg = (f"🚨 *YENİ SİNYAL* 🚨\n\n"
                               f"*{signal['symbol']}* - *{signal['type']}*\n\n"
                               f"Giriş Fiyatı: `{signal['entry_price']:.4f}`\n"
                               f"Stop Loss: `{signal['stop_loss']:.4f}`\n"
                               f"Take Profit: `{signal['take_profit_2r']:.4f}`")
                        for sub in subscribers: send_telegram_message(token, sub['telegram_chat_id'], msg)
                        supabase.table('signals').update({'notified': True}).eq('id', signal['id']).execute()
                        logging.info(f"Sinyal ID {signal['id']} için YENİ SİNYAL bildirimi tamamlandı.")
        except Exception as e:
            logging.error(f"Bildirim döngüsünde hata: {e}")
        time.sleep(config['loop_intervals']['notifier'])


# --- ANA PROGRAM BAŞLANGICI ---
if __name__ == "__main__":
    config = load_config()
    setup_logging(config['log_file'])
    supabase_client = get_supabase_client(config)
    generator_thread = threading.Thread(target=run_signal_generator, name="SinyalUretici", args=(config, supabase_client))
    telegram_thread = threading.Thread(target=run_telegram_bot, name="TelegramBot", args=(config, supabase_client))
    notifier_thread = threading.Thread(target=run_notifier, name="BildirimDagitici", args=(config, supabase_client))
    generator_thread.start()
    telegram_thread.start()
    notifier_thread.start()
    logging.info("Tüm bot servisleri başlatıldı.")
    generator_thread.join()
    telegram_thread.join()
    notifier_thread.join()