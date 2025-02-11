import os
import requests
import json
from datetime import datetime, timedelta
from tradingview_ta import TA_Handler, Interval

# ==============================
# KONFIGURASI
# ==============================

TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

ACTIVE_BUYS_FILE = 'active_buys.json'
ACTIVE_BUYS = {}

# Parameter trading
PROFIT_TARGET_PERCENTAGE = 5    # Target profit 5%
STOP_LOSS_PERCENTAGE = 2        # Stop loss 2%
MAX_HOLD_DURATION_HOUR = 24     # Durasi hold maksimum 24 jam
PAIR_TO_ANALYZE = 100           # Jumlah pair yang akan dianalisis
RSI_LIMIT = 60           # Batas atas RSI untuk entry

# ==============================
# FUNGSI UTITAS: LOAD & SAVE POSITION
# ==============================

def load_active_buys():
    """Muat posisi aktif dari file JSON."""
    global ACTIVE_BUYS
    if os.path.exists(ACTIVE_BUYS_FILE):
        try:
            with open(ACTIVE_BUYS_FILE, 'r') as f:
                data = json.load(f)
            ACTIVE_BUYS = {
                pair: {
                    'price': d['price'],
                    'time': datetime.fromisoformat(d['time'])
                }
                for pair, d in data.items()
            }
            print("✅ Posisi aktif dimuat.")
        except Exception as e:
            print(f"❌ Gagal memuat posisi aktif: {e}")
    else:
        ACTIVE_BUYS = {}

def save_active_buys():
    """Simpan posisi aktif ke file JSON."""
    try:
        data = {}
        for pair, d in ACTIVE_BUYS.items():
            data[pair] = {
                'price': d['price'],
                'time': d['time'].isoformat()
            }
        with open(ACTIVE_BUYS_FILE, 'w') as f:
            json.dump(data, f, indent=4)
        print("✅ Posisi aktif disimpan.")
    except Exception as e:
        print(f"❌ Gagal menyimpan posisi aktif: {e}")

# ==============================
# FUNGSI MENDAPATKAN PAIR TERATAS
# ==============================

def get_binance_top_pairs():
    """
    Ambil pasangan (pair) teratas berdasarkan volume trading dari Binance melalui CoinGecko.
    Hanya pair dengan target USDT yang diambil.
    """
    url = "https://api.coingecko.com/api/v3/exchanges/binance/tickers"
    params = {'include_exchange_logo': 'false', 'order': 'volume_desc'}
    try:
        response = requests.get(url, params=params)
        data = response.json()
        usdt_pairs = [t for t in data['tickers'] if t['target'] == 'USDT']
        sorted_pairs = sorted(usdt_pairs, key=lambda x: x['converted_volume']['usd'], reverse=True)[:PAIR_TO_ANALYZE]
        return [f"{p['base']}USDT" for p in sorted_pairs]
    except Exception as e:
        print(f"❌ Gagal mengambil pair: {e}")
        return []

# ==============================
# FUNGSI ANALISIS: MULTI-TIMEFRAME (1H & 15M)
# ==============================

def analyze_pair_interval(pair, interval):
    """
    Lakukan analisis teknikal untuk pair pada timeframe tertentu menggunakan tradingview_ta.
    """
    try:
        handler = TA_Handler(
            symbol=pair,
            exchange="BINANCE",
            screener="CRYPTO",
            interval=interval
        )
        analysis = handler.get_analysis()
        return analysis
    except Exception as e:
        print(f"⚠️ Gagal menganalisis {pair} pada interval {interval}: {e}")
        return None

# ==============================
# GENERATE SINYAL TRADING
# ==============================

def generate_signal(pair):
    """
    Hasilkan sinyal trading dengan logika:
      - BUY: Jika tren 1H bullish (RECOMMENDATION 'BUY' atau 'STRONG_BUY')
             dan terjadi pullback pada 15M (RSI < 40 dan MACD > Signal)
             serta posisi belum aktif.
      - EXIT (SELL/TAKE PROFIT/STOP LOSS/EXPIRED): Jika posisi aktif dan salah satu kondisi exit terpenuhi.
    """
    # Analisis pada timeframe 1H (sebagai acuan tren utama)
    trend_analysis = analyze_pair_interval(pair, Interval.INTERVAL_1_HOUR)
    if trend_analysis is None:
        return None, None, "Analisis 1H gagal."
    trend_rec = trend_analysis.summary.get('RECOMMENDATION')
    trend_bullish = trend_rec in ['BUY', 'STRONG_BUY']

    # Analisis pada timeframe 15M untuk entry/pullback
    entry_analysis = analyze_pair_interval(pair, Interval.INTERVAL_15_MINUTES)
    if entry_analysis is None:
        return None, None, "Analisis 15M gagal."
    entry_close = entry_analysis.indicators.get('close')
    entry_rsi = entry_analysis.indicators.get('RSI')
    previous_rsi = entry_analysis.indicators.get('RSI[1]')
    entry_macd = entry_analysis.indicators.get('MACD.macd')
    entry_signal_line = entry_analysis.indicators.get('MACD.signal')
    
    if entry_close is None:
        return None, None, "Harga close 15M tidak tersedia."

    # Kondisi pullback pada 15M: RSI < 40 dan MACD > Signal
    pullback_entry = (entry_rsi is not None and entry_rsi < RSI_LIMIT) and \
                     (entry_rsi is not None and previous_rsi is not None and entry_rsi > previous_rsi) and \
                     (entry_macd is not None and entry_signal_line is not None and entry_macd > entry_signal_line)
    
    # Jika posisi belum aktif dan kondisi entry terpenuhi
    if pair not in ACTIVE_BUYS and trend_bullish and pullback_entry:
        details = f"1H: {trend_rec}, 15M RSI: {entry_rsi:.2f}, MACD: Bullish"
        return "BUY", entry_close, details

    # Jika posisi sudah aktif, periksa kondisi exit
    if pair in ACTIVE_BUYS:
        entry_price = ACTIVE_BUYS[pair]['price']
        profit = (entry_close - entry_price) / entry_price * 100
        holding_duration = datetime.now() - ACTIVE_BUYS[pair]['time']

        if profit >= PROFIT_TARGET_PERCENTAGE:
            return "TAKE PROFIT", entry_close, f"Profit tercapai"
        if profit <= -STOP_LOSS_PERCENTAGE:
            return "STOP LOSS", entry_close, f"Stop loss tercapai"
        if holding_duration > timedelta(hours=MAX_HOLD_DURATION_HOUR):
            return "EXPIRED", entry_close, f"Durasi hold maksimal"
        if not trend_bullish:
            return "SELL", entry_close, f"Trend 1H Bearish ({trend_rec})"
    
    return None, entry_close, "Tidak ada sinyal."

# ==============================
# KIRIM ALERT TELEGRAM
# ==============================

def send_telegram_alert(signal_type, pair, current_price, details=""):
    """
    Mengirim notifikasi ke Telegram.
    Untuk sinyal BUY, posisi disimpan ke ACTIVE_BUYS.
    Untuk sinyal exit (SELL, TAKE PROFIT, STOP LOSS, EXPIRED) posisi akan dihapus.
    """
    display_pair = f"{pair[:-4]}/USDT"
    emoji = {
        'BUY': '🚀',
        'SELL': '⚠️',
        'TAKE PROFIT': '✅',
        'STOP LOSS': '🛑',
        'EXPIRED': '⌛'
    }.get(signal_type, 'ℹ️')

    message = f"{emoji} *{signal_type}*\n"
    message += f"💱 *Pair:* {display_pair}\n"
    message += f"💲 *Price:* ${current_price:.8f}\n"
    if details:
        message += f"📝 *Kondisi:* {details}\n"

    # Jika BUY, simpan entry
    if signal_type == "BUY":
        ACTIVE_BUYS[pair] = {'price': current_price, 'time': datetime.now()}
    else:
        # Jika posisi aktif, tampilkan info entry dan hitung profit
        if pair in ACTIVE_BUYS:
            entry_price = ACTIVE_BUYS[pair]['price']
            profit = (current_price - entry_price) / entry_price * 100
            duration = datetime.now() - ACTIVE_BUYS[pair]['time']
            message += f"▫️ *Entry Price:* ${entry_price:.8f}\n"
            message += f"💰 *{'Profit' if profit > 0 else 'Loss'}:* {profit:+.2f}%\n"
            message += f"🕒 *Duration:* {str(duration).split('.')[0]}\n"
            # Hapus posisi setelah exit
            del ACTIVE_BUYS[pair]

    print(f"📢 Mengirim alert:\n{message}")
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'Markdown'}
        )
    except Exception as e:
        print(f"❌ Gagal mengirim alert Telegram: {e}")

# ==============================
# PROGRAM UTAMA
# ==============================

def main():
    load_active_buys()
    pairs = get_binance_top_pairs()
    print(f"🔍 Memulai analisis {len(pairs)} pair pada {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    for pair in pairs:
        print(f"\n🔎 Sedang menganalisis pair: {pair}")
        try:
            signal, current_price, details = generate_signal(pair)
            if signal:
                print(f"💡 Sinyal: {signal}, Harga: {current_price:.8f}")
                print(f"📝 Details: {details}")
                send_telegram_alert(signal, pair, current_price, details)
            else:
                # Hanya tampilkan notifikasi jika tidak ada sinyal
                print("ℹ️ Tidak ada sinyal untuk pair ini.")
        except Exception as e:
            print(f"⚠️ Error di {pair}: {e}")
            continue

    # Auto-close posisi jika durasi hold melebihi batas (cek ulang posisi aktif)
    for pair in list(ACTIVE_BUYS.keys()):
        holding_duration = datetime.now() - ACTIVE_BUYS[pair]['time']
        if holding_duration > timedelta(hours=MAX_HOLD_DURATION_HOUR):
            entry_analysis = analyze_pair_interval(pair, Interval.INTERVAL_15_MINUTES)
            current_price = entry_analysis.indicators.get('close') if entry_analysis else 0
            send_telegram_alert("EXPIRED", pair, current_price, f"Durasi hold: {holding_duration}")

    save_active_buys()

if __name__ == "__main__":
    main()
