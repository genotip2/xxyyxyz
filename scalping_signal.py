import os
import requests
import yfinance as yf
import pandas_ta as ta
import pandas as pd
from datetime import datetime, timedelta
import json

# ==============================
# KONFIGURASI
# ==============================
TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
ACTIVE_BUYS = {}
BUY_SCORE_THRESHOLD = 5
SELL_SCORE_THRESHOLD = 4
FILE_PATH = 'active_buys.json'

# Inisialisasi file JSON
if not os.path.exists(FILE_PATH):
    with open(FILE_PATH, 'w') as f:
        json.dump({}, f)
else:
    with open(FILE_PATH, 'r') as f:
        loaded = json.load(f)
    ACTIVE_BUYS = {
        pair: {
            'price': data['price'],
            'time': datetime.fromisoformat(data['time'])
        } for pair, data in loaded.items()
    }

# ==============================
# FUNGSI UTILITAS
# ==============================
def save_active_buys_to_json():
    try:
        to_save = {}
        for pair, data in ACTIVE_BUYS.items():
            to_save[pair] = {
                'price': data['price'],
                'time': data['time'].isoformat()
            }
        with open(FILE_PATH, 'w') as f:
            json.dump(to_save, f, indent=4)
        print("✅ Berhasil menyimpan active_buys.json")
    except Exception as e:
        print(f"❌ Gagal menyimpan: {str(e)}")

def get_binance_top_pairs():
    url = "https://api.coingecko.com/api/v3/exchanges/binance/tickers"
    params = {'include_exchange_logo': 'false', 'order': 'volume_desc'}
    
    try:
        response = requests.get(url, params=params)
        data = response.json()
        usdt_pairs = [t for t in data['tickers'] if t['target'] == 'USDT']
        sorted_pairs = sorted(usdt_pairs, key=lambda x: x['converted_volume']['usd'], reverse=True)[:50]
        return [f"{p['base']}USDT" for p in sorted_pairs]
    except Exception as e:
        print(f"❌ Error fetching data: {e}")
        return []

# ==============================
# FUNGSI ANALISIS DENGAN PANDAS
# ==============================
def analyze_pair(symbol):
    try:
        # Konversi simbol untuk Yahoo Finance
        yf_symbol = symbol.replace('USDT', '-USD')
        
        # Ambil data 15 menit
        data_m15 = yf.download(yf_symbol, period='7d', interval='15m')
        if data_m15.empty:
            return None
            
        # Hitung indikator untuk 15m
        data_m15.ta.ema(length=9, append=True, col_names={'EMA9'})
        data_m15.ta.ema(length=21, append=True, col_names={'EMA21'})
        data_m15.ta.rsi(append=True, col_names={'RSI'})
        data_m15.ta.macd(append=True, col_names={'MACD', 'MACD_signal', 'MACD_hist'})
        data_m15.ta.bbands(append=True, col_names={'BB_lower', 'BB_mid', 'BB_upper'})
        data_m15.ta.adx(append=True, col_names={'ADX'})
        data_m15.ta.obv(append=True, col_names={'OBV'})
        
        latest_m15 = data_m15.iloc[-1]
        
        # Ambil data 1 jam
        data_h1 = yf.download(yf_symbol, period='30d', interval='1h')
        if data_h1.empty:
            return None
            
        # Hitung indikator untuk 1h
        data_h1.ta.ema(length=9, append=True, col_names={'EMA9'})
        data_h1.ta.ema(length=21, append=True, col_names={'EMA21'})
        data_h1.ta.rsi(append=True, col_names={'RSI'})
        data_h1.ta.macd(append=True, col_names={'MACD', 'MACD_signal', 'MACD_hist'})
        data_h1.ta.bbands(append=True, col_names={'BB_lower', 'BB_mid', 'BB_upper'})
        data_h1.ta.adx(append=True, col_names={'ADX'})
        data_h1.ta.obv(append=True, col_names={'OBV'})
        
        latest_h1 = data_h1.iloc[-1]
        
        return {
            'ema9_m15': latest_m15['EMA9'],
            'ema21_m15': latest_m15['EMA21'],
            'rsi_m15': latest_m15['RSI'],
            'macd_m15': latest_m15['MACD'],
            'macd_signal_m15': latest_m15['MACD_signal'],
            'bb_lower_m15': latest_m15['BB_lower'],
            'bb_upper_m15': latest_m15['BB_upper'],
            'close_price_m15': latest_m15['Close'],
            'adx_m15': latest_m15['ADX'],
            'obv_m15': latest_m15['OBV'],
            
            'ema9_h1': latest_h1['EMA9'],
            'ema21_h1': latest_h1['EMA21'],
            'rsi_h1': latest_h1['RSI'],
            'macd_h1': latest_h1['MACD'],
            'macd_signal_h1': latest_h1['MACD_signal'],
            'bb_lower_h1': latest_h1['BB_lower'],
            'bb_upper_h1': latest_h1['BB_upper'],
            'close_price_h1': latest_h1['Close'],
            'adx_h1': latest_h1['ADX'],
            'obv_h1': latest_h1['OBV']
        }
    except Exception as e:
        print(f"⚠️ Error analisis {symbol}: {str(e)}")
        return None

# ==============================
# FUNGSI TRADING (TIDAK BERUBAH)
# ==============================
def generate_signal(pair, data):
    price = data['close_price_m15']
    
    buy_signal = (
        data['ema9_m15'] > data['ema21_m15'] and
        data['ema9_h1'] > data['ema21_h1'] and
        data['rsi_m15'] < 30 and
        data['rsi_h1'] < 50 and
        data['macd_m15'] > data['macd_signal_m15'] and
        data['macd_h1'] > data['macd_signal_h1'] and
        data['close_price_m15'] <= data['bb_lower_m15'] and
        data['close_price_h1'] <= data['bb_lower_h1'] and
        data['adx_m15'] > 25 and
        data['adx_h1'] > 25 and
        data['obv_m15'] > 0 and
        data['obv_h1'] > 0
    )
    
    sell_signal = (
        data['ema9_m15'] < data['ema21_m15'] and
        data['ema9_h1'] < data['ema21_h1'] and
        data['rsi_m15'] > 70 and
        data['rsi_h1'] > 50 and
        data['macd_m15'] < data['macd_signal_m15'] and
        data['macd_h1'] < data['macd_signal_h1'] and
        data['close_price_m15'] >= data['bb_upper_m15'] and
        data['close_price_h1'] >= data['bb_upper_h1'] and
        data['adx_m15'] > 25 and
        data['adx_h1'] > 25 and
        data['obv_m15'] < 0 and
        data['obv_h1'] < 0 and
        pair in ACTIVE_BUYS
    )
    
    take_profit = pair in ACTIVE_BUYS and price > ACTIVE_BUYS[pair]['price'] * 1.05
    stop_loss = pair in ACTIVE_BUYS and price < ACTIVE_BUYS[pair]['price'] * 0.98

    if buy_signal:
        return 'BUY', price
    elif take_profit:
        return 'TAKE PROFIT', price
    elif stop_loss:
        return 'STOP LOSS', price
    elif sell_signal:
        return 'SELL', ACTIVE_BUYS[pair]['price']
    return None, None

def send_telegram_alert(signal_type, pair, price, data, buy_price=None):
    display_pair = f"{pair[:-4]}/USDT"
    emoji = {'BUY': '🚀', 'SELL': '⚠️', 'TAKE PROFIT': '✅', 'STOP LOSS': '🛑'}.get(signal_type, 'ℹ️')
    message = f"{emoji} {signal_type}\n💱 {display_pair}\n💲 Price: ${price:.8f}\n"
    
    if signal_type == 'BUY':
        message += f"🔍 RSI: {data['rsi_m15']:.1f}\n"
        ACTIVE_BUYS[pair] = {'price': price, 'time': datetime.now()}
    
    elif signal_type in ['TAKE PROFIT', 'STOP LOSS', 'SELL']:
        entry = ACTIVE_BUYS.get(pair)
        if entry:
            profit = ((price - entry['price'])/entry['price'])*100
            duration = str(datetime.now() - entry['time']).split('.')[0]
            message += f"💲 Entry: ${entry['price']:.8f}\n"
            message += f"💰 {'Profit' if profit > 0 else 'Loss'}: {profit:+.2f}%\n"
            message += f"🕒 Hold Duration: {duration}"
            
            if signal_type in ['STOP LOSS', 'SELL']:
                del ACTIVE_BUYS[pair]
    
    print(f"📢 Mengirim alert: {message}")
    save_active_buys_to_json()
    
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'Markdown'}
    )

# ==============================
# FUNGSI UTAMA
# ==============================
def main():
    pairs = get_binance_top_pairs()
    print(f"🔍 Memulai analisis {len(pairs)} pair - {datetime.now().strftime('%d/%m %H:%M')}")
    
    for pair in pairs:
        try:
            data = analyze_pair(pair)
            if not data:
                continue
                
            signal, price = generate_signal(pair, data)
            if signal:
                send_telegram_alert(signal, pair, data['close_price_m15'], data)
                
            # Auto close position
            if pair in ACTIVE_BUYS:
                position = ACTIVE_BUYS[pair]
                duration = datetime.now() - position['time']
                profit = (data['close_price_m15'] - position['price'])/position['price']*100
                
                if duration > timedelta(hours=24) or abs(profit) > 8:
                    send_telegram_alert('SELL', pair, data['close_price_m15'], data)
                    
        except Exception as e:
            print(f"⚠️ Error di {pair}: {str(e)}")
            continue

if __name__ == "__main__":
    main()
