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
def setup_logging(): 
    logging.basicConfig(
        level=logging.INFO, 
        format='%(asctime)s - %(levelname)s - [SinyalUretici] - %(message)s', 
        handlers=[logging.FileHandler('sinyal_uretici.log'), logging.StreamHandler()]
    )

def load_config():
    with open('config.json', 'r') as f: 
        return json.load(f)

def get_supabase_client(config):
    url = config['supabase']['url']
    key = config['supabase']['key']
    if "YOUR" in url or "YOUR" in key: 
        logging.critical("Supabase ayarları yapılmamış!") 
        exit()
    return create_client(url, key)

# --- PERPETUAL EXCHANGE SETUP ---
def setup_perpetual_exchange():
    """Binance perpetual futures exchange'i ayarla"""
    exchange = ccxt.binance({
        'options': {
            'defaultType': 'future',  # Perpetual futures için
            'adjustForTimeDifference': True,
        }
    })
    exchange.load_markets()
    return exchange

def convert_symbol_to_perpetual(symbol):
    """Spot sembolü perpetual formatına çevir
    Örnek: BTC/USDT -> BTC/USDT:USDT"""
    if ':' not in symbol:
        # Eğer zaten perpetual formatında değilse, dönüştür
        base_quote = symbol.split('/')
        if len(base_quote) == 2 and base_quote[1] == 'USDT':
            return f"{symbol}:USDT"
    return symbol

# --- STRATEJİ ---
def get_ny_4h_levels(symbol, for_date, exchange, ny_timezone):
    """New York saat 00:00'daki 4 saatlik mumun high ve low seviyelerini al"""
    try:
        # Perpetual sembol formatına çevir
        perp_symbol = convert_symbol_to_perpetual(symbol)
        
        start_time = for_date.replace(hour=0, minute=0, second=0, microsecond=0)
        start_ts = int(start_time.timestamp() * 1000)
        
        # Perpetual piyasadan 4 saatlik mumu al
        ohlcv = exchange.fetch_ohlcv(perp_symbol, '4h', since=start_ts, limit=1)
        
        if ohlcv:
            candle_start_time = datetime.fromtimestamp(ohlcv[0][0]/1000, tz=pytz.utc).astimezone(ny_timezone)
            if candle_start_time.date() == for_date.date() and candle_start_time.hour == 0:
                high = ohlcv[0][2]
                low = ohlcv[0][3]
                logging.info(f"[{perp_symbol}] NY 00:00 4S seviyeleri - High: {high:.2f}, Low: {low:.2f}")
                return high, low
    except Exception as e:
        logging.error(f"[{symbol}] 4S seviyeleri alınamadı: {e}")
    return None, None

def find_new_signal(df, upper_limit, lower_limit, breakout_state, symbol):
    """Breakout sinyallerini tespit et"""
    if df.empty or len(df) < 2: 
        return None
    
    last_candle = df.iloc[-2]  # Tamamlanmış son mum
    current_candle = df.iloc[-1]  # Henüz tamamlanmamış mevcut mum
    new_signal = None
    
    # SHORT sinyal tespiti
    if not breakout_state['short_detected'] and last_candle['close'] > upper_limit:
        breakout_state['short_detected'] = True
        breakout_state['peak_price'] = last_candle['high']
        logging.info(f"[{symbol}] SHORT kırılım tespit edildi. Peak: {breakout_state['peak_price']:.2f}")
    
    elif breakout_state['short_detected']:
        breakout_state['peak_price'] = max(breakout_state['peak_price'], last_candle['high'])
        
        if last_candle['close'] < upper_limit:
            entry_price = last_candle['close']
            stop_loss = breakout_state['peak_price']
            
            if (stop_loss - entry_price) > 0:
                risk = stop_loss - entry_price
                take_profit_2r = entry_price - (2 * risk)
                
                new_signal = {
                    "type": "SHORT", 
                    "entry_price": entry_price, 
                    "stop_loss": stop_loss, 
                    "take_profit_2r": take_profit_2r,
                    "risk": risk,
                    "risk_reward_ratio": 2.0
                }
                logging.info(f"[{symbol}] SHORT sinyal oluşturuldu: Entry={entry_price:.2f}, SL={stop_loss:.2f}, TP={take_profit_2r:.2f}")
            
            breakout_state['short_detected'] = False
    
    # LONG sinyal tespiti
    if not breakout_state['long_detected'] and last_candle['close'] < lower_limit:
        breakout_state['long_detected'] = True
        breakout_state['trough_price'] = last_candle['low']
        logging.info(f"[{symbol}] LONG kırılım tespit edildi. Trough: {breakout_state['trough_price']:.2f}")
    
    elif breakout_state['long_detected']:
        breakout_state['trough_price'] = min(breakout_state['trough_price'], last_candle['low'])
        
        if last_candle['close'] > lower_limit:
            entry_price = last_candle['close']
            stop_loss = breakout_state['trough_price']
            
            if (entry_price - stop_loss) > 0:
                risk = entry_price - stop_loss
                take_profit_2r = entry_price + (2 * risk)
                
                new_signal = {
                    "type": "LONG", 
                    "entry_price": entry_price, 
                    "stop_loss": stop_loss, 
                    "take_profit_2r": take_profit_2r,
                    "risk": risk,
                    "risk_reward_ratio": 2.0
                }
                logging.info(f"[{symbol}] LONG sinyal oluşturuldu: Entry={entry_price:.2f}, SL={stop_loss:.2f}, TP={take_profit_2r:.2f}")
            
            breakout_state['long_detected'] = False
    
    return new_signal

def get_perpetual_price(exchange, symbol):
    """Perpetual piyasadan anlık fiyat al"""
    try:
        perp_symbol = convert_symbol_to_perpetual(symbol)
        ticker = exchange.fetch_ticker(perp_symbol)
        return ticker['last']
    except Exception as e:
        logging.error(f"[{symbol}] Perpetual fiyat alınamadı: {e}")
        return None

# --- ANA DÖNGÜ ---
def main():
    config = load_config()
    setup_logging()
    supabase = get_supabase_client(config)
    
    # Perpetual exchange kurulumu
    exchange = setup_perpetual_exchange()
    
    ny_timezone = pytz.timezone("America/New_York")
    
    # Breakout durumları
    breakout_states = {
        symbol: {
            'short_detected': False, 
            'long_detected': False, 
            'peak_price': 0, 
            'trough_price': float('inf')
        } for symbol in config['symbols']
    }
    
    logging.info("Perpetual Sinyal Üretici Başlatıldı.")
    logging.info(f"Takip edilen semboller: {config['symbols']}")
    
    while True:
        try:
            # Aktif işlemleri kontrol et
            response = supabase.table('signals').select('id, symbol, type, stop_loss, take_profit_2r, entry_price').eq('status', 'active').execute()
            active_trades = response.data if response.data else []
            active_symbols = [trade['symbol'] for trade in active_trades]
            
            # Aktif işlemlerin durumunu kontrol et
            for trade in active_trades:
                try:
                    # Perpetual fiyat al
                    last_price = get_perpetual_price(exchange, trade['symbol'])
                    if not last_price:
                        continue
                    
                    result = None
                    pnl_percent = 0
                    
                    # SHORT pozisyon kontrolü
                    if trade['type'] == 'SHORT':
                        if last_price >= trade['stop_loss']:
                            result = 'sl_hit'
                            pnl_percent = -((trade['stop_loss'] - trade['entry_price']) / trade['entry_price'] * 100)
                        elif last_price <= trade['take_profit_2r']:
                            result = 'tp_hit'
                            pnl_percent = ((trade['entry_price'] - trade['take_profit_2r']) / trade['entry_price'] * 100)
                    
                    # LONG pozisyon kontrolü
                    elif trade['type'] == 'LONG':
                        if last_price <= trade['stop_loss']:
                            result = 'sl_hit'
                            pnl_percent = -((trade['entry_price'] - trade['stop_loss']) / trade['entry_price'] * 100)
                        elif last_price >= trade['take_profit_2r']:
                            result = 'tp_hit'
                            pnl_percent = ((trade['take_profit_2r'] - trade['entry_price']) / trade['entry_price'] * 100)
                    
                    if result:
                        logging.info(f"[{trade['symbol']}] POZİSYON KAPANDI: {result} (PnL: {pnl_percent:.2f}%)")
                        supabase.table('signals').update({
                            'status': result,
                            'exit_price': last_price,
                            'pnl_percent': pnl_percent,
                            'closed_at': datetime.now(ny_timezone).isoformat()
                        }).eq('id', trade['id']).execute()
                        
                except Exception as e:
                    logging.error(f"[{trade['symbol']}] Aktif işlem takibinde hata: {e}")
            
            # Yeni sinyal taraması yapılacak semboller
            symbols_to_scan = [s for s in config['symbols'] if s not in active_symbols]
            
            if symbols_to_scan:
                current_ny_time = datetime.now(ny_timezone)
                
                # NY saat 04:00'dan sonra tarama yap
                if current_ny_time.hour >= 4:
                    for symbol in symbols_to_scan:
                        try:
                            # 4 saatlik seviyeleri al
                            upper_limit, lower_limit = get_ny_4h_levels(symbol, current_ny_time, exchange, ny_timezone)
                            
                            if not upper_limit or not lower_limit:
                                continue
                            
                            # Perpetual sembol formatına çevir
                            perp_symbol = convert_symbol_to_perpetual(symbol)
                            
                            # Son 10 adet 5 dakikalık mumu al (sinyal tespiti için)
                            ohlcv = exchange.fetch_ohlcv(perp_symbol, '5m', limit=10)
                            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                            
                            # Anlık fiyat bilgisini de al
                            current_price = get_perpetual_price(exchange, symbol)
                            if current_price:
                                logging.debug(f"[{symbol}] Tarama - 5m Kapanış: {df.iloc[-2]['close']:.2f}, Anlık: {current_price:.2f}, Upper: {upper_limit:.2f}, Lower: {lower_limit:.2f}")
                            
                            # Yeni sinyal ara (5 dakikalık grafik verisi ile)
                            new_signal = find_new_signal(df, upper_limit, lower_limit, breakout_states[symbol], symbol)
                            
                            if new_signal:
                                signal_data = {
                                    **new_signal, 
                                    'symbol': symbol, 
                                    'status': 'active', 
                                    'notified': False,
                                    'created_at': datetime.now(ny_timezone).isoformat(),
                                    'upper_limit': upper_limit,
                                    'lower_limit': lower_limit
                                }
                                
                                supabase.table('signals').insert(signal_data).execute()
                                logging.info(f"[{symbol}] YENİ SİNYAL KAYIT EDİLDİ: {new_signal['type']} @ {new_signal['entry_price']:.2f}")
                                
                        except Exception as e:
                            logging.error(f"[{symbol}] Sinyal taramasında hata: {e}")
                else:
                    logging.debug(f"NY saati {current_ny_time.hour}:00 - Henüz tarama zamanı değil (04:00'dan itibaren)")
            
            # Döngü aralığı
            time.sleep(config['loop_intervals']['signal_generator'])
            
        except Exception as e:
            logging.critical(f"Ana döngüde kritik hata: {e}", exc_info=True)
            time.sleep(60)

if __name__ == "__main__":
    main()