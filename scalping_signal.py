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
BUY_SCORE_THRESHOLD = 5  # Diselaraskan dengan kode2 (sebelumnya 4)
SELL_SCORE_THRESHOLD = 4
PROFIT_TARGET_PERCENTAGE = 5   # Target profit 5%
STOP_LOSS_PERCENTAGE = 2       # Stop loss 2%
MAX_HOLD_DURATION_HOUR = 24    # Durasi hold maksimum 24 jam
AUTO_CLOSE_PROFIT_THRESHOLD = 8  # Auto close jika profit absolut > 8%

# Inisialisasi file JSON untuk active buys dengan konversi datetime
if not os.path.exists(ACTIVE_BUYS_FILE):
    with open(ACTIVE_BUYS_FILE, 'w') as f:
        json.dump({}, f)
else:
    with open(ACTIVE_BUYS_FILE, 'r') as f:
        try:
            loaded = json.load(f)
            ACTIVE_BUYS = {
                pair: {
                    'price': data['price'],
                    'time': datetime.fromisoformat(data['time'])
                }
                for pair, data in loaded.items()
            }
        except Exception as e:
            print(f"❌ Error loading active buys: {e}")
            ACTIVE_BUYS = {}

# ==============================
# FUNGSI UTILITAS
# ==============================
def save_active_buys_to_json():
    """Simpan data active buys ke file JSON dengan konversi datetime ke string"""
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
        print(f"❌ Gagal menyimpan active buys: {str(e)}")

def get_binance_top_pairs():
    """Ambil 50 pair teratas berdasarkan volume trading dari Binance (via CoinGecko)"""
    url = "https://api.coingecko.com/api/v3/exchanges/binance/tickers"
    params = {'include_exchange_logo': 'false', 'order': 'volume_desc'}
    try:
        response = requests.get(url, params=params)
        data = response.json()
        usdt_pairs = [t for t in data['tickers'] if t['target'] == 'USDT']
        sorted_pairs = sorted(usdt_pairs, key=lambda x: x['converted_volume']['usd'], reverse=True)[:50]
        return [f"{p['base']}USDT" for p in sorted_pairs]
    except Exception as e:
        print(f"❌ Error fetching top pairs: {e}")
        return []

# ==============================
# FUNGSI ANALISIS (berdasarkan kode1)
# ==============================
def analyze_pair(symbol):
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
    if val1 is not None and val2 is not None:
        if operator == '>':
            return val1 > val2
        elif operator == '<':
            return val1 < val2
    return False

def calculate_scores(data):
    # Hitung skor beli dan jual berdasarkan indikator
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

    buy_conditions = [
        safe_compare(ema5_m5, ema10_m5, '>'),
        safe_compare(ema10_m15, ema20_m15, '>'),
        safe_compare(ema10_h1, ema20_h1, '>'),
        (rsi_m5 is not None and rsi_m5 < 30),
        safe_compare(macd_m5, macd_signal_m5, '>'),
        (current_price <= bb_lower_m5 if bb_lower_m5 is not None else False),
        (adx_m5 is not None and adx_m5 > 25),
        (("BUY" in candle_m5 or "STRONG_BUY" in candle_m5) if candle_m5 else False),
        (stoch_k_m5 is not None and stoch_k_m5 < 20 and stoch_d_m5 is not None and stoch_d_m5 < 20)
    ]

    sell_conditions = [
        safe_compare(ema5_m5, ema10_m5, '<'),
        safe_compare(ema10_m15, ema20_m15, '<'),
        safe_compare(ema10_h1, ema20_h1, '<'),
        (rsi_m5 is not None and rsi_m5 > 70),
        safe_compare(macd_m5, macd_signal_m5, '<'),
        (current_price >= bb_upper_m5 if bb_upper_m5 is not None else False),
        (adx_m5 is not None and adx_m5 > 25),
        (("SELL" in candle_m5 or "STRONG_SELL" in candle_m5) if candle_m5 else False),
        (stoch_k_m5 is not None and stoch_k_m5 > 80 and stoch_d_m5 is not None and stoch_d_m5 > 80)
    ]

    return sum(buy_conditions), sum(sell_conditions)

# ==============================
# FUNGSI TRADING
# ==============================
def generate_signal(pair, data):
    """
    Hasilkan sinyal trading berdasarkan:
      - Jika belum ada posisi aktif: sinyal BUY bila skor beli mencapai threshold.
      - Jika sudah ada posisi aktif: cek TAKE PROFIT, STOP LOSS, atau auto-close (SELL) jika hold > 24 jam atau profit/loss > 8%.
    """
    current_price = data['current_price']
    buy_score, sell_score = calculate_scores(data)
    display_pair = f"{pair[:-4]}/USDT"
    print(f"{display_pair} - Price: {current_price:.8f} | Buy: {buy_score}/9 | Sell: {sell_score}/9")

    # Jika belum ada posisi, cek sinyal BUY
    if pair not in ACTIVE_BUYS:
        if buy_score >= BUY_SCORE_THRESHOLD:
            return 'BUY', current_price
        else:
            return None, None

    # Jika sudah ada posisi aktif
    entry_price = ACTIVE_BUYS[pair]['price']
    take_profit = current_price >= entry_price * (1 + PROFIT_TARGET_PERCENTAGE / 100)
    stop_loss = current_price <= entry_price * (1 - STOP_LOSS_PERCENTAGE / 100)
    hold_duration = datetime.now() - ACTIVE_BUYS[pair]['time']
    profit = (current_price - entry_price) / entry_price * 100

    if take_profit:
        return 'TAKE PROFIT', current_price
    if stop_loss:
        return 'STOP LOSS', current_price
    if hold_duration > timedelta(hours=MAX_HOLD_DURATION_HOUR) or abs(profit) > AUTO_CLOSE_PROFIT_THRESHOLD:
        return 'SELL', entry_price
    if sell_score >= SELL_SCORE_THRESHOLD:
        return 'SELL', entry_price

    return None, None

def send_telegram_alert(signal_type, pair, current_price, data, buy_score, sell_score, buy_price=None):
    """Kirim notifikasi ke Telegram berdasarkan sinyal trading"""
    display_pair = f"{pair[:-4]}/USDT"
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
    base_msg += f"📊 Score: Buy {buy_score}/9 | Sell {sell_score}/9\n"

    if signal_type == 'BUY':
        message = f"{base_msg}🔍 RSI: M5 = {data['rsi_m5']:.2f} | M15 = {data['rsi_m15']:.2f}\n"
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
        else:
            message = base_msg
    else:
        message = base_msg

    print(f"📢 Mengirim alert: {message}")
    try:
        save_active_buys_to_json()
    except Exception as e:
        print(f"❌ Gagal menyimpan active buys: {str(e)}")

    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'Markdown'}
        )
    except Exception as e:
        print(f"❌ Gagal mengirim alert ke Telegram: {e}")

# ==============================
# FUNGSI UTAMA
# ==============================
def main():
    """Program utama untuk analisis dan sinyal trading"""
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
            buy_score, sell_score = calculate_scores(data)

            if signal:
                send_telegram_alert(signal, pair, current_price, data, buy_score, sell_score)

            # Opsional: cek ulang kondisi auto close untuk posisi aktif (durasi > 24 jam atau profit/loss > 8%)
            if pair in ACTIVE_BUYS:
                entry = ACTIVE_BUYS[pair]
                hold_duration = datetime.now() - entry['time']
                profit = ((data['current_price'] - entry['price']) / entry['price']) * 100
                if (hold_duration > timedelta(hours=MAX_HOLD_DURATION_HOUR) or
                    abs(profit) > AUTO_CLOSE_PROFIT_THRESHOLD) and (signal is None):
                    send_telegram_alert('SELL', pair, data['current_price'], data, buy_score, sell_score)
        except Exception as e:
            print(f"⚠️ Error di {pair}: {str(e)}")
            continue

if __name__ == "__main__":
    main()
