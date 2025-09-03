import ccxt
import pandas as pd
from datetime import datetime
import json
import pytz

def load_signals_from_file(filename='sinyal-eth.json'):
    """
    Belirtilen JSON dosyasından sinyalleri yükler.
    """
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            signals = json.load(f)
            if not signals.get('short_sinyaller') and not signals.get('long_sinyaller'):
                print(f"'{filename}' dosyasında kontrol edilecek sinyal bulunamadı.")
                return None
            print(f"✅ '{filename}' dosyasından sinyaller başarıyla yüklendi.")
            return signals
    except FileNotFoundError:
        print(f"HATA: '{filename}' dosyası bulunamadı.")
        return None
    except json.JSONDecodeError:
        print(f"HATA: '{filename}' dosyasının formatı bozuk (JSON değil).")
        return None
    except Exception as e:
        print(f"Dosya okunurken bir hata oluştu: {e}")
        return None

def run_trading_simulation(signals, initial_balance, risk_percent):
    """
    Verilen sinyalleri, bakiye ve risk yönetimi kurallarıyla simüle eder.
    """
    if not signals:
        return

    exchange = ccxt.binance()
    all_trades = []

    for trade in signals.get('short_sinyaller', []):
        trade['type'] = 'SHORT'
        all_trades.append(trade)

    for trade in signals.get('long_sinyaller', []):
        trade['type'] = 'LONG'
        all_trades.append(trade)
    
    if not all_trades:
        print("İşlem listesi boş, simülasyon başlatılamıyor.")
        return
        
    # Bakiye hesaplamasının doğru olması için işlemleri zamana göre sırala
    all_trades.sort(key=lambda x: x['entry_time'])
    
    print("\n--- Ticaret Simülasyonu Başlatılıyor ---")
    print(f"Başlangıç Bakiyesi: ${initial_balance:.2f}")
    print(f"İşlem Başına Risk: %{risk_percent}")
    print("-" * 40)

    # Simülasyon değişkenleri
    current_balance = float(initial_balance)
    win_count = 0
    loss_count = 0
    open_trades = 0

    for i, trade in enumerate(all_trades, 1):
        entry_time_str = trade['entry_time']
        stop_loss = trade['stop_loss']
        take_profit = trade['take_profit_2R']
        
        try:
            entry_time_dt = datetime.strptime(entry_time_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=pytz.utc)
            since_timestamp = int(entry_time_dt.timestamp() * 1000)
            ohlcv = exchange.fetch_ohlcv('BTC/USDT', '30m', since=since_timestamp)

            status = "Halen Açık"
            if not ohlcv:
                open_trades += 1
                continue

            for candle in ohlcv:
                high_price, low_price = candle[2], candle[3]
                if trade['type'] == 'SHORT':
                    if high_price >= stop_loss:
                        status = "Stop Oldu"
                        break
                    if low_price <= take_profit:
                        status = "TP Oldu"
                        break
                elif trade['type'] == 'LONG':
                    if low_price <= stop_loss:
                        status = "Stop Oldu"
                        break
                    if high_price >= take_profit:
                        status = "TP Oldu"
                        break
            
            # Bakiye hesaplaması
            risk_amount = current_balance * (risk_percent / 100.0)
            
            print(f"{i}. İşlem | {trade['entry_time']} | {trade['type']:<5} | Bakiye: ${current_balance:8.2f} | Sonuç: {status}")

            if status == "TP Oldu":
                profit = risk_amount * 2  # 2R kazanç
                current_balance += profit
                win_count += 1
                print(f"    -> KAZANÇ: +${profit:.2f} | Yeni Bakiye: ${current_balance:.2f}")
            elif status == "Stop Oldu":
                loss = risk_amount # -1R kayıp
                current_balance -= loss
                loss_count += 1
                print(f"    -> KAYIP : -${loss:.2f} | Yeni Bakiye: ${current_balance:.2f}")
            else:
                open_trades += 1

        except Exception as e:
            print(f"  -> Bu sinyal işlenirken bir hata oluştu: {e}")

    # --- FİNAL RAPORU ---
    print("\n" + "="*40)
    print("--- Simülasyon Final Raporu ---")
    print(f"Başlangıç Bakiyesi : ${initial_balance:.2f}")
    print(f"Bitiş Bakiyesi     : ${current_balance:.2f}")
    
    net_profit = current_balance - initial_balance
    net_profit_percent = (net_profit / initial_balance) * 100
    
    print(f"Net Kar/Zarar      : ${net_profit:.2f} ({net_profit_percent:+.2f}%)")
    print("-" * 40)
    
    total_closed_trades = win_count + loss_count
    win_rate = (win_count / total_closed_trades * 100) if total_closed_trades > 0 else 0
    
    print(f"Toplam Kapalı İşlem: {total_closed_trades}")
    print(f"Kazanan İşlem      : {win_count}")
    print(f"Kaybeden İşlem     : {loss_count}")
    print(f"Kazanma Oranı      : {win_rate:.2f}%")
    print(f"Halen Açık İşlem   : {open_trades}")
    print("="*40)

# --- ANA KOD BLOGU ---
if __name__ == "__main__":
    # --- SİMÜLASYON PARAMETRELERİ ---
    INITIAL_BALANCE = 100.0
    RISK_PER_TRADE_PERCENT = 10.0

    signals_to_check = load_signals_from_file('sinyal.json')
    
    if signals_to_check:
        run_trading_simulation(signals_to_check, INITIAL_BALANCE, RISK_PER_TRADE_PERCENT)