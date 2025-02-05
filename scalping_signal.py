import os
import requests
import pandas as pd
import numpy as np
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
                'price': data['close_price_m15'],
                'time': datetime.fromisoformat(data['time'])
            } 
            for pair, data in loaded.items()
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
    except Exception as e:
        print(f"❌ Gagal menyimpan: {str(e)}")

def get_binance_top_pairs():
    url = "https://api.coingecko.com/api/v3/exchanges/binance/tickers"
    params = {'include_exchange_logo': 'false', 'order': 'volume_desc'}
    
    try:
        response = requests.get(url, params=params)
        data = response.json()
        usdt_pairs = [t for t in data['tickers'] if t['target'] == 'USDT']
        sorted_pairs = sorted(usdt_pairs, 
                            key=lambda x: x['converted_volume']['usd'], 
                            reverse=True)[:50]
        return [f"{p['base']}USDT" for p in sorted_pairs]
    
    except Exception as e:
        print(f"❌ Error fetching data: {e}")
        return []

# ==============================
# FUNGSI ANALISIS DENGAN PANDAS
# ==============================
def fetch_klines(symbol, interval, limit=100):
    url = "https://api.binance.com/api/v3/klines"
    params = {
        'symbol': symbol,
        'interval': interval,
        'limit': limit
    }
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        print(f"Failed to fetch klines for {symbol} {interval}: {e}")
        return None
    
    columns = ['Open time', 'Open', 'High', 'Low', 'Close', 'Volume',
               'Close time', 'Quote asset volume', 'Number of trades',
               'Taker buy base asset volume', 'Taker buy quote asset volume',
               'Ignore']
    df = pd.DataFrame(data, columns=columns)
    
    numeric_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
    df[numeric_cols] = df[numeric_cols].apply(pd.to_numeric, errors='coerce')
    df['Open time'] = pd.to_datetime(df['Open time'], unit='ms')
    df.set_index('Open time', inplace=True)
    return df

def calculate_adx(df, period=14):
    df['TR'] = np.maximum(df['High'] - df['Low'], 
                         np.maximum(abs(df['High'] - df['Close'].shift()), 
                                   abs(df['Low'] - df['Close'].shift())))
    df['+DM'] = np.where((df['High'] - df['High'].shift()) > (df['Low'].shift() - df['Low']), 
                        np.maximum(df['High'] - df['High'].shift(), 0), 0)
    df['-DM'] = np.where((df['Low'].shift() - df['Low']) > (df['High'] - df['High'].shift()), 
                        np.maximum(df['Low'].shift() - df['Low'], 0), 0)
    
    df['TR_smooth'] = df['TR'].rolling(period).sum()
    df['+DM_smooth'] = df['+DM'].rolling(period).sum()
    df['-DM_smooth'] = df['-DM'].rolling(period).sum()
    
    df['+DI'] = (df['+DM_smooth'] / df['TR_smooth']) * 100
    df['-DI'] = (df['-DM_smooth'] / df['TR_smooth']) * 100
    
    df['DX'] = (np.abs(df['+DI'] - df['-DI']) / (df['+DI'] + df['-DI'])) * 100
    df['ADX'] = df['DX'].rolling(period).mean()
    return df

def compute_indicators(df):
    # Moving Averages
    df['EMA9'] = df['Close'].ewm(span=9, adjust=False).mean()
    df['EMA21'] = df['Close'].ewm(span=21, adjust=False).mean()
    
    # RSI
    delta = df['Close'].diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / avg_loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # MACD
    ema12 = df['Close'].ewm(span=12, adjust=False).mean()
    ema26 = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = ema12 - ema26
    df['MACD_signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    
    # Bollinger Bands
    sma20 = df['Close'].rolling(20).mean()
    std20 = df['Close'].rolling(20).std()
    df['BB_upper'] = sma20 + 2 * std20
    df['BB_lower'] = sma20 - 2 * std20
    
    # ADX
    df = calculate_adx(df)
    
    # OBV
    df['OBV'] = (np.sign(df['Close'].diff()) * df['Volume']).fillna(0).cumsum()
    df['OBV_slope'] = df['OBV'].diff()
    
    return df

def get_candle_recommendation(data):
    if data['Close'] > data['Open']:
        return 'BUY'
    elif data['Close'] < data['Open']:
        return 'SELL'
    return 'NEUTRAL'

def analyze_pair(symbol):
    try:
        df_15m = fetch_klines(symbol, '15m')
        df_1h = fetch_klines(symbol, '1h')
        if df_15m is None or df_1h is None:
            return None
            
        df_15m = compute_indicators(df_15m)
        df_1h = compute_indicators(df_1h)
        
        latest_15m = df_15m.iloc[-1]
        latest_1h = df_1h.iloc[-1]
        
        return {
            'ema9_m15': latest_15m['EMA9'],
            'ema21_m15': latest_15m['EMA21'],
            'rsi_m15': latest_15m['RSI'],
            'macd_m15': latest_15m['MACD'],
            'macd_signal_m15': latest_15m['MACD_signal'],
            'bb_lower_m15': latest_15m['BB_lower'],
            'bb_upper_m15': latest_15m['BB_upper'],
            'close_price_m15': latest_15m['Close'],
            'adx_m15': latest_15m['ADX'],
            'obv_m15': latest_15m['OBV_slope'],
            'candle_m15': get_candle_recommendation(latest_15m),
            
            'ema9_h1': latest_1h['EMA9'],
            'ema21_h1': latest_1h['EMA21'],
            'rsi_h1': latest_1h['RSI'],
            'macd_h1': latest_1h['MACD'],
            'macd_signal_h1': latest_1h['MACD_signal'],
            'bb_lower_h1': latest_1h['BB_lower'],
            'bb_upper_h1': latest_1h['BB_upper'],
            'close_price_h1': latest_1h['Close'],
            'adx_h1': latest_1h['ADX'],
            'obv_h1': latest_1h['OBV_slope'],
            'candle_h1': get_candle_recommendation(latest_1h)
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
        data['obv_h1'] > 0 and
        ("BUY" in data['candle_m15'] or "STRONG_BUY" in data['candle_m15']) and
        ("BUY" in data['candle_h1'] or "STRONG_BUY" in data['candle_h1']) and
        pair not in ACTIVE_BUYS
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
        ("SELL" in data['candle_m15'] or "STRONG_SELL" in data['candle_m15']) and
        ("SELL" in data['candle_h1'] or "STRONG_SELL" in data['candle_h1']) and
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
    message = ""
    
    emoji = {
        'BUY': '🚀', 
        'SELL': '⚠️', 
        'TAKE PROFIT': '✅', 
        'STOP LOSS': '🛑'
    }.get(signal_type, 'ℹ️')

    base_msg = f"{emoji} **{signal_type}**\n💱 {display_pair}\n💲 Price: ${price:.8f}\n"
    
    if signal_type == 'BUY':
        message = f"{base_msg}🔍 RSI M15: {data['rsi_m15']:.1f}\n"
        ACTIVE_BUYS[pair] = {'price': price, 'time': datetime.now()}
    elif signal_type in ['TAKE PROFIT', 'STOP LOSS', 'SELL']:
        entry = ACTIVE_BUYS.get(pair)
        if entry:
            profit = ((price - entry['price'])/entry['price'])*100
            duration = str(datetime.now() - entry['time']).split('.')[0]
            message = f"{base_msg}💲 Entry: ${entry['price']:.8f}\n"
            message += f"💰 {'Profit' if profit > 0 else 'Loss'}: {profit:+.2f}%\n"
            message += f"🕒 Hold Duration: {duration}"
            if signal_type in ['STOP LOSS', 'SELL']:
                del ACTIVE_BUYS[pair]

    if message:
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
