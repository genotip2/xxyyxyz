import os
import requests
import pandas as pd
import json
from datetime import datetime, timedelta

# ==============================
# KONFIGURASI
# ==============================
TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
ACTIVE_BUYS = {}
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
            }
            for pair, data in loaded.items()
        }

# ==============================
# FUNGSI UTILITAS
# ==============================
def save_active_buys_to_json():
    try:
        to_save = {pair: {'price': data['price'], 'time': data['time'].isoformat()} for pair, data in ACTIVE_BUYS.items()}
        with open(FILE_PATH, 'w') as f:
            json.dump(to_save, f, indent=4)
        print("✅ Berhasil menyimpan active_buys.json")
    except Exception as e:
        print(f"❌ Gagal menyimpan: {str(e)}")


def get_binance_top_pairs():
    """Ambil 50 pair teratas berdasarkan volume trading dari CoinGecko"""
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


def fetch_price_data(symbol):
def get_binance_top_pairs():
    """Ambil 50 pair teratas berdasarkan volume trading"""
    url = "https://api.coingecko.com/api/v3/exchanges/binance/tickers"
    params = {'include_exchange_logo': 'false', 'order': 'volume_desc'}
    
    try:
        response = requests.get(url, params=params)
        data = response.json()
        
        if 'tickers' not in data:
            print("❌ Tidak ada data ticker ditemukan.")
            return []

        usdt_pairs = [t for t in data['tickers'] if t['target'] == 'USDT']
        sorted_pairs = sorted(usdt_pairs, 
                            key=lambda x: x['converted_volume']['usd'], 
                            reverse=True)[:50]
        
        # Pastikan kita menangani 'prices' dan key lainnya dengan aman
        pairs = []
        for pair in sorted_pairs:
            try:
                pair_symbol = f"{pair['base']}USDT"
                # Pastikan harga ada di data ticker
                if 'last' in pair:
                    pairs.append(pair_symbol)
            except KeyError as e:
                print(f"⚠️ Data tidak lengkap untuk pair: {pair.get('base', 'Unknown')}, error: {e}")

        return pairs
    
    except Exception as e:
        print(f"❌ Error fetching data: {e}")
        return []

# ==============================
# FUNGSI ANALISIS
# ==============================
def calculate_indicators(df):
    """Menghitung indikator teknikal"""
    df['ema9'] = df['close'].ewm(span=9, adjust=False).mean()
    df['ema21'] = df['close'].ewm(span=21, adjust=False).mean()

    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))

    df['macd'] = df['ema9'] - df['ema21']
    df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()

    df['bb_middle'] = df['close'].rolling(window=20).mean()
    df['bb_upper'] = df['bb_middle'] + 2 * df['close'].rolling(window=20).std()
    df['bb_lower'] = df['bb_middle'] - 2 * df['close'].rolling(window=20).std()

    df['adx'] = (df['macd'] - df['macd'].shift(1)).abs().rolling(14).mean()

    df['obv'] = (df['close'].diff() > 0).astype(int).cumsum()

    return df


def analyze_pair(symbol):
    """Analisis indikator teknikal berdasarkan data harga"""
    price_data = fetch_price_data(symbol)
    if price_data is None:
        return None

    df = pd.DataFrame({'close': price_data})
    df = calculate_indicators(df)

    return df.iloc[-1].to_dict()


# ==============================
# FUNGSI TRADING
# ==============================
def generate_signal(pair, data):
    """Generate sinyal trading berdasarkan indikator"""
    buy_signal = (
        data['ema9'] > data['ema21'] and
        data['rsi'] < 30 and
        data['macd'] > data['macd_signal'] and
        data['close'] <= data['bb_lower'] and
        data['adx'] > 25 and
        data['obv'] > 0 and
        pair not in ACTIVE_BUYS
    )

    sell_signal = (
        data['ema9'] < data['ema21'] and
        data['rsi'] > 70 and
        data['macd'] < data['macd_signal'] and
        data['close'] >= data['bb_upper'] and
        data['adx'] > 25 and
        data['obv'] < 0 and
        pair in ACTIVE_BUYS
    )

    take_profit = pair in ACTIVE_BUYS and data['close'] > ACTIVE_BUYS[pair]['price'] * 1.05
    stop_loss = pair in ACTIVE_BUYS and data['close'] < ACTIVE_BUYS[pair]['price'] * 0.98

    if buy_signal:
        return 'BUY', data['close']
    elif take_profit:
        return 'TAKE PROFIT', data['close']
    elif stop_loss:
        return 'STOP LOSS', data['close']
    elif sell_signal:
        return 'SELL', ACTIVE_BUYS[pair]['price']

    return None, None


def send_telegram_alert(signal_type, pair, price):
    """Mengirim notifikasi ke Telegram"""
    message = f"📢 **{signal_type}**\n💱 {pair}\n💲 Price: ${price:.8f}\n"

    if signal_type == 'BUY':
        ACTIVE_BUYS[pair] = {'price': price, 'time': datetime.now()}

    elif signal_type in ['TAKE PROFIT', 'STOP LOSS', 'SELL']:
        del ACTIVE_BUYS[pair]

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
        data = analyze_pair(pair)
        if data:
            signal, price = generate_signal(pair, data)
            if signal:
                send_telegram_alert(signal, pair, price)


if __name__ == "__main__":
    main()
