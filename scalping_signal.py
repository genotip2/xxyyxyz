import os
import requests
from datetime import datetime, timedelta
import json
import numpy as np

# ==============================
# KONFIGURASI
# ==============================
TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
ACTIVE_BUYS = {}
ACTIVE_BUYS_FILE = 'active_buys.json'
MEAN_WINDOW = 10  # Kurangi jendela waktu untuk menghindari masalah data tidak cukup
STD_DEV_THRESHOLD = 2  # Ambang standar deviasi untuk beli
PROFIT_TARGET_PERCENTAGE = 5  # 5% target profit
STOP_LOSS_PERCENTAGE = 2  # 2% stop loss target
MAX_HOLD_DURATION_HOUR = 24  # Maksimal durasi pegangan dalam jam

# Inisialisasi file JSON dengan handling datetime
if not os.path.exists(ACTIVE_BUYS_FILE):
    with open(ACTIVE_BUYS_FILE, 'w') as f:
        json.dump({}, f)
else:
    with open(ACTIVE_BUYS_FILE, 'r') as f:
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
    """Simpan data dengan konversi datetime ke string"""
    try:
        to_save = {}
        for pair, data in ACTIVE_BUYS.items():
            to_save[pair] = {
                'price': data['price'],
                'time': data['time'].isoformat()
            }

        with open(ACTIVE_BUYS_FILE, 'w') as f:
            json.dump(to_save, f, indent=4)

        print("✅ Berhasil menyimpan active_buys.json")
    except Exception as e:
        print(f"❌ Gagal menyimpan: {str(e)}")

def get_binance_top_pairs():
    """Ambil 50 pair teratas berdasarkan volume trading"""
    url = "https://api.coingecko.com/api/v3/exchanges/binance/tickers"
    params = {'include_exchange_logo': 'false', 'order': 'volume_desc'}

    try:
        response = requests.get(url, params=params)
        data = response.json()
        usdt_pairs = [t for t in data['tickers'] if t['target'] == 'USDT']
        sorted_pairs = sorted(usdt_pairs,
                            key=lambda x: x['converted_volume']['usd'],
                            reverse=True)[:100]
        return [f"{p['base']}USDT" for p in sorted_pairs]

    except Exception as e:
        print(f"❌ Error fetching data: {e}")
        return []

# ==============================
# FUNGSI ANALISIS
# ==============================
def analyze_pair(symbol):
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1h&limit={MEAN_WINDOW}"
        response = requests.get(url)
        data = response.json()

        # Print data yang diterima dari API untuk debugging
        print(f"Data dari API untuk {symbol}: {data}")

        if isinstance(data, dict) and 'msg' in data:
            print(f"⚠️ Error dari API untuk {symbol}: {data['msg']}")
            return None

        if len(data) < MEAN_WINDOW:
            print(f"⚠️ Tidak cukup data untuk {symbol}")
            return None

        closes = np.array([float(c[4]) for c in data])
        mean = np.mean(closes)
        std_dev = np.std(closes)
        current_price = closes[-1]

        return {
            'current_price': current_price,
            'mean': mean,
            'std_dev': std_dev
        }

    except Exception as e:
        print(f"⚠️ Error analisis {symbol}: {str(e)}")
        return None

# ==============================
# FUNGSI TRADING
# ==============================
def generate_signal(pair, data):
    """Generate trading signal"""
    current_price = data['current_price']
    mean = data['mean']
    std_dev = data['std_dev']
    display_pair = f"{pair[:-4]}/USDT"

    print(f"{display_pair} - Price: {current_price:.8f} | Mean: {mean:.8f} | Std Dev: {std_dev:.8f}")

    buy_signal = current_price < (mean - STD_DEV_THRESHOLD * std_dev) and pair not in ACTIVE_BUYS
    sell_signal = current_price >= (mean + std_dev) and pair in ACTIVE_BUYS
    take_profit = pair in ACTIVE_BUYS and current_price >= ACTIVE_BUYS[pair]['price'] * (1 + PROFIT_TARGET_PERCENTAGE / 100)
    stop_loss = pair in ACTIVE_BUYS and current_price <= ACTIVE_BUYS[pair]['price'] * (1 - STOP_LOSS_PERCENTAGE / 100)
    expired = pair in ACTIVE_BUYS and (datetime.now() - ACTIVE_BUYS[pair]['time']) > timedelta(hours=MAX_HOLD_DURATION_HOUR)

    if buy_signal:
        return 'BUY', current_price
    elif take_profit:
        return 'TAKE PROFIT', current_price
    elif stop_loss:
        return 'STOP LOSS', current_price
    elif sell_signal:
        return 'SELL', ACTIVE_BUYS[pair]['price']
    elif expired:
        return 'EXPIRED', ACTIVE_BUYS[pair]['price']

    return None, None

def send_telegram_alert(signal_type, pair, current_price, data):
    """Kirim notifikasi ke Telegram"""
    display_pair = f"{pair[:-4]}/USDT"
    message = ""

    emoji = {
        'BUY': '🚀',
        'SELL': '⚠️',
        'TAKE PROFIT': '✅',
        'STOP LOSS': '🛑',
        'EXPIRED': '⏰'
    }.get(signal_type, 'ℹ️')

    base_msg = f"{emoji} **{signal_type}**\n"
    base_msg += f"💱 {display_pair}\n"
    base_msg += f"💲 Price: ${current_price:.8f}\n"

    if signal_type == 'BUY':
        message = f"{base_msg}🔍 Mean: {data['mean']:.8f} | Std Dev: {data['std_dev']:.8f}\n"
        ACTIVE_BUYS[pair] = {'price': current_price, 'time': datetime.now()}

    elif signal_type in ['TAKE PROFIT', 'STOP LOSS', 'SELL', 'EXPIRED']:
        entry = ACTIVE_BUYS.get(pair)
        if entry:
            profit = ((current_price - entry['price']) / entry['price']) * 100
            duration = str(datetime.now() - entry['time']).split('.')[0]

            message = f"{base_msg}💲 Entry: ${entry['price']:.8f}\n"
            message += f"💰 {'Profit' if profit > 0 else 'Loss'}: {profit:+.2f}%\n"
            message += f"🕒 Hold Duration: {duration}"

            if signal_type in ['STOP LOSS', 'SELL', 'EXPIRED']:
                del ACTIVE_BUYS[pair]

    print(f"📢 Mengirim alert: {message}")

    try:
        save_active_buys_to_json()
    except Exception as e:
        print(f"❌ Gagal menyimpan: {str(e)}")

    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'Markdown'}
    )

# ==============================
# FUNGSI UTAMA
# ==============================
def main():
    """Program utama"""
    pairs = get_binance_top_pairs()
    print(f"🔍 Memulai analisis {len(pairs)} pair - {datetime.now().strftime('%d/%m %H:%M')}")

    for pair in pairs:
        try:
            data = analyze_pair(pair)
            if not data:
                continue

            display_pair = f"{pair[:-4]}/USDT"
            print(f"\n📈 {display_pair}:")

            signal, current_price = generate_signal(pair, data)

            if signal:
                send_telegram_alert(signal_type=signal, pair=pair, current_price=current_price, data=data)

        except Exception as e:
            print(f"⚠️ Error di {pair}: {str(e)}")
            continue

if __name__ == "__main__":
    main()
