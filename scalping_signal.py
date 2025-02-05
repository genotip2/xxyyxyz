import os
import requests
import pandas as pd
import pandas_ta as ta
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
def fetch_ohlcv(symbol, interval):
    # Implementasi data source disini (contoh: yfinance, CCXT, dll)
    # Return DataFrame dengan kolom: open, high, low, close, volume
    # Contoh dummy data untuk demonstrasi
    return pd.DataFrame({
        'close': [50000 + i*100 for i in range(100)],
        'open': [49500 + i*100 for i in range(100)],
        'high': [50500 + i*100 for i in range(100)],
        'low': [49000 + i*100 for i in range(100)],
        'volume': [1000 + i*10 for i in range(100)]
    })

def calculate_indicators(df):
    df['EMA9'] = ta.ema(df['close'], length=9)
    df['EMA21'] = ta.ema(df['close'], length=21)
    df['RSI'] = ta.rsi(df['close'], length=14)
    macd = ta.macd(df['close'])
    df = pd.concat([df, macd], axis=1)
    bb = ta.bbands(df['close'])
    df = pd.concat([df, bb], axis=1)
    df['ADX'] = ta.adx(df['high'], df['low'], df['close'], length=14)['ADX_14']
    df['OBV'] = ta.obv(df['close'], df['volume'])
    return df

def analyze_pair(symbol):
    try:
        # Ambil data untuk 15m dan 1h
        df_m15 = fetch_ohlcv(symbol, '15m')
        df_h1 = fetch_ohlcv(symbol, '1h')
        
        # Hitung indikator
        df_m15 = calculate_indicators(df_m15)
        df_h1 = calculate_indicators(df_h1)
        
        # Ambil nilai terakhir
        return {
            'ema9_m15': df_m15['EMA9'].iloc[-1],
            'ema21_m15': df_m15['EMA21'].iloc[-1],
            'rsi_m15': df_m15['RSI'].iloc[-1],
            'macd_m15': df_m15['MACD_12_26_9'].iloc[-1],
            'macd_signal_m15': df_m15['MACDs_12_26_9'].iloc[-1],
            'bb_lower_m15': df_m15['BBL_20_2.0'].iloc[-1],
            'bb_upper_m15': df_m15['BBU_20_2.0'].iloc[-1],
            'close_price_m15': df_m15['close'].iloc[-1],
            'adx_m15': df_m15['ADX'].iloc[-1],
            'obv_m15': df_m15['OBV'].iloc[-1],
            'ema9_h1': df_h1['EMA9'].iloc[-1],
            'ema21_h1': df_h1['EMA21'].iloc[-1],
            'rsi_h1': df_h1['RSI'].iloc[-1],
            'macd_h1': df_h1['MACD_12_26_9'].iloc[-1],
            'macd_signal_h1': df_h1['MACDs_12_26_9'].iloc[-1],
            'bb_lower_h1': df_h1['BBL_20_2.0'].iloc[-1],
            'bb_upper_h1': df_h1['BBU_20_2.0'].iloc[-1],
            'close_price_h1': df_h1['close'].iloc[-1],
            'adx_h1': df_h1['ADX'].iloc[-1],
            'obv_h1': df_h1['OBV'].iloc[-1]
        }
    except Exception as e:
        print(f"⚠️ Error analisis {symbol}: {str(e)}")
        return None

# ==============================
# FUNGSI TRADING (TETAP SAMA)
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

def send_telegram_alert(signal_type, pair, price, data):
    emoji = {'BUY': '🚀', 'SELL': '⚠️', 'TAKE PROFIT': '✅', 'STOP LOSS': '🛑'}.get(signal_type, 'ℹ️')
    message = f"{emoji} {signal_type}\n💱 {pair[:-4]}/USDT\n💲 Price: ${price:.8f}"
    
    if signal_type == 'BUY':
        ACTIVE_BUYS[pair] = {'price': price, 'time': datetime.now()}
        message += f"\n🔍 RSI: {data['rsi_m15']:.1f}"
    elif signal_type in ['TAKE PROFIT', 'STOP LOSS', 'SELL']:
        entry = ACTIVE_BUYS.get(pair, {})
        if entry:
            profit = ((price - entry['price'])/entry['price'])*100
            duration = str(datetime.now() - entry['time']).split('.')[0]
            message += f"\n💲 Entry: ${entry['price']:.8f}"
            message += f"\n💰 {'Profit' if profit > 0 else 'Loss'}: {profit:+.2f}%"
            message += f"\n🕒 Hold Duration: {duration}"
            if signal_type in ['STOP LOSS', 'SELL']:
                del ACTIVE_BUYS[pair]
    
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'Markdown'}
    )
    save_active_buys_to_json()

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
                send_telegram_alert(signal, pair, price, data)
                
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
