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
PROFIT_TARGET_PERCENTAGE_1 = 5    # Target profit TP1 5% (dihitung dari harga entry)
PROFIT_TARGET_PERCENTAGE_2 = 8    # Target profit TP2 8% (dihitung dari harga entry)
STOP_LOSS_PERCENTAGE = 2          # Stop loss 2% (dihitung dari harga entry)
EXIT_TRADE_TARGET = 2             # Exit Trade target 2% (dihitung dari harga TP1, digunakan setelah TP1 tercapai)
MAX_HOLD_DURATION_HOUR = 24       # Durasi hold maksimum 24 jam
PAIR_TO_ANALYZE = 50             # Jumlah pair yang akan dianalisis
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
                    'time': datetime.fromisoformat(d['time']),
                    'tp1_hit': d.get('tp1_hit', False),
                    'tp1_price': d.get('tp1_price', None)
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
                'tp1_hit': d.get('tp1_hit', False),
                'tp1_price': d.get('tp1_price', None)
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
             dan terjadi pullback pada RSI < RSI_LIMIT, EMA 10 > EMA 20 dan MACD > Signal)
             serta posisi belum aktif.
      - EXIT (SELL/TAKE PROFIT/STOP LOSS/EXIT TRADE/EXPIRED):
            Jika posisi aktif dan salah satu kondisi exit terpenuhi:
              * Stop Loss: jika profit (dari entry) turun mencapai -STOP_LOSS_PERCENTAGE.
              * TAKE PROFIT 1: Jika profit (dihitung dari entry) mencapai PROFIT_TARGET_PERCENTAGE_1,
                               maka posisi diberi tanda TP1 dan harga TP1 dicatat (tetap tidak keluar).
              * EXIT TRADE: Setelah TP1 tercapai, jika harga turun dari TP1 sebesar EXIT_TRADE_TARGET,
                            maka kirim sinyal EXIT TRADE dengan informasi tambahan.
              * TAKE PROFIT 2: Jika profit (dihitung dari entry) mencapai PROFIT_TARGET_PERCENTAGE_2,
                               maka posisi exit.
              * SELL: Jika tren 1H sudah tidak bullish.
              * EXPIRED: Jika durasi hold melebihi MAX_HOLD_DURATION_HOUR.
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
    entry_ema10 = entry_analysis.indicators.get('EMA10')
    entry_ema20 = entry_analysis.indicators.get('EMA20')
    entry_macd = entry_analysis.indicators.get('MACD.macd')
    entry_signal_line = entry_analysis.indicators.get('MACD.signal')
    
    if entry_close is None:
        return None, None, "Harga close 15M tidak tersedia."

    # Kondisi pullback pada RSI < RSI_LIMIT, EMA 10 > EMA 20, dan MACD > Signal
    pullback_entry = (entry_rsi is not None and entry_rsi < RSI_LIMIT) and \
                     (entry_ema10 is not None and entry_ema20 is not None and entry_ema10 > entry_ema20) and \
                     (entry_macd is not None and entry_signal_line is not None and entry_macd > entry_signal_line)
    
    # Jika posisi belum aktif dan kondisi entry terpenuhi, berikan sinyal BUY
    if pair not in ACTIVE_BUYS and trend_bullish and pullback_entry:
        details = f"1H: {trend_rec}, EMA 10 & EMA 20 Cross, MACD: Bullish, RSI M15: {entry_rsi:.2f}"
        return "BUY", entry_close, details

    # Jika posisi sudah aktif, periksa kondisi exit dan target profit
    if pair in ACTIVE_BUYS:
        data = ACTIVE_BUYS[pair]
        holding_duration = datetime.now() - data['time']
        if holding_duration > timedelta(hours=MAX_HOLD_DURATION_HOUR):
            return "EXPIRED", entry_close, f"Durasi hold maksimal"
        
        entry_price = data['price']
        profit_from_entry = (entry_close - entry_price) / entry_price * 100

        # Cek stop loss berdasarkan harga entry (untuk antisipasi penurunan mendadak)
        if profit_from_entry <= -STOP_LOSS_PERCENTAGE:
            return "STOP LOSS", entry_close, "Limit stop loss tercapai"
        
        # Cek target TP2 (dihitung dari entry)
        if profit_from_entry >= PROFIT_TARGET_PERCENTAGE_2:
            return "TAKE PROFIT 2", entry_close, f"Target TP2 tercapai"
        
        # Jika TP1 belum tercapai dan profit dari entry mencapai target TP1, beri sinyal TAKE PROFIT 1
        if not data.get('tp1_hit', False) and profit_from_entry >= PROFIT_TARGET_PERCENTAGE_1:
            ACTIVE_BUYS[pair]['tp1_hit'] = True
            ACTIVE_BUYS[pair]['tp1_price'] = entry_close
            return "TAKE PROFIT 1", entry_close, f"Target TP1 tercapai"
        
        # Jika TP1 sudah tercapai, hitung exit trade (dihitung dari harga TP1)
        if data.get('tp1_hit', False):
            tp1_price = data.get('tp1_price')
            exit_trade_profit = (entry_close - tp1_price) / tp1_price * 100
            if exit_trade_profit <= -EXIT_TRADE_TARGET:
                details = (f"Exit Trade: Harga turun {exit_trade_profit:.2f}% dari TP1\n"
                           f"▫️ TP1 Price: {tp1_price:.8f}\n")
                return "EXIT TRADE", entry_close, details
        
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
    Untuk sinyal exit:
      - TAKE PROFIT 1: Posisi tidak dihapus, hanya diberi tanda (tp1_hit) dan dicatat harga TP1.
      - EXIT TRADE, TAKE PROFIT 2, SELL, STOP LOSS, EXPIRED: Posisi dihapus.
    """
    display_pair = f"{pair[:-4]}/USDT"
    emoji = {
        'BUY': '🚀',
        'SELL': '⚠️',
        'TAKE PROFIT 1': '✅',
        'TAKE PROFIT 2': '🎉',
        'EXIT TRADE': '🚪',
        'STOP LOSS': '🛑',
        'EXPIRED': '⌛'
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
            'tp1_hit': False,
            'tp1_price': None
        }
    # Untuk TAKE PROFIT 1, tampilkan informasi entry tanpa menghapus posisi
    elif signal_type == "TAKE PROFIT 1":
        if pair in ACTIVE_BUYS:
            entry_price = ACTIVE_BUYS[pair]['price']
            profit = (current_price - entry_price) / entry_price * 100
            duration = datetime.now() - ACTIVE_BUYS[pair]['time']
            message += f"▫️ *Entry Price:* ${entry_price:.8f}\n"
            message += f"💰 *{'Profit' if profit > 0 else 'Loss'}:* {profit:+.2f}%\n"
            message += f"🕒 *Duration:* {str(duration).split('.')[0]}\n"
    # Untuk sinyal exit (EXIT TRADE, TAKE PROFIT 2, SELL, STOP LOSS, EXPIRED), tampilkan detail entry dan hapus posisi
    else:
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
