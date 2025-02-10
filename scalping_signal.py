import os
import requests
from tradingview_ta import TA_Handler, Interval
from datetime import datetime, timedelta
import json

# ==============================
# KONFIGURASI
# ==============================

TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
ACTIVE_BUYS = {}
ACTIVE_BUYS_FILE = 'active_buys.json'
BUY_SCORE_THRESHOLD = 5
SELL_SCORE_THRESHOLD = 4
PROFIT_TARGET_PERCENTAGE = 5    # Target profit 5%
STOP_LOSS_PERCENTAGE = 2        # Stop loss 2%
MAX_HOLD_DURATION_HOUR = 24     # Durasi hold maksimum 24 jam
PAIR_TO_ANALIZE = 100

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
    """Simpan data active buys dengan mengonversi datetime ke string."""
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
    """Ambil 50 pair teratas berdasarkan volume trading dari Binance melalui CoinGecko."""
    url = "https://api.coingecko.com/api/v3/exchanges/binance/tickers"
    params = {'include_exchange_logo': 'false', 'order': 'volume_desc'}
    try:
        response = requests.get(url, params=params)
        data = response.json()
        usdt_pairs = [t for t in data['tickers'] if t['target'] == 'USDT']
        sorted_pairs = sorted(usdt_pairs, key=lambda x: x['converted_volume']['usd'], reverse=True)[:PAIR_TO_ANALIZE]
        return [f"{p['base']}USDT" for p in sorted_pairs]
    except Exception as e:
        print(f"❌ Error fetching data: {e}")
        return []

def analyze_pair(symbol):
    """Lakukan analisis teknikal pada pair dengan berbagai time frame."""
    try:
        handler_m1 = TA_Handler(
            symbol=symbol,
            exchange="BINANCE",
            screener="CRYPTO",
            interval=Interval.INTERVAL_1_MINUTE
        )
        handler_m5 = TA_Handler(
            symbol=symbol,
            exchange="BINANCE",
            screener="CRYPTO",
            interval=Interval.INTERVAL_5_MINUTES
        )
        handler_m15 = TA_Handler(
            symbol=symbol,
            exchange="BINANCE",
            screener="CRYPTO",
            interval=Interval.INTERVAL_15_MINUTES
        )
        handler_h1 = TA_Handler(
            symbol=symbol,
            exchange="BINANCE",
            screener="CRYPTO",
            interval=Interval.INTERVAL_1_HOUR
        )

        analysis_m1 = handler_m1.get_analysis()  
        analysis_m5 = handler_m5.get_analysis()  
        analysis_m15 = handler_m15.get_analysis()  
        analysis_h1 = handler_h1.get_analysis()  

        return {  
            # Gunakan key 'current_price' untuk harga saat ini (diambil dari analisis 5 menit)  
            'current_price': analysis_m5.indicators.get('close'),  
            'ema5_m5': analysis_m5.indicators.get('EMA5'),  
            'ema10_m5': analysis_m5.indicators.get('EMA10'),  
            'rsi_m5': analysis_m5.indicators.get('RSI'),  
            'macd_m5': analysis_m5.indicators.get('MACD.macd'),  
            'macd_signal_m5': analysis_m5.indicators.get('MACD.signal'),  
            'bb_lower_m5': analysis_m5.indicators.get('BB.lower'),  
            'bb_upper_m5': analysis_m5.indicators.get('BB.upper'),  
            'adx_m5': analysis_m5.indicators.get('ADX'),  
            'obv_m5': analysis_m5.indicators.get('OBV'),  
            'candle_m5': analysis_m5.summary.get('RECOMMENDATION'),  
            'stoch_k_m5': analysis_m5.indicators.get('Stoch.K'),  
            'stoch_d_m5': analysis_m5.indicators.get('Stoch.D'),  

            'ema10_m15': analysis_m15.indicators.get('EMA10'),  
            'ema20_m15': analysis_m15.indicators.get('EMA20'),  
            'rsi_m15': analysis_m15.indicators.get('RSI'),  
            'macd_m15': analysis_m15.indicators.get('MACD.macd'),  
            'macd_signal_m15': analysis_m15.indicators.get('MACD.signal'),  
            'bb_lower_m15': analysis_m15.indicators.get('BB.lower'),  
            'bb_upper_m15': analysis_m15.indicators.get('BB.upper'),  
            'adx_m15': analysis_m15.indicators.get('ADX'),  
            'obv_m15': analysis_m15.indicators.get('OBV'),  
            'candle_m15': analysis_m15.summary.get('RECOMMENDATION'),  

            'ema10_h1': analysis_h1.indicators.get('EMA10'),  
            'ema20_h1': analysis_h1.indicators.get('EMA20'),  
            'rsi_h1': analysis_h1.indicators.get('RSI'),  
            'macd_h1': analysis_h1.indicators.get('MACD.macd'),  
            'macd_signal_h1': analysis_h1.indicators.get('MACD.signal'),  
            'bb_lower_h1': analysis_h1.indicators.get('BB.lower'),  
            'bb_upper_h1': analysis_h1.indicators.get('BB.upper'),  
            'adx_h1': analysis_h1.indicators.get('ADX'),  
            'obv_h1': analysis_h1.indicators.get('OBV'),  
            'candle_h1': analysis_h1.summary.get('RECOMMENDATION')  
        }  
    except Exception as e:  
        print(f"⚠️ Error analisis {symbol}: {str(e)}")  
        return None

def safe_compare(val1, val2, operator='>'):
    """Bandingkan dua nilai secara aman (jika keduanya tidak None)."""
    if val1 is not None and val2 is not None:
        if operator == '>':
            return val1 > val2
        elif operator == '<':
            return val1 < val2
    return False

def calculate_scores(data):
    """
    Hitung skor beli dan jual berdasarkan indikator teknikal dan kembalikan juga
    daftar indikator yang terpenuhi untuk masing-masing kondisi.
    """
    current_price = data['current_price']
    ema5_m5 = data['ema5_m5']
    ema10_m5 = data['ema10_m5']
    rsi_m5 = data['rsi_m5']
    macd_m5 = data['macd_m5']
    macd_signal_m5 = data['macd_signal_m5']
    bb_lower_m5 = data['bb_lower_m5']
    bb_upper_m5 = data['bb_upper_m5']
    adx_m5 = data['adx_m5']
    obv_m5 = data['obv_m5']
    candle_m5 = data['candle_m5']
    stoch_k_m5 = data['stoch_k_m5']
    stoch_d_m5 = data['stoch_d_m5']

    ema10_m15 = data['ema10_m15']  
    ema20_m15 = data['ema20_m15']  
    rsi_m15 = data['rsi_m15']  
    macd_m15 = data['macd_m15']  
    macd_signal_m15 = data['macd_signal_m15']  
    bb_lower_m15 = data['bb_lower_m15']  
    bb_upper_m15 = data['bb_upper_m15']  
    adx_m15 = data['adx_m15']  
    obv_m15 = data['obv_m15']  
    candle_m15 = data['candle_m15']  

    ema10_h1 = data['ema10_h1']  
    ema20_h1 = data['ema20_h1']  
    rsi_h1 = data['rsi_h1']  
    macd_h1 = data['macd_h1']  
    macd_signal_h1 = data['macd_signal_h1']  
    bb_lower_h1 = data['bb_lower_h1']  
    bb_upper_h1 = data['bb_upper_h1']  
    adx_h1 = data['adx_h1']  
    obv_h1 = data['obv_h1']  
    candle_h1 = data['candle_h1']  

    # Buat list tuple: (kondisi_boolean, deskripsi indikator)
    buy_conditions = [
        (safe_compare(ema5_m5, ema10_m5, '>'), "EMA5 M5 > EMA10 M5"),
        (safe_compare(ema10_m15, ema20_m15, '>'), "EMA10 M15 > EMA20 M15"),
        (safe_compare(ema10_h1, ema20_h1, '>'), "EMA10 H1 > EMA20 H1"),
        ((rsi_m5 is not None and rsi_m5 < 30), "RSI M5 < 30"),
        (safe_compare(macd_m5, macd_signal_m5, '>'), "MACD M5 > Signal M5"),
        ((bb_lower_m5 is not None and current_price <= bb_lower_m5), "Price <= BB Lower M5"),
        ((adx_m5 is not None and adx_m5 > 25), "ADX M5 > 25"),
        ((candle_m5 is not None and ("BUY" in candle_m5 or "STRONG_BUY" in candle_m5)), "Candle M5 mengindikasikan BUY"),
        ((stoch_k_m5 is not None and stoch_k_m5 < 20 and stoch_d_m5 is not None and stoch_d_m5 < 20), "Stoch RSI M5 < 20")
    ]

    sell_conditions = [
        (safe_compare(ema5_m5, ema10_m5, '<'), "EMA5 M5 < EMA10 M5"),
        (safe_compare(ema10_m15, ema20_m15, '<'), "EMA10 M15 < EMA20 M15"),
        (safe_compare(ema10_h1, ema20_h1, '<'), "EMA10 H1 < EMA20 H1"),
        ((rsi_m5 is not None and rsi_m5 > 70), "RSI M5 > 70"),
        (safe_compare(macd_m5, macd_signal_m5, '<'), "MACD M5 < Signal M5"),
        ((bb_upper_m5 is not None and current_price >= bb_upper_m5), "Price >= BB Upper M5"),
        ((adx_m5 is not None and adx_m5 > 25), "ADX M5 > 25"),
        ((candle_m5 is not None and ("SELL" in candle_m5 or "STRONG_SELL" in candle_m5)), "Candle M5 mengindikasikan SELL"),
        ((stoch_k_m5 is not None and stoch_k_m5 > 80 and stoch_d_m5 is not None and stoch_d_m5 > 80), "Stoch RSI M5 > 80")
    ]

    buy_score = sum(1 for cond, _ in buy_conditions if cond)
    sell_score = sum(1 for cond, _ in sell_conditions if cond)
    buy_met = [desc for cond, desc in buy_conditions if cond]
    sell_met = [desc for cond, desc in sell_conditions if cond]

    return buy_score, sell_score, buy_met, sell_met

# ==============================
# FUNGSI TRADING
# ==============================

def generate_signal(pair, data):
    """Generate trading signal berdasarkan skor dan posisi aktif."""
    current_price = data['current_price']
    buy_score, sell_score, buy_met, sell_met = calculate_scores(data)
    display_pair = f"{pair[:-4]}/USDT"

    print(f"{display_pair} - Price: {current_price:.8f} | Buy: {buy_score}/9 | Sell: {sell_score}/9")
    print(f"  Triggered Buy Indicators: {', '.join(buy_met) if buy_met else 'None'}")
    print(f"  Triggered Sell Indicators: {', '.join(sell_met) if sell_met else 'None'}")

    buy_signal = buy_score >= BUY_SCORE_THRESHOLD and pair not in ACTIVE_BUYS  
    sell_signal = sell_score >= SELL_SCORE_THRESHOLD and pair in ACTIVE_BUYS  

    # Perhitungan take profit dan stop loss
    take_profit = pair in ACTIVE_BUYS and current_price > ACTIVE_BUYS[pair]['price'] * (1 + PROFIT_TARGET_PERCENTAGE / 100)
    stop_loss = pair in ACTIVE_BUYS and current_price < ACTIVE_BUYS[pair]['price'] * (1 - STOP_LOSS_PERCENTAGE / 100)

    if buy_signal:
        return 'BUY', current_price
    elif take_profit:
        return 'TAKE PROFIT', current_price
    elif stop_loss:
        return 'STOP LOSS', current_price
    elif sell_signal:
        return 'SELL', current_price

    return None, None

def send_telegram_alert(signal_type, pair, current_price, data, buy_price=None):
    """Kirim notifikasi ke Telegram dan perbarui active buys."""
    display_pair = f"{pair[:-4]}/USDT"
    message = ""
    buy_score, sell_score, buy_met, sell_met = calculate_scores(data)

    emoji = {
        'BUY': '🚀',
        'SELL': '⚠️',
        'TAKE PROFIT': '✅',
        'STOP LOSS': '🛑',
        'EXPIRED': '⌛'
    }.get(signal_type, 'ℹ️')

    base_msg = f"{emoji} *{signal_type}*\n"
    base_msg += f"💱 *{display_pair}*\n"
    base_msg += f"💲 *Price:* ${current_price:.8f}\n"
    base_msg += f"📊 *Score:* Buy {buy_score}/9 | Sell {sell_score}/9\n"

    if signal_type == 'BUY':
        message = base_msg
        message += f"🔍 *RSI:* M5 = {data['rsi_m5']:.2f} | M15 = {data['rsi_m15']:.2f}\n"
        message += f"🔍 *Stoch RSI:* {data['stoch_k_m5']:.2f}\n"
        message += "\n*Triggered Buy Indicators:*\n" + ("\n".join(f"- {i}" for i in buy_met) if buy_met else "None")
        # Simpan posisi beli
        ACTIVE_BUYS[pair] = {'price': current_price, 'time': datetime.now()}

    elif signal_type in ['TAKE PROFIT', 'STOP LOSS', 'SELL']:
        entry = ACTIVE_BUYS.get(pair)
        if entry:
            profit = ((current_price - entry['price']) / entry['price']) * 100
            duration = str(datetime.now() - entry['time']).split('.')[0]
            message = base_msg
            message += f"▫️ *Entry:* ${entry['price']:.8f}\n"
            message += f"💰 *{'Profit' if profit > 0 else 'Loss'}:* {profit:+.2f}%\n"
            message += f"🕒 *Durasi:* {duration}\n"
            message += "\n*Triggered Sell Indicators:*\n" + ("\n".join(f"- {i}" for i in sell_met) if sell_met else "None")
            if pair in ACTIVE_BUYS:
                del ACTIVE_BUYS[pair]

    elif signal_type == 'EXPIRED':
        entry = ACTIVE_BUYS.get(pair)
        if entry:
            profit = ((current_price - entry['price']) / entry['price']) * 100
            duration = str(datetime.now() - entry['time']).split('.')[0]
            message = base_msg
            message += f"▫️ *Entry:* ${entry['price']:.8f}\n"
            message += f"⌛ *Order Expired After:* {duration}\n"
            message += f"💰 *{'Profit' if profit > 0 else 'Loss'}:* {profit:+.2f}%\n"
            message += "\n*Triggered Sell Indicators:*\n" + ("\n".join(f"- {i}" for i in sell_met) if sell_met else "None")
            if pair in ACTIVE_BUYS:
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

            # Tampilkan indikator yang terpenuhi di halaman utama (console)
            buy_score, sell_score, buy_met, sell_met = calculate_scores(data)
            print(f"  Triggered Buy Indicators: {', '.join(buy_met) if buy_met else 'None'}")
            print(f"  Triggered Sell Indicators: {', '.join(sell_met) if sell_met else 'None'}")

            signal, current_price = generate_signal(pair, data)
            if signal:
                send_telegram_alert(signal, pair, current_price, data, buy_price=current_price)

            # Auto close posisi berdasarkan durasi hold maksimum
            if pair in ACTIVE_BUYS:
                entry = ACTIVE_BUYS.get(pair)
                duration = datetime.now() - entry['time']
                if duration > timedelta(hours=MAX_HOLD_DURATION_HOUR):
                    send_telegram_alert('EXPIRED', pair, data['current_price'], data, entry['price'])

        except Exception as e:
            print(f"⚠️ Error di {pair}: {str(e)}")
            continue

if __name__ == "__main__":
    main()
