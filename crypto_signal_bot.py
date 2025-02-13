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
TAKE_PROFIT_PERCENTAGE = 5          # Target take profit 5% (dihitung dari harga entry)
STOP_LOSS_PERCENTAGE = 2             # Stop loss 2% (dihitung dari harga entry)
TRAILING_STOP_PERCENTAGE = 2     # Trailing stop 2% (dari harga tertinggi setelah take profit tercapai)
MAX_HOLD_DURATION_HOUR = 24    # Durasi hold maksimum 24 jam
PAIR_TO_ANALYZE = 50                        # Jumlah pair yang akan dianalisis
RSI_LIMIT = 60                                        # Batas atas RSI untuk entry
MIN_RECOMMEND_MA = 0.7               # Minimal nilai recommend.ma pada timeframe 1H untuk dianggap bullish

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
                    'time': datetime.fromisoformat(d['time']),
                    'trailing_stop_active': d.get('trailing_stop_active', False),
                    'highest_price': d.get('highest_price', None)
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
                'trailing_stop_active': d.get('trailing_stop_active', False),
                'highest_price': d.get('highest_price', None)
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
      - BUY: Jika tren 1H bullish (RECOMMENDATION 'BUY' atau 'STRONG_BUY' dan recommend.ma > MIN_RECOMMEND_MA)
             dan terjadi pullback pada RSI < RSI_LIMIT, EMA 10 > EMA 20 dan MACD > Signal,
             serta posisi belum aktif.
      - EXIT (SELL/TAKE PROFIT/STOP LOSS/EXPIRED/TRAILING STOP):
            Jika posisi aktif dan salah satu kondisi exit terpenuhi:
              * Stop Loss: jika profit (dari entry) turun mencapai -STOP_LOSS_PERCENTAGE.
              * TAKE PROFIT: Jika profit mencapai TAKE_PROFIT_PERCENTAGE, aktifkan trailing stop.
              * TRAILING STOP: Setelah trailing stop aktif, posisi akan keluar jika harga turun
                dari harga tertinggi sebesar TRAILING_STOP_PERCENTAGE.
              * SELL: Jika tren 1H sudah tidak bullish.
              * EXPIRED: Jika durasi hold melebihi MAX_HOLD_DURATION_HOUR.
    """
    # Analisis pada timeframe 1H (sebagai acuan tren utama)
    trend_analysis = analyze_pair_interval(pair, Interval.INTERVAL_1_HOUR)
    if trend_analysis is None:
        return None, None, "Analisis 1H gagal."
    trend_rec = trend_analysis.summary.get('RECOMMENDATION')
    trend_bullish = trend_rec in ['BUY', 'STRONG_BUY']
    
    # Tambahan: cek nilai recommend.ma harus lebih besar dari MIN_RECOMMEND_MA
    trend_recommend_ma = trend_analysis.indicators.get('Recommend.MA')
    if trend_recommend_ma is None:
        return None, None, "Data recommend.ma tidak tersedia pada analisis 1H."
    if trend_recommend_ma <= MIN_RECOMMEND_MA:
        # Jika nilai recommend.ma kurang, anggap tidak bullish
        trend_bullish = False

    # Analisis pada timeframe 15M untuk entry/pullback
    entry_analysis = analyze_pair_interval(pair, Interval.INTERVAL_15_MINUTES)
    if entry_analysis is None:
        return None, None, "Analisis 15M gagal."
    entry_close = entry_analysis.indicators.get('close')
    entry_rsi = entry_analysis.indicators.get('RSI')
    entry_ema10 = entry_analysis.indicators.get('EMA10')
    entry_ema20 = entry_analysis.indicators.get('EMA20')
    entry_macd = entry_analysis.indicators.get('MACD.macd')
    entry_signal_line = entry_analysis.indicators.get('MACD.signal')
    
    if entry_close is None:
        return None, None, "Harga close 15M tidak tersedia."

    # Kondisi pullback: RSI < RSI_LIMIT, EMA 10 > EMA 20, dan MACD > Signal
    pullback_entry = (entry_rsi is not None and entry_rsi < RSI_LIMIT) and \
                     (entry_ema10 is not None and entry_ema20 is not None and entry_ema10 > entry_ema20) and \
                     (entry_macd is not None and entry_signal_line is not None and entry_macd > entry_signal_line)
    
    # Jika posisi belum aktif dan kondisi entry terpenuhi, berikan sinyal BUY
    if pair not in ACTIVE_BUYS and trend_bullish and pullback_entry:
        details = (f"1H: {trend_rec}, Recommend.MA: {trend_recommend_ma:.2f}, "
                   f"EMA 10 & EMA 20 Cross, MACD: Bullish, RSI M15: {entry_rsi:.2f}")
        return "BUY", entry_close, details

    # Jika posisi sudah aktif, periksa kondisi exit dan target profit
    if pair in ACTIVE_BUYS:
        data = ACTIVE_BUYS[pair]
        holding_duration = datetime.now() - data['time']
        if holding_duration > timedelta(hours=MAX_HOLD_DURATION_HOUR):
            return "EXPIRED", entry_close, "Durasi hold maksimal tercapai."
        
        entry_price = data['price']
        profit_from_entry = (entry_close - entry_price) / entry_price * 100

        # Cek stop loss berdasarkan harga entry
        if profit_from_entry <= -STOP_LOSS_PERCENTAGE:
            return "STOP LOSS", entry_close, "Harga turun ke stop loss target."
        
        # Jika take profit tercapai dan trailing stop belum aktif, aktifkan trailing stop
        if not data.get('trailing_stop_active', False) and profit_from_entry >= TAKE_PROFIT_PERCENTAGE:
            ACTIVE_BUYS[pair]['trailing_stop_active'] = True
            ACTIVE_BUYS[pair]['highest_price'] = entry_close
            return "TAKE PROFIT", entry_close, "Target take profit tercapai, trailing stop diaktifkan."
        
        # Jika trailing stop aktif, perbarui harga tertinggi dan cek kondisi trailing stop
        if data.get('trailing_stop_active', False):
            prev_high = data.get('highest_price')
            if prev_high is None or entry_close > prev_high:
                ACTIVE_BUYS[pair]['highest_price'] = entry_close
                if prev_high is not None:
                    send_telegram_alert("NEW HIGH", pair, entry_close, f"New highest price (sebelumnya: {prev_high:.8f})")
            trailing_stop_price = ACTIVE_BUYS[pair]['highest_price'] * (1 - TRAILING_STOP_PERCENTAGE / 100)
            if entry_close < trailing_stop_price:
                return "TRAILING STOP", entry_close, f"Harga turun ke trailing stop target."
        
        # Jika tren 1H sudah tidak bullish, keluarkan sinyal SELL
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
    Untuk sinyal exit seperti SELL, STOP LOSS, EXPIRED, atau TRAILING STOP, posisi dihapus.
    Sementara untuk sinyal TAKE PROFIT, hanya mengaktifkan trailing stop tanpa menghapus posisi.
    Untuk sinyal "NEW HIGH", posisi tidak dihapus.
    """
    display_pair = f"{pair[:-4]}/USDT"
    emoji = {
        'BUY': '🚀',
        'SELL': '⚠️',
        'TAKE PROFIT': '✅',
        'STOP LOSS': '🛑',
        'EXPIRED': '⌛',
        'TRAILING STOP': '📉',
        'NEW HIGH': '📈'
    }.get(signal_type, 'ℹ️')

    message = f"{emoji} *{signal_type}*\n"
    message += f"💱 *Pair:* {display_pair}\n"
    message += f"💲 *Price:* ${current_price:.8f}\n"
    if details:
        message += f"📝 *Kondisi:* {details}\n"

    # Jika BUY, simpan entry baru
    if signal_type == "BUY":
        ACTIVE_BUYS[pair] = {
            'price': current_price,
            'time': datetime.now(),
            'trailing_stop_active': False,
            'highest_price': None
        }
    # Untuk sinyal TAKE PROFIT, hanya mengirim alert (posisi tetap aktif dengan trailing stop)
    elif signal_type == "TAKE PROFIT":
        pass
    # Untuk sinyal exit (SELL, STOP LOSS, EXPIRED, TRAILING STOP), tampilkan detail entry dan hapus posisi
    elif signal_type in ["SELL", "STOP LOSS", "EXPIRED", "TRAILING STOP"]:
        if pair in ACTIVE_BUYS:
            entry_price = ACTIVE_BUYS[pair]['price']
            profit = (current_price - entry_price) / entry_price * 100
            duration = datetime.now() - ACTIVE_BUYS[pair]['time']
            message += f"▫️ *Entry Price:* ${entry_price:.8f}\n"
            message += f"💰 *{'Profit' if profit > 0 else 'Loss'}:* {profit:+.2f}%\n"
            message += f"🕒 *Duration:* {str(duration).split('.')[0]}\n"
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
            send_telegram_alert("EXPIRED", pair, current_price, f"Durasi hold: {str(holding_duration).split('.')[0]}")

    save_active_buys()

if __name__ == "__main__":
    main()
