import os
import requests
import json
from datetime import datetime, timedelta
from tradingview_ta import TA_Handler, Interval

# KONFIGURASI
TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
CMC_API_KEY = os.getenv('CMC_API_KEY')  # API key untuk CoinMarketCap

ACTIVE_BUYS_FILE = 'active_buys.json'
ACTIVE_BUYS = {}

# Tambahan file untuk unused signals
UNUSED_SIGNAL_FILE = 'unused_signal.json'
UNUSED_SIGNALS = {}

# File cache untuk menyimpan daftar pair top berdasarkan ranking CMC
CACHE_FILE = 'pairs_cache.json'
CACHE_EXPIRED_DAYS = 30  # Cache dianggap kadaluarsa jika lebih dari 30 hari

# Flag untuk mengetahui apakah cache telah diperbarui (misalnya file tidak ada atau sudah kadaluarsa)
CACHE_UPDATED = False

# Konfigurasi jumlah pair untuk cache dan analisis
TOP_PAIRS_CACHED = 200       # Jumlah pair teratas (berdasarkan ranking CMC) yang akan disimpan ke cache
PAIR_TO_ANALYZE = 200         # Dari cache, hanya analisis sejumlah pair tertentu

# Konfigurasi order analisis.
ANALYSIS_ORDER = "top"       # "top" mengambil dari awal, "bottom" dari akhir.

# Parameter trading
TAKE_PROFIT_PERCENTAGE = 6    # Target take profit 6%
STOP_LOSS_PERCENTAGE = 3      # Stop loss 3%
TRAILING_STOP_PERCENTAGE = 3  # Trailing stop 3%
MAX_HOLD_DURATION_DAYS = 2    # Durasi hold maksimum 2 hari

# Konfigurasi Timeframe
TIMEFRAME_ENTRY = Interval.INTERVAL_1_HOUR          # Timeframe untuk analisis entry/pullback (1H)
TIMEFRAME_TREND = Interval.INTERVAL_4_HOURS       # Timeframe untuk analisis tren utama (4H)
TIMEFRAME_KONFIRMASI = Interval.INTERVAL_1_DAY       # Timeframe konfirmasi (1 Day)

##############################
# FUNGSI UTILITY: LOAD & SAVE POSITION
##############################
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
                        'highest_price': d.get('highest_price', None),
                        'exit_flag': d.get('exit_flag', None)
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
                'highest_price': d.get('highest_price', None),
                'exit_flag': d.get('exit_flag', None)
            }
        with open(ACTIVE_BUYS_FILE, 'w') as f:
            json.dump(data, f, indent=4)
        print("✅ Posisi aktif disimpan.")
    except Exception as e:
        print(f"❌ Gagal menyimpan posisi aktif: {e}")

def load_unused_signals():
    """Muat unused signals dari file JSON."""
    global UNUSED_SIGNALS
    if os.path.exists(UNUSED_SIGNAL_FILE):
        try:
            with open(UNUSED_SIGNAL_FILE, 'r') as f:
                data = json.load(f)
                # Konversi string waktu kembali ke datetime
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
    """Simpan unused signals ke file JSON."""
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
    """
    Mengambil data ranking dari CoinMarketCap untuk daftar simbol yang diberikan.
    Mengembalikan dictionary dengan key = simbol, value = cmc_rank.
    """
    print("🔄 Mengambil data ranking dari CoinMarketCap...")
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
    """
    Mengambil semua halaman dari CoinGecko untuk pair Binance,
    memfilter pair dengan target USDT, lalu mengurutkan berdasarkan ranking dari CoinMarketCap,
    dan menyimpannya ke file cache.
    """
    print("🔄 Memperbarui file cache pair...")
    all_tickers = []
    page = 1
    while True:
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

    # Filter pair dengan target USDT
    usdt_tickers = [t for t in all_tickers if t.get('target') == 'USDT']
    print(f"🔍 Total tickers yang diambil: {len(all_tickers)}, setelah difilter USDT: {len(usdt_tickers)}")

    # Ambil daftar simbol unik dari tickers
    symbols = list({t.get('base').upper() for t in usdt_tickers if t.get('base')})
    print(f"🔍 Mengambil data ranking CMC untuk {len(symbols)} simbol: {symbols}")

    # Ambil data ranking dari CMC
    ranking_mapping = get_cmc_rankings(symbols)

    # Urutkan tickers berdasarkan ranking CMC secara ascending (ranking 1 = terbaik)
    sorted_tickers = sorted(usdt_tickers, key=lambda x: ranking_mapping.get(x.get('base').upper(), float('inf')))

    # Ambil TOP_PAIRS_CACHED pair teratas
    top_pairs = sorted_tickers[:TOP_PAIRS_CACHED]

    # Bentuk daftar pair dengan format "BASEUSDT"
    pairs_list = [f"{ticker.get('base').upper()}USDT" for ticker in top_pairs]

    try:
        with open(CACHE_FILE, 'w') as f:
            json.dump(pairs_list, f, indent=4)
        print("✅ File cache pair berhasil diperbarui.")
    except Exception as e:
        print(f"❌ Gagal menyimpan file cache pair: {e}")

def get_pairs_from_cache():
    """
    Memuat daftar pair dari file cache.
    Jika file cache tidak ada atau sudah kadaluarsa, maka file cache akan diperbarui terlebih dahulu.
    """
    global CACHE_UPDATED
    now = datetime.now()
    update_cache = False

    if not os.path.exists(CACHE_FILE):
        update_cache = True
        print("ℹ️ File cache pair tidak ditemukan. Memperbarui cache...")
    else:
        try:
            mtime = os.path.getmtime(CACHE_FILE)
            mod_time = datetime.fromtimestamp(mtime)
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

##############################
# FUNGSI BEST ENTRY & BEST EXIT
##############################
def is_best_entry_from_data(data):
    """
    Evaluasi apakah kondisi best entry terpenuhi.
    """
    candle_entry = data.get('candle_entry')
    if candle_entry is None or (("BUY" not in candle_entry.upper()) and ("STRONG_BUY" not in candle_entry.upper())):
        return False, "Rekomendasi candle tidak mendukung (tidak ada BUY/STRONG_BUY)."

    ema10_entry = data.get('ema10_entry')
    ema20_entry = data.get('ema20_entry')
    if ema10_entry is None or ema20_entry is None or ema10_entry <= ema20_entry:
        return False, "EMA entry tidak memenuhi (EMA10 <= EMA20)."

    macd_entry = data.get('macd_entry')
    macd_signal_entry = data.get('macd_signal_entry')
    if macd_entry is None or macd_signal_entry is None or macd_entry <= macd_signal_entry or macd_entry <= 0:
        return False, "MACD entry tidak memenuhi (tidak > signal atau tidak > 0)."

    macd_trend = data.get('macd_trend')
    macd_signal_trend = data.get('macd_signal_trend')
    if macd_trend is None or macd_signal_trend is None or macd_trend <= macd_signal_trend or macd_trend <= 0:
        return False, "MACD trend tidak memenuhi (MACD trend <= signal trend)."

    macd_konfirmasi = data.get('macd_konfirmasi')
    signal_konfirmasi = data.get('signal_konfirmasi')
    if macd_konfirmasi is None or signal_konfirmasi is None or macd_konfirmasi <= signal_konfirmasi:
        return False, "MACD konfirmasi tidak memenuhi (tidak > signal konfirmasi)."

    return True, "Best Entry Condition terpenuhi."

def is_best_exit_from_data(data):
    """
    Evaluasi apakah kondisi best exit terpenuhi.
    """
    candle_entry = data.get('candle_entry')
    if candle_entry is None or (("SELL" not in candle_entry.upper()) and ("STRONG_SELL" not in candle_entry.upper())):
        return False, "Rekomendasi candle tidak mendukung exit (tidak ada SELL/STRONG_SELL)."

    ema10_entry = data.get('ema10_entry')
    ema20_entry = data.get('ema20_entry')
    if ema10_entry is None or ema20_entry is None or ema10_entry >= ema20_entry:
        return False, "EMA entry tidak mendukung exit (EMA10 >= EMA20)."

    macd_entry = data.get('macd_entry')
    macd_signal_entry = data.get('macd_signal_entry')
    if macd_entry is None or macd_signal_entry is None or macd_entry >= macd_signal_entry:
        return False, "MACD entry tidak mendukung exit (tidak < signal)."

    return True, "Best Exit Condition terpenuhi."

##############################
# GENERATE SINYAL TRADING DENGAN BEST ENTRY & BEST EXIT
##############################
def generate_signal(pair):
    """
    Hasilkan sinyal trading berdasarkan evaluasi best entry atau best exit.
    Mengembalikan tuple (signal, current_price, details, entry_analysis).
    """
    # Analisis timeframe tren dan entry
    trend_analysis = analyze_pair_interval(pair, TIMEFRAME_TREND)
    if trend_analysis is None:
        return None, None, "Analisis tren gagal.", None

    entry_analysis = analyze_pair_interval(pair, TIMEFRAME_ENTRY)
    if entry_analysis is None:
        return None, None, "Analisis entry gagal.", None

    # Analisis timeframe konfirmasi
    konfirmasi_analysis = analyze_pair_interval(pair, TIMEFRAME_KONFIRMASI)
    if konfirmasi_analysis is None:
        return None, None, "Analisis konfirmasi gagal.", None

    current_price = entry_analysis.indicators.get('close')
    if current_price is None:
        return None, None, "Harga close tidak tersedia pada timeframe entry.", entry_analysis

    # Kumpulkan data indikator
    data = {
        'current_price': current_price,
        'ema10_entry': entry_analysis.indicators.get('EMA10'),
        'ema20_entry': entry_analysis.indicators.get('EMA20'),
        'macd_entry': entry_analysis.indicators.get('MACD.macd'),
        'macd_signal_entry': entry_analysis.indicators.get('MACD.signal'),
        'candle_entry': entry_analysis.summary.get('RECOMMENDATION'),
        'macd_trend': trend_analysis.indicators.get('MACD.macd'),
        'macd_signal_trend': trend_analysis.indicators.get('MACD.signal'),
        'macd_konfirmasi': konfirmasi_analysis.indicators.get('MACD.macd'),
        'signal_konfirmasi': konfirmasi_analysis.indicators.get('MACD.signal')
    }

    # Jika pair sudah tercatat di UNUSED_SIGNALS, hanya evaluasi best exit
    if pair in UNUSED_SIGNALS:
        best_exit_ok, best_exit_msg = is_best_exit_from_data(data)
        if best_exit_ok:
            print(f"✅ Pair {pair} dihapus dari unused signals karena best exit terpenuhi (tanpa notifikasi).")
            del UNUSED_SIGNALS[pair]
            return None, current_price, "Best exit terpenuhi, pair dihapus dari unused signals.", entry_analysis
        else:
            return None, current_price, "Tidak ada sinyal (unused signal mode).", entry_analysis

    # Jika pair belum aktif di ACTIVE_BUYS, evaluasi best entry
    if pair not in ACTIVE_BUYS:
        best_entry_ok, best_entry_msg = is_best_entry_from_data(data)
        if best_entry_ok:
            if CACHE_UPDATED:
                UNUSED_SIGNALS[pair] = {
                    'price': current_price,
                    'time': datetime.now()
                }
                print(f"ℹ️ Sinyal BUY untuk {pair} dicatat di UNUSED_SIGNALS (tanpa notifikasi) karena cache diperbarui.")
                return None, current_price, "Buy signal dicatat ke unused_signal.", entry_analysis
            else:
                return "BUY", current_price, f"BEST ENTRY: {best_entry_msg}", entry_analysis
        else:
            return None, current_price, f"Tidak memenuhi best entry: {best_entry_msg}", entry_analysis
    else:
        # Pair sudah aktif di ACTIVE_BUYS
        data_active = ACTIVE_BUYS[pair]
        holding_duration = datetime.now() - data_active['time']
        
        # Evaluasi best exit terlebih dahulu
        best_exit_ok, best_exit_msg = is_best_exit_from_data(data)
        if best_exit_ok:
            if data_active.get('exit_flag') is not None:
                # Jika exit flag sudah aktif, langsung hapus pair tanpa notifikasi
                del ACTIVE_BUYS[pair]
                print(f"✅ Pair {pair} dihapus dari active buys karena exit flag aktif dan best exit terpenuhi.")
                return None, current_price, "Pair dihapus dari active buys karena exit flag aktif.", entry_analysis
            else:
                return "SELL", current_price, f"BEST EXIT: {best_exit_msg}", entry_analysis

        # Selanjutnya, periksa kondisi EXPIRED (dalam satuan days)
        if holding_duration > timedelta(days=MAX_HOLD_DURATION_DAYS):
            if data_active.get('exit_flag') is not None:
                del ACTIVE_BUYS[pair]
                print(f"✅ Pair {pair} dihapus dari active buys karena exit flag aktif dan kondisi EXPIRED terpenuhi.")
                return None, current_price, "Pair dihapus dari active buys (exit flag & expired).", entry_analysis
            else:
                return "EXPIRED", current_price, f"Durasi hold: {holding_duration.days} hari", entry_analysis

        # Jika exit flag sudah aktif (untuk menghindari notifikasi ganda)
        if data_active.get('exit_flag') is not None:
            return None, current_price, "Sinyal exit sudah ditandai, menunggu sinyal SELL/EXPIRED.", entry_analysis

        # Evaluasi kondisi lainnya (stop loss dan trailing stop)
        entry_price = data_active['price']
        profit_from_entry = (current_price - entry_price) / entry_price * 100

        if profit_from_entry <= -STOP_LOSS_PERCENTAGE:
            return "STOP LOSS", current_price, "Stop loss tercapai.", entry_analysis

        if not data_active.get('trailing_stop_active', False) and profit_from_entry >= TAKE_PROFIT_PERCENTAGE:
            ACTIVE_BUYS[pair]['trailing_stop_active'] = True
            ACTIVE_BUYS[pair]['highest_price'] = current_price
            return "TAKE PROFIT", current_price, "Target take profit tercapai, trailing stop diaktifkan.", entry_analysis

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
                return "TRAILING STOP", current_price, f"Harga turun ke trailing stop: {trailing_stop_price:.8f}", entry_analysis

        return None, current_price, "Tidak ada sinyal.", entry_analysis

##############################
# FUNGSI PEMBANTU UNTUK MENGHADIRKAN LINK BINANCE & TRADINGVIEW
##############################
def get_binance_url(pair):
    base = pair[:-4]
    quote = pair[-4:]
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

    # Untuk sinyal BUY, tambahkan data ke ACTIVE_BUYS
    if signal_type == "BUY":
        ACTIVE_BUYS[pair] = {
            'price': current_price,
            'time': datetime.now(),
            'trailing_stop_active': False,
            'highest_price': None,
            'exit_flag': None
        }

    # Jika sinyal bukan BUY dan pair ada di ACTIVE_BUYS,
    # ambil dulu data entry agar dapat ditampilkan di pesan.
    if signal_type != "BUY" and pair in ACTIVE_BUYS:
        entry_data = ACTIVE_BUYS[pair]
        entry_price = entry_data['price']
        profit = (current_price - entry_price) / entry_price * 100
        duration = datetime.now() - entry_data['time']
        message_entry = (
            f"▫️ *Entry Price:* ${entry_price:.8f}\n"
            f"💰 *{'Profit' if profit > 0 else 'Loss'}:* {profit:+.2f}%\n"
            f"🕒 *Duration:* {str(duration).split('.')[0]}\n"
        )
    else:
        message_entry = ""

    message = f"{emoji} *{signal_type}*\n"
    message += f"💱 *Pair:* [{display_pair}]({binance_url}) ==> [TradingView]({tradingview_url})\n"
    message += f"💲 *Price:* ${current_price:.8f}\n"
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

    # Setelah menambahkan informasi entry, baru hapus data untuk sinyal SELL/EXPIRED
    if signal_type in ["SELL", "EXPIRED"]:
        if pair in ACTIVE_BUYS:
            del ACTIVE_BUYS[pair]
            print(f"✅ Posisi {pair} ditutup dari active buys dengan sinyal {signal_type}.")

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

##############################
# PROGRAM UTAMA
##############################
def main():
    load_active_buys()
    load_unused_signals()

    # Ambil daftar pair dari file cache
    pairs = get_pairs_from_cache()

    # Sesuaikan order analisis berdasarkan konfigurasi ANALYSIS_ORDER.
    if PAIR_TO_ANALYZE > 0 and PAIR_TO_ANALYZE < len(pairs):
        if ANALYSIS_ORDER.lower() == "top":
            pairs = pairs[:PAIR_TO_ANALYZE]
        elif ANALYSIS_ORDER.lower() == "bottom":
            pairs = pairs[-PAIR_TO_ANALYZE:]

    print(f"🔍 Memulai analisis {len(pairs)} pair pada {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

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
