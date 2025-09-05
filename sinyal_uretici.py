# sinyal_uretici.py (İşlem Saatleri Kontrolü Eklendi)

import os
import time
import logging
import json
from datetime import datetime
import pytz
import ccxt
import pandas as pd
from supabase import create_client

# --- AYARLAR ---
def setup_logging(): logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - [SinyalUretici] - %(message)s', handlers=[logging.FileHandler('sinyal_uretici.log'), logging.StreamHandler()])
def load_config():
    with open('config.json', 'r') as f: return json.load(f)
def get_supabase_client(config):
    url = config['supabase']['url']
    key = config['supabase']['key']
    if "YOUR" in url or "YOUR" in key: logging.critical("Supabase ayarları yapılmamış!"); exit()
    return create_client(url, key)

# --- STRATEJİ ---
# (get_ny_4h_levels ve find_new_signal fonksiyonları önceki koddan buraya kopyalanacak)
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

def find_events(df, upper_limit, lower_limit, breakout_state, symbol, supabase):
    if df.empty or len(df) < 2: return None
    last_candle = df.iloc[-2]
    new_signal = None
    if not breakout_state['short_detected'] and last_candle['close'] > upper_limit:
        breakout_state['short_detected'] = True
        breakout_state['peak_price'] = last_candle['high']
        alert_data = {'symbol': symbol, 'type': 'breakout_up', 'price': last_candle['close']}
        supabase.table('alerts').insert(alert_data).execute()
        logging.info(f"[{symbol}] YUKARI YÖNLÜ KIRILIM TESPİT EDİLDİ: {alert_data}")
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
        alert_data = {'symbol': symbol, 'type': 'breakdown_down', 'price': last_candle['close']}
        supabase.table('alerts').insert(alert_data).execute()
        logging.info(f"[{symbol}] AŞAĞI YÖNLÜ KIRILIM TESPİT EDİLDİ: {alert_data}")
    elif breakout_state['long_detected']:
        breakout_state['trough_price'] = min(breakout_state['trough_price'], last_candle['low'])
        if last_candle['close'] > lower_limit:
            entry_price, stop_loss = last_candle['close'], breakout_state['trough_price']
            if (entry_price - stop_loss) > 0:
                new_signal = {"type": "LONG", "entry_price": entry_price, "stop_loss": stop_loss, "take_profit_2r": entry_price + 2 * (entry_price - stop_loss)}
            breakout_state['long_detected'] = False

    return new_signal

# --- ANA DÖNGÜ ---
def main():
    config = load_config()
    setup_logging()
    supabase = get_supabase_client(config)
    exchange = ccxt.binance({'options': {'defaultType': 'future'}})
    ny_timezone = pytz.timezone("America/New_York")
    breakout_states = {symbol: {'short_detected': False, 'long_detected': False, 'peak_price': 0, 'trough_price': 0} for symbol in config['symbols']}
    logging.info("Sinyal Üretici (Perpetual Futures Modu) Başlatıldı.")

    while True:
        try:
            current_ny_time = datetime.now(ny_timezone)
            ny_hour = current_ny_time.hour
            
            # İşlem saatleri: NY 04:00 (mum kapanışı) ile 17:00 arası
            is_trading_hours = 4 <= ny_hour < 17

            response = supabase.table('signals').select('id, symbol, type, stop_loss, take_profit_2r').eq('status', 'active').execute()
            active_trades = response.data if response.data else []
            
            # Önce aktif işlemleri yönet
            for trade in active_trades:
                # EĞER İŞLEM SAATİ DIŞINDAYSAK, TÜM AKTİF İŞLEMLERİ KAPAT
                if not is_trading_hours:
                    logging.info(f"[{trade['symbol']}] İşlem saati bitti. Aktif pozisyon kapatılıyor.")
                    supabase.table('signals').update({'status': 'closed_by_system'}).eq('id', trade['id']).execute()
                    continue # Diğer kontrollere geçme

                # İşlem saati içindeysek normal TP/SL takibi yap
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

            # EĞER İŞLEM SAATİ İÇİNDEYSEK ve aktif işlem yoksa, yeni sinyal ara
            if is_trading_hours:
                active_symbols = [trade['symbol'] for trade in active_trades]
                symbols_to_scan = [s for s in config['symbols'] if s not in active_symbols]
                if symbols_to_scan:
                    for symbol in symbols_to_scan:
                        upper_limit, lower_limit = get_ny_4h_levels(symbol, current_ny_time, exchange, ny_timezone)
                        if not upper_limit: continue
                        ohlcv = exchange.fetch_ohlcv(symbol, '5m', limit=10)
                        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                        new_signal = find_events(df, upper_limit, lower_limit, breakout_states[symbol], symbol, supabase)
                        if new_signal:
                            signal_data = {**new_signal, 'symbol': symbol, 'status': 'active', 'notified': False}
                            supabase.table('signals').insert(signal_data).execute()
                            logging.info(f"[{symbol}] YENİ SİNYAL: {signal_data}")

            time.sleep(config['loop_intervals']['signal_generator'])
        except Exception as e:
            logging.critical(f"Ana döngüde kritik hata: {e}", exc_info=True)
            time.sleep(60)

if __name__ == "__main__":
    main()