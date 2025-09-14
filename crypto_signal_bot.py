import os
import requests
import json
from datetime import datetime, timedelta, timezone
from tradingview_ta import TA_Handler, Interval

# Definisikan zona waktu UTC+7
UTC7 = timezone(timedelta(hours=7))

# KONFIGURASI

TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
CMC_API_KEY = os.getenv('CMC_API_KEY')

ACTIVE_BUYS_FILE = 'active_buys.json'
ACTIVE_BUYS = {}

UNUSED_SIGNAL_FILE = 'unused_signal.json'
UNUSED_SIGNALS = {}

CACHE_FILE = 'pairs_cache.json'
CACHE_EXPIRED_DAYS = 360

CACHE_UPDATED = False

TOP_PAIRS_CACHED = 2
PAIR_TO_ANALYZE = 2

ANALYSIS_ORDER = "top"

# Parameter trading - Nilai 0 berarti fitur tidak digunakan
TAKE_PROFIT_PERCENTAGE = 6
STOP_LOSS_PERCENTAGE = 3
TRAILING_STOP_PERCENTAGE = 3
MAX_HOLD_DURATION_DAYS = 0 # 0 berarti tidak ada batas waktu

TIMEFRAME_ENTRY = Interval.INTERVAL_1_HOUR
TIMEFRAME_TREND = Interval.INTERVAL_4_HOURS
TIMEFRAME_KONFIRMASI = Interval.INTERVAL_1_DAY

##############################
# FUNGSI UTILITY: LOAD & SAVE POSITION
##############################
def load_active_buys():
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
                    'highest_price': d.get('highest_price', None),
                }
                for pair, d in data.items()
            }
            print("✅ Posisi aktif dimuat.")
        except Exception as e:
            print(f"❌ Gagal memuat posisi aktif: {e}")
    else:
        ACTIVE_BUYS = {}

def save_active_buys():
    try:
        data = {}
        for pair, d in ACTIVE_BUYS.items():
            data[pair] = {
                'price': d['price'],
                'time': d['time'].isoformat(),
                'trailing_stop_active': d.get('trailing_stop_active', False),
                'highest_price': d.get('highest_price', None),
            }
        with open(ACTIVE_BUYS_FILE, 'w') as f:
            json.dump(data, f, indent=4)
        print("✅ Posisi aktif disimpan.")
    except Exception as e:
        print(f"❌ Gagal menyimpan posisi aktif: {e}")

def load_unused_signals():
    global UNUSED_SIGNALS
    if os.path.exists(UNUSED_SIGNAL_FILE):
        try:
            with open(UNUSED_SIGNAL_FILE, 'r') as f:
                data = json.load(f)
            UNUSED_SIGNALS = {
                pair: {
                    'price': d['price'],
                    'time': datetime.fromisoformat(d['time'])
                }
                for pair, d in data.items()
            }
            print("✅ Unused signals dimuat.")
        except Exception as e:
            print(f"❌ Gagal memuat unused signals: {e}")
            UNUSED_SIGNALS = {}
    else:
        UNUSED_SIGNALS = {}

def save_unused_signals():
    try:
        data = {}
        for pair, d in UNUSED_SIGNALS.items():
            data[pair] = {
                'price': d['price'],
                'time': d['time'].isoformat()
            }
        with open(UNUSED_SIGNAL_FILE, 'w') as f:
            json.dump(data, f, indent=4)
        print("✅ Unused signals disimpan.")
    except Exception as e:
        print(f"❌ Gagal menyimpan unused signals: {e}")

##############################
# FUNGSI MEMPERBARUI CACHE PAIR & MENGAMBIL RANKING CMC
##############################
def get_cmc_rankings(symbols):
    print("🔄 Mengambil data ranking dari CoinMarketCap...")
    # Perbaiki spasi ekstra di URL
    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest"
    headers = {
        "X-CMC_PRO_API_KEY": CMC_API_KEY
    }
    params = {
        "start": "1",
        "limit": "5000",
        "convert": "USD"
    }
    try:
        response = requests.get(url, headers=headers, params=params)
        data = response.json()
        ranking_mapping = {}
        for coin in data.get("data", []):
            symbol = coin.get("symbol")
            rank = coin.get("cmc_rank")
            if symbol and rank:
                ranking_mapping[symbol.upper()] = rank
        print("✅ Data ranking CMC berhasil diambil.")
        return ranking_mapping
    except Exception as e:
        print(f"❌ Gagal mengambil data ranking CMC: {e}")
        return {}

def update_pairs_cache():
    print("🔄 Memperbarui file cache pair...")
    all_tickers = []
    page = 1
    while True:
        # Perbaiki spasi ekstra di URL
        url = "https://api.coingecko.com/api/v3/exchanges/binance/tickers"
        params = {'include_exchange_logo': 'false', 'order': 'volume_desc', 'page': page}
        try:
            print(f"🔍 Mengambil halaman {page} dari CoinGecko...")
            response = requests.get(url, params=params)
            data = response.json()
            tickers = data.get('tickers', [])
            if not tickers:
                print(f"ℹ️ Halaman {page} tidak memiliki tickers, menghentikan proses pengambilan.")
                break
            print(f"✅ Halaman {page} berhasil diambil, jumlah tickers: {len(tickers)}")
            all_tickers.extend(tickers)
            page += 1
        except Exception as e:
            print(f"❌ Gagal mengambil halaman {page}: {e}")
            break

    usdt_tickers = [t for t in all_tickers if t.get('target') == 'USDT']
    print(f"🔍 Total tickers yang diambil: {len(all_tickers)}, setelah difilter USDT: {len(usdt_tickers)}")

    symbols = list({t.get('base').upper() for t in usdt_tickers if t.get('base')})
    print(f"🔍 Mengambil data ranking CMC untuk {len(symbols)} simbol: {symbols}")

    ranking_mapping = get_cmc_rankings(symbols)

    sorted_tickers = sorted(usdt_tickers, key=lambda x: ranking_mapping.get(x.get('base').upper(), float('inf')))

    top_pairs = sorted_tickers[:TOP_PAIRS_CACHED]

    pairs_list = [f"{ticker.get('base').upper()}USDT" for ticker in top_pairs]

    try:
        with open(CACHE_FILE, 'w') as f:
            json.dump(pairs_list, f, indent=4)
        print("✅ File cache pair berhasil diperbarui.")
    except Exception as e:
        print(f"❌ Gagal menyimpan file cache pair: {e}")

def get_pairs_from_cache():
    global CACHE_UPDATED
    now = datetime.now(UTC7)
    update_cache = False

    if not os.path.exists(CACHE_FILE):
        update_cache = True
        print("ℹ️ File cache pair tidak ditemukan. Memperbarui cache...")
    else:
        try:
            mtime = os.path.getmtime(CACHE_FILE)
            mod_time = datetime.fromtimestamp(mtime, UTC7)
            if now - mod_time > timedelta(days=CACHE_EXPIRED_DAYS):
                update_cache = True
                print("ℹ️ File cache pair kadaluarsa. Memperbarui cache...")
        except Exception as e:
            print(f"⚠️ Gagal mendapatkan waktu modifikasi cache: {e}")
            update_cache = True

    if update_cache:
        CACHE_UPDATED = True
        update_pairs_cache()
    else:
        CACHE_UPDATED = False

    try:
        with open(CACHE_FILE, 'r') as f:
            pairs = json.load(f)
        print(f"✅ Cache pair dimuat. Jumlah pair: {len(pairs)}")
        return pairs
    except Exception as e:
        print(f"❌ Gagal memuat file cache pair: {e}")
        return []

##############################
# FUNGSI ANALISIS: MULTI-TIMEFRAME
##############################
def analyze_pair_interval(pair, interval):
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

##############################
# FUNGSI BEST ENTRY & BEST EXIT
##############################
def is_best_entry_from_data(data):
    macd_entry = data.get('macd_entry')
    macd_signal_entry = data.get('macd_signal_entry')
    if macd_entry is None or macd_signal_entry is None or macd_entry <= macd_signal_entry:
        return False, "MACD entry tidak memenuhi (tidak > signal atau tidak > 0)."

    macd_trend = data.get('macd_trend')
    macd_signal_trend = data.get('macd_signal_trend')
    if macd_trend is None or macd_signal_trend is None or macd_trend <= macd_signal_trend:
        return False, "MACD trend tidak memenuhi (MACD trend <= signal trend)."

    ema10_konfirmasi = data.get('ema10_konfirmasi')
    ema20_konfirmasi = data.get('ema20_konfirmasi')
    if ema10_konfirmasi is None or ema20_konfirmasi is None or ema10_konfirmasi <= ema20_konfirmasi:
        return False, "EMA konfirmasi tidak memenuhi (EMA10 <= EMA20)."

    macd_konfirmasi = data.get('macd_konfirmasi')
    signal_konfirmasi = data.get('signal_konfirmasi')
    if macd_konfirmasi is None or signal_konfirmasi is None or macd_konfirmasi <= signal_konfirmasi:
        return False, "MACD konfirmasi tidak memenuhi (tidak > signal konfirmasi)."

    return True, "Best Entry Condition terpenuhi."

def is_best_exit_from_data(data):
    ema10_entry = data.get('ema10_entry')
    ema20_entry = data.get('ema20_entry')
    if ema10_entry is None or ema20_entry is None or ema10_entry >= ema20_entry:
        return False, "EMA entry tidak mendukung exit (EMA10 >= EMA20)."

    macd_entry = data.get('macd_entry')
    macd_signal_entry = data.get('macd_signal_entry')
    if macd_entry is None or macd_signal_entry is None or macd_entry >= macd_signal_entry:
        return False, "MACD entry tidak mendukung exit (tidak < signal)."

    macd_trend = data.get('macd_trend')
    macd_signal_trend = data.get('macd_signal_trend')
    if macd_trend is None or macd_signal_trend is None or macd_trend >= macd_signal_trend:
        return False, "MACD trend tidak mendukung exit (tidak < signal)."

    return True, "Best Exit Condition terpenuhi."

##############################
# GENERATE SINYAL TRADING DENGAN BEST ENTRY & BEST EXIT
##############################
def generate_signal(pair):
    trend_analysis = analyze_pair_interval(pair, TIMEFRAME_TREND)
    if trend_analysis is None:
        return None, None, "Analisis tren gagal.", None

    entry_analysis = analyze_pair_interval(pair, TIMEFRAME_ENTRY)
    if entry_analysis is None:
        return None, None, "Analisis entry gagal.", None

    konfirmasi_analysis = analyze_pair_interval(pair, TIMEFRAME_KONFIRMASI)
    if konfirmasi_analysis is None:
        return None, None, "Analisis konfirmasi gagal.", None

    current_price = entry_analysis.indicators.get('close')
    if current_price is None:
        return None, None, "Harga close tidak tersedia pada timeframe entry.", entry_analysis

    data = {
        'current_price': current_price,
        'ema10_entry': entry_analysis.indicators.get('EMA10'),
        'ema20_entry': entry_analysis.indicators.get('EMA20'),
        'macd_entry': entry_analysis.indicators.get('MACD.macd'),
        'macd_signal_entry': entry_analysis.indicators.get('MACD.signal'),
        'candle_entry': entry_analysis.summary.get('RECOMMENDATION'),
        'macd_trend': trend_analysis.indicators.get('MACD.macd'),
        'macd_signal_trend': trend_analysis.indicators.get('MACD.signal'),
        'ema10_konfirmasi': konfirmasi_analysis.indicators.get('EMA10'),
        'ema20_konfirmasi': konfirmasi_analysis.indicators.get('EMA20'),
        'macd_konfirmasi': konfirmasi_analysis.indicators.get('MACD.macd'),
        'signal_konfirmasi': konfirmasi_analysis.indicators.get('MACD.signal')
    }

    if pair in UNUSED_SIGNALS:
        best_exit_ok, best_exit_msg = is_best_exit_from_data(data)
        if best_exit_ok:
            print(f"✅ Pair {pair} dihapus dari unused signals karena best exit terpenuhi (tanpa notifikasi).")
            del UNUSED_SIGNALS[pair]
            return None, current_price, "Best exit terpenuhi, pair dihapus dari unused signals.", entry_analysis
        else:
            return None, current_price, "Tidak ada sinyal (unused signal mode).", entry_analysis

    if pair not in ACTIVE_BUYS:
        best_entry_ok, best_entry_msg = is_best_entry_from_data(data)
        if best_entry_ok:
            if CACHE_UPDATED:
                UNUSED_SIGNALS[pair] = {
                    'price': current_price,
                    'time': datetime.now(UTC7)
                }
                print(f"ℹ️ Sinyal BUY untuk {pair} dicatat di UNUSED_SIGNALS (tanpa notifikasi) karena cache diperbarui.")
                return None, current_price, "Buy signal dicatat ke unused_signal.", entry_analysis
            else:
                return "BUY", current_price, f"BEST ENTRY: {best_entry_msg}", entry_analysis
        else:
            return None, current_price, f"Tidak memenuhi best entry: {best_entry_msg}", entry_analysis
    else:
        data_active = ACTIVE_BUYS[pair]
        holding_duration = datetime.now(UTC7) - data_active['time']

        best_exit_ok, best_exit_msg = is_best_exit_from_data(data)
        if best_exit_ok:
            print(f"✅ Pair {pair} dihapus dari active buys karena best exit terpenuhi.")
            return "SELL", current_price, f"BEST EXIT: {best_exit_msg}", entry_analysis

        entry_price = data_active['price']
        profit_from_entry = (current_price - entry_price) / entry_price * 100

        # --- Cek Expired (MAX_HOLD_DURATION_DAYS) ---
        # Jika MAX_HOLD_DURATION_DAYS adalah 0, fitur ini dinonaktifkan
        if MAX_HOLD_DURATION_DAYS > 0 and holding_duration > timedelta(days=MAX_HOLD_DURATION_DAYS):
            UNUSED_SIGNALS[pair] = ACTIVE_BUYS[pair]
            print(f"✅ Pair {pair} dipindahkan ke unused signals karena expired (hold {holding_duration.days} hari).")
            return "EXPIRED", current_price, f"Durasi hold: {holding_duration.days} hari", entry_analysis

        # --- Cek Stop Loss (STOP_LOSS_PERCENTAGE) ---
        # Jika STOP_LOSS_PERCENTAGE adalah 0, fitur ini dinonaktifkan
        if STOP_LOSS_PERCENTAGE > 0 and profit_from_entry <= -STOP_LOSS_PERCENTAGE:
            UNUSED_SIGNALS[pair] = ACTIVE_BUYS[pair]
            print(f"✅ Pair {pair} dipindahkan ke unused signals karena stop loss tercapai.")
            return "STOP LOSS", current_price, "Stop loss tercapai.", entry_analysis

        # --- Cek Take Profit dan Trailing Stop (TAKE_PROFIT_PERCENTAGE & TRAILING_STOP_PERCENTAGE) ---
        # Jika salah satu dari ini 0, fitur ini dinonaktifkan
        if TAKE_PROFIT_PERCENTAGE > 0 and TRAILING_STOP_PERCENTAGE > 0:
            # Cek aktivasi trailing stop ketika target take profit tercapai
            if not data_active.get('trailing_stop_active', False) and profit_from_entry >= TAKE_PROFIT_PERCENTAGE:
                ACTIVE_BUYS[pair]['trailing_stop_active'] = True
                ACTIVE_BUYS[pair]['highest_price'] = current_price
                return "TAKE PROFIT", current_price, "Target take profit tercapai, trailing stop diaktifkan.", entry_analysis

            # Jika trailing stop sudah aktif
            if data_active.get('trailing_stop_active', False):
                prev_high = data_active.get('highest_price')
                if prev_high is None or current_price > prev_high:
                    ACTIVE_BUYS[pair]['highest_price'] = current_price
                    send_telegram_alert(
                        "NEW HIGH",
                        pair,
                        current_price,
                        f"New highest price (sebelumnya: {prev_high:.8f})" if prev_high else "New highest price set.",
                        entry_analysis
                    )
                trailing_stop_price = ACTIVE_BUYS[pair]['highest_price'] * (1 - TRAILING_STOP_PERCENTAGE / 100)
                if current_price < trailing_stop_price:
                    UNUSED_SIGNALS[pair] = ACTIVE_BUYS[pair]
                    print(f"✅ Pair {pair} dipindahkan ke unused signals karena trailing stop tercapai.")
                    return "TRAILING STOP", current_price, f"Harga turun ke trailing stop: {trailing_stop_price:.8f}", entry_analysis
        # Jika TAKE_PROFIT_PERCENTAGE > 0 tetapi TRAILING_STOP_PERCENTAGE = 0, hanya cek take profit tanpa trailing stop
        elif TAKE_PROFIT_PERCENTAGE > 0 and TRAILING_STOP_PERCENTAGE == 0:
             if profit_from_entry >= TAKE_PROFIT_PERCENTAGE:
                # Jika hanya take profit yang aktif, kita bisa mempertimbangkan untuk menjual langsung
                # atau memindahkan ke unused signals. Di sini saya pilih memindahkan ke unused.
                # Anda bisa menyesuaikan logikanya.
                UNUSED_SIGNALS[pair] = ACTIVE_BUYS[pair]
                print(f"✅ Pair {pair} dipindahkan ke unused signals karena target take profit tercapai (tanpa trailing stop).")
                return "TAKE PROFIT", current_price, "Target take profit tercapai (tanpa trailing stop).", entry_analysis


        return None, current_price, "Tidak ada sinyal.", entry_analysis

##############################
# FUNGSI PEMBANTU UNTUK MENGHADIRKAN LINK BINANCE & TRADINGVIEW
##############################
def get_binance_url(pair):
    base = pair[:-4]
    quote = pair[-4:]
    # Perbaiki spasi ekstra di URL
    return f"https://www.binance.com/en/trade/{base}_{quote}"

def get_tradingview_url(pair):
    return f"https://www.tradingview.com/chart/?symbol=BINANCE:{pair}"

##############################
# KIRIM ALERT TELEGRAM (dengan parameter entry_analysis opsional)
##############################
def send_telegram_alert(signal_type, pair, current_price, details="", entry_analysis=None):
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

    binance_url = get_binance_url(pair)
    tradingview_url = get_tradingview_url(pair)

    if signal_type == "BUY":
        ACTIVE_BUYS[pair] = {
            'price': current_price,
            'time': datetime.now(UTC7),
            'trailing_stop_active': False,
            'highest_price': None,
        }

    message = f"{emoji} *{signal_type}*\n"
    # Perbaiki spasi ekstra di URL
    message += f"💱 *Pair:* [{display_pair}]({binance_url}) ==> [TradingView]({tradingview_url})\n"
    message += f"💲 *Price:* ${current_price:.8f}\n"

    if signal_type != "BUY" and pair in ACTIVE_BUYS:
        entry_data = ACTIVE_BUYS[pair]
        entry_price = entry_data['price']
        profit = (current_price - entry_price) / entry_price * 100
        duration = datetime.now(UTC7) - entry_data['time']
        message_entry = (
            f"▫️ *Entry Price:* ${entry_price:.8f}\n"
            f"💰 *{'Profit' if profit > 0 else 'Loss'}:* {profit:+.2f}%\n"
            f"🕒 *Duration:* {str(duration).split('.')[0]}\n"
        )
    else:
        message_entry = ""
    message += message_entry

    if entry_analysis is None:
        entry_analysis = analyze_pair_interval(pair, TIMEFRAME_ENTRY)
    if entry_analysis:
        rsi_value = entry_analysis.indicators.get('RSI')
        adx_value = entry_analysis.indicators.get('ADX')
        stoch_k_value = entry_analysis.indicators.get('Stoch.K')
        if rsi_value is not None and adx_value is not None and stoch_k_value is not None:
            indicator_info = f"*RSI:* {rsi_value:.2f}, *ADX:* {adx_value:.2f}, *Stoch K:* {stoch_k_value:.2f}"
            message += f"📊 {indicator_info}\n"

    print(f"📢 Mengirim alert:\n{message}")
    try:
        # Perbaiki spasi ekstra di URL
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

    if signal_type in ["SELL", "EXPIRED", "STOP LOSS", "TRAILING STOP"]:
        if pair in ACTIVE_BUYS:
            del ACTIVE_BUYS[pair]
            print(f"✅ Posisi {pair} ditutup dari active buys dengan sinyal {signal_type}.")

##############################
# PROGRAM UTAMA
##############################
def main():
    load_active_buys()
    load_unused_signals()

    pairs = get_pairs_from_cache()

    if PAIR_TO_ANALYZE > 0 and PAIR_TO_ANALYZE < len(pairs):
        if ANALYSIS_ORDER.lower() == "top":
            pairs = pairs[:PAIR_TO_ANALYZE]
        elif ANALYSIS_ORDER.lower() == "bottom":
            pairs = pairs[-PAIR_TO_ANALYZE:]

    print(f"🔍 Memulai analisis {len(pairs)} pair pada {datetime.now(UTC7).strftime('%Y-%m-%d %H:%M:%S')}")

    for pair in pairs:
        print(f"\n🔎 Sedang menganalisis pair: {pair}")
        try:
            signal, current_price, details, entry_analysis = generate_signal(pair)
            if signal:
                print(f"💡 Sinyal: {signal}, Harga: {current_price:.8f}")
                print(f"📝 Details: {details}")
                send_telegram_alert(signal, pair, current_price, details, entry_analysis)
            else:
                print("ℹ️ Tidak ada sinyal untuk pair ini.")
        except Exception as e:
            print(f"⚠️ Error di {pair}: {e}")
            continue

    save_active_buys()
    save_unused_signals()

if __name__ == "__main__":
    main()
