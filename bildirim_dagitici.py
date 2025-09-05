# bildirim_dagitici.py (Sistem Kapanış Bildirimi Eklendi)

import os
import logging
import time
import requests
import json
from supabase import create_client

# (AYARLAR ve send_telegram_message fonksiyonları aynı kalacak)
def setup_logging(): logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - [BildirimDagitici] - %(message)s')
def load_config():
    with open('config.json', 'r') as f: return json.load(f)
def get_supabase_client(config):
    url = config['supabase']['url']
    key = config['supabase']['key']
    return create_client(url, key)
def send_telegram_message(token, chat_id, message):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        logging.error(f"{chat_id}'ye mesaj gönderilemedi: {e}")
# ...

def notify_for_closed_signals(supabase, token, subscribers):
    """Veritabanında kapanmış ama bildirimi gönderilmemiş sinyalleri bulur ve gönderir."""
    # YENİ: 'closed_by_system' durumunu da kontrol listesine ekle
    response = supabase.table('signals').select('*').in_('status', ['tp_hit', 'sl_hit', 'closed_by_system']).eq('closure_notified', False).execute()
    closed_signals = response.data
    if not closed_signals: return

    logging.info(f"{len(closed_signals)} adet kapanan sinyal bulundu. Abonelere gönderiliyor...")
    for signal in closed_signals:
        if signal['status'] == 'tp_hit':
            result_icon = "✅"
            result_text = "TP OLDU"
        elif signal['status'] == 'sl_hit':
            result_icon = "❌"
            result_text = "STOP OLDU"
        else: # closed_by_system durumu
            result_icon = "⏰"
            result_text = "SİSTEM TARAFINDAN KAPATILDI (İşlem Saati Bitti)"
            
        msg = (f"{result_icon} *POZİSYON KAPANDI* {result_icon}\n\n"
               f"*{signal['symbol']}* - *{signal['type']}*\n\n"
               f"Sonuç: *{result_text}*")
        
        for sub in subscribers:
            send_telegram_message(token, sub['telegram_chat_id'], msg)
            time.sleep(0.1)
        
        supabase.table('signals').update({'closure_notified': True}).eq('id', signal['id']).execute()
        logging.info(f"Sinyal ID {signal['id']} için KAPANIŞ bildirimi tamamlandı.")

# (notify_for_alerts, notify_for_new_signals ve main fonksiyonları aynı kalacak)
def notify_for_alerts(supabase, token, subscribers):
    response = supabase.table('alerts').select('*').eq('notified', False).execute()
    new_alerts = response.data
    if not new_alerts: return
    for alert in new_alerts:
        direction = "YUKARI" if alert['type'] == 'breakout_up' else "AŞAĞI"
        msg = (f"🔔 *KIRILIM UYARISI* 🔔\n\n*{alert['symbol']}* paritesinde *{direction}* yönlü bir kırılım gerçekleşti.\n\n"
               f"Fiyat: `{alert['price']:.4f}`\n\n_İşlem sinyali için takip ediliyor..._")
        for sub in subscribers: send_telegram_message(token, sub['telegram_chat_id'], msg)
        supabase.table('alerts').update({'notified': True}).eq('id', alert['id']).execute()
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
                notify_for_alerts(supabase, token, subscribers)
                notify_for_new_signals(supabase, token, subscribers)
                notify_for_closed_signals(supabase, token, subscribers)
        except Exception as e:
            logging.error(f"Bildirim döngüsünde hata: {e}")
        time.sleep(config['loop_intervals']['notifier'])
if __name__ == '__main__':
    main()