# bildirim_dagitici.py

import os
import logging
import time
import requests
import json
from supabase import create_client

# --- AYARLAR ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - [BildirimDagitici] - %(message)s')
def load_config():
    with open('config.json', 'r') as f: return json.load(f)
def get_supabase_client(config):
    url = config['supabase']['url']
    key = config['supabase']['key']
    return create_client(url, key)

# --- BİLDİRİM FONKSİYONLARI ---
def send_telegram_message(token, chat_id, message):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        logging.error(f"{chat_id}'ye mesaj gönderilemedi: {e}")

def notify_for_new_signals(supabase, token, subscribers):
    response = supabase.table('signals').select('*').eq('notified', False).execute()
    new_signals = response.data
    if new_signals:
        for signal in new_signals:
            msg = (f"🚨 *YENİ SİNYAL* 🚨\n\n*{signal['symbol']}* - *{signal['type']}*\n\n"
                   f"Giriş Fiyatı: `{signal['entry_price']:.4f}`\nStop Loss: `{signal['stop_loss']:.4f}`\n"
                   f"Take Profit: `{signal['take_profit_2r']:.4f}`")
            for sub in subscribers: send_telegram_message(token, sub['telegram_chat_id'], msg)
            supabase.table('signals').update({'notified': True}).eq('id', signal['id']).execute()
            logging.info(f"Sinyal ID {signal['id']} için YENİ SİNYAL bildirimi tamamlandı.")

def notify_for_closed_signals(supabase, token, subscribers):
    response = supabase.table('signals').select('*').in_('status', ['tp_hit', 'sl_hit']).eq('closure_notified', False).execute()
    closed_signals = response.data
    if closed_signals:
        for signal in closed_signals:
            result_icon = "✅" if signal['status'] == 'tp_hit' else "❌"
            result_text = "TP OLDU" if signal['status'] == 'tp_hit' else "STOP OLDU"
            msg = (f"{result_icon} *POZİSYON KAPANDI* {result_icon}\n\n"
                   f"*{signal['symbol']}* - *{signal['type']}*\n\nSonuç: *{result_text}*")
            for sub in subscribers: send_telegram_message(token, sub['telegram_chat_id'], msg)
            supabase.table('signals').update({'closure_notified': True}).eq('id', signal['id']).execute()
            logging.info(f"Sinyal ID {signal['id']} için KAPANIŞ bildirimi tamamlandı.")

# --- ANA DÖNGÜ ---
def main():
    config = load_config()
    supabase = get_supabase_client(config)
    token = config['telegram']['token']
    logging.info("Bildirim Dağıtıcı Başlatıldı.")
    while True:
        try:
            sub_response = supabase.table('subscribers').select('telegram_chat_id').eq('is_active', True).execute()
            subscribers = sub_response.data
            if subscribers:
                notify_for_new_signals(supabase, token, subscribers)
                notify_for_closed_signals(supabase, token, subscribers)
        except Exception as e:
            logging.error(f"Bildirim döngüsünde hata: {e}")
        time.sleep(config['loop_intervals']['notifier'])

if __name__ == '__main__':
    main()