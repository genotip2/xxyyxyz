import os
import requests
import json
from datetime import datetime, timedelta, timezone
from tradingview_ta import TA_Handler, Interval

# --- KONFIGURASI ---
# Definisikan zona waktu UTC+7
UTC7 = timezone(timedelta(hours=7))

TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

ACTIVE_BUYS_FILE = 'active_buys.json'
ACTIVE_BUYS = {}

# Konfigurasi Timeframe
TIMEFRAME_DAILY = Interval.INTERVAL_1_DAY

# --- FUNGSI UTILITY: LOAD & SAVE POSITION ---
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
                    'time': datetime.fromisoformat(d['time']),
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
                'time': d['time'].isoformat(),
            }
        with open(ACTIVE_BUYS_FILE, 'w') as f:
            json.dump(data, f, indent=4)
        print("✅ Posisi aktif disimpan.")
    except Exception as e:
        print(f"❌ Gagal menyimpan posisi aktif: {e}")

# --- FUNGSI ANALISIS ---
def analyze_pair_daily(pair):
    """Lakukan analisis teknikal untuk pair pada timeframe 1D menggunakan tradingview_ta."""
    try:
        handler = TA_Handler(
            symbol=pair,
            exchange="BINANCE",
            screener="CRYPTO",
            interval=TIMEFRAME_DAILY
        )
        analysis = handler.get_analysis()
        return analysis
    except Exception as e:
        print(f"⚠️ Gagal menganalisis {pair} pada interval {TIMEFRAME_DAILY}: {e}")
        return None

# --- GENERATE SINYAL TRADING SEDERHANA (HANYA MACD) ---
def generate_signal(pair):
    """
    Hasilkan sinyal BUY atau SELL berdasarkan MACD pada timeframe 1D.
    Mengembalikan tuple (signal, current_price, details).
    """
    analysis = analyze_pair_daily(pair)
    if analysis is None:
        return None, None, "Analisis gagal."

    current_price = analysis.indicators.get('close')
    macd = analysis.indicators.get('MACD.macd')
    signal_line = analysis.indicators.get('MACD.signal')

    if any(v is None for v in [current_price, macd, signal_line]):
        return None, current_price, "Data MACD tidak lengkap."

    # --- KONDISI SINYAL ---
    buy_condition = macd > signal_line
    sell_condition = macd < signal_line

    if pair not in ACTIVE_BUYS and buy_condition:
        return "BUY", current_price, f"MACD ({macd:.6f}) > Signal ({signal_line:.6f})"

    elif pair in ACTIVE_BUYS and sell_condition:
        return "SELL", current_price, f"MACD ({macd:.6f}) < Signal ({signal_line:.6f})"

    return None, current_price, "Tidak ada sinyal."

# --- FUNGSI PEMBANTU UNTUK LINK ---
def get_binance_url(pair):
    base = pair[:-4]
    quote = pair[-4:]
    return f"https://www.binance.com/en/trade/{base}_{quote}"

def get_tradingview_url(pair):
    return f"https://www.tradingview.com/chart/?symbol=BINANCE:{pair}"

# --- KIRIM ALERT TELEGRAM ---
def send_telegram_alert(signal_type, pair, current_price, details="", entry_analysis=None):
    display_pair = f"{pair[:-4]}/USDT"
    emoji = {'BUY': '🚀', 'SELL': '⚠️'}.get(signal_type, 'ℹ️')
    
    binance_url = get_binance_url(pair)
    tradingview_url = get_tradingview_url(pair)

    # Tambahkan data ke ACTIVE_BUYS saat BUY
    if signal_type == "BUY":
        ACTIVE_BUYS[pair] = {
            'price': current_price,
            'time': datetime.now(UTC7),
        }

    message = f"{emoji} *{signal_type}*\n"
    message += f"💱 *Pair:* [{display_pair}]({binance_url}) ==> [TradingView]({tradingview_url})\n"
    message += f"💲 *Price:* ${current_price:.8f}\n"

    # Tambahkan info entry untuk SELL
    if signal_type == "SELL" and pair in ACTIVE_BUYS:
        entry_data = ACTIVE_BUYS[pair]
        entry_price = entry_data['price']
        profit = (current_price - entry_price) / entry_price * 100
        duration = datetime.now(UTC7) - entry_data['time']
        message += f"▫️ *Entry Price:* ${entry_price:.8f}\n"
        message += f"💰 *{'Profit' if profit > 0 else 'Loss'}:* {profit:+.2f}%\n"
        message += f"🕒 *Duration:* {str(duration).split('.')[0]}\n"

    message += f"📝 *Details:* {details}\n"

    print(f"📢 Mengirim alert:\n{message}")
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                'chat_id': TELEGRAM_CHAT_ID,
                'text': message,
                'parse_mode': 'Markdown',
                'disable_web_page_preview': True
            }
        )
    except Exception as e:
        print(f"❌ Gagal mengirim alert Telegram: {e}")

    # Hapus pair dari ACTIVE_BUYS saat SELL
    if signal_type == "SELL" and pair in ACTIVE_BUYS:
        del ACTIVE_BUYS[pair]
        print(f"✅ Posisi {pair} ditutup dari active buys.")

# --- PROGRAM UTAMA ---
def main():
    load_active_buys()

    # --- DAFTAR PAIR YANG DISEDHANAKAN ---
    pairs_to_analyze = ["BCHUSDT", "PEPEUSDT"]

    print(f"🔍 Memulai analisis {len(pairs_to_analyze)} pair pada {datetime.now(UTC7).strftime('%Y-%m-%d %H:%M:%S')}")

    for pair in pairs_to_analyze:
        print(f"\n🔎 Sedang menganalisis pair: {pair}")
        try:
            signal, current_price, details = generate_signal(pair)
            if signal:
                print(f"💡 Sinyal: {signal}, Harga: {current_price:.8f}")
                print(f"📝 Details: {details}")
                # Dapatkan analysis untuk alert (jika sinyal ada)
                analysis_for_alert = analyze_pair_daily(pair) if signal else None
                send_telegram_alert(signal, pair, current_price, details, analysis_for_alert)
            else:
                print("ℹ️ Tidak ada sinyal untuk pair ini.")
        except Exception as e:
            print(f"⚠️ Error di {pair}: {e}")
            continue

    save_active_buys() # Simpan posisi aktif setelah analisis

if __name__ == "__main__":
    main()
