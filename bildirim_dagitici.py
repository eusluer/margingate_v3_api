import os
import logging
import time
import requests
from supabase import create_client, Client

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_supabase_client():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    return create_client(url, key)

def send_telegram_message(token, chat_id, message):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.ok
    except Exception as e:
        logging.error(f"{chat_id}'ye mesaj gönderilemedi: {e}")
        return False

def main():
    supabase = get_supabase_client()
    token = os.environ.get("TELEGRAM_TOKEN")
    if not token:
        logging.critical("TELEGRAM_TOKEN ortam değişkeni ayarlanmamış!")
        return

    logging.info("Bildirim Dağıtıcı Başlatıldı.")
    
    while True:
        try:
            # 1. Bildirimi gönderilmemiş yeni sinyalleri bul
            response = supabase.table('signals').select('*').eq('status', 'active').eq('notified', False).execute()
            new_signals = response.data

            if new_signals:
                logging.info(f"{len(new_signals)} adet yeni sinyal bulundu. Abonelere gönderiliyor...")
                
                # 2. Tüm aktif aboneleri al
                sub_response = supabase.table('subscribers').select('telegram_chat_id').eq('is_active', True).execute()
                subscribers = sub_response.data
                
                if not subscribers:
                    logging.warning("Aktif abone bulunamadı. Bildirim gönderilemiyor.")
                else:
                    for signal in new_signals:
                        # 3. Her sinyali her aboneye gönder
                        msg = (f"🚨 YENİ SİNYAL: *{signal['symbol']}*\n"
                               f"Yön: *{signal['type']}*\n"
                               f"Giriş Fiyatı: `{signal['entry_price']:.4f}`\n"
                               f"Stop Loss: `{signal['stop_loss']:.4f}`\n"
                               f"Take Profit: `{signal['take_profit_2R']:.4f}`")
                        
                        for sub in subscribers:
                            send_telegram_message(token, sub['telegram_chat_id'], msg)
                            time.sleep(0.1) # Telegram limitlerine takılmamak için küçük bekleme

                        # 4. Sinyalin 'notified' durumunu güncelle
                        supabase.table('signals').update({'notified': True}).eq('id', signal['id']).execute()
                        logging.info(f"Sinyal ID {signal['id']} için bildirimler tamamlandı.")

        except Exception as e:
            logging.error(f"Bildirim döngüsünde hata: {e}")
        
        time.sleep(20) # Her 20 saniyede bir veritabanını kontrol et

if __name__ == '__main__':
    main()