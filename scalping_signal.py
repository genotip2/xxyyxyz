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
BUY_SCORE_THRESHOLD = 5
SELL_SCORE_THRESHOLD = 4
FILE_PATH = 'active_buys.json'

# Inisialisasi file JSON dengan handling datetime
if not os.path.exists(FILE_PATH):
    with open(FILE_PATH, 'w') as f:
        json.dump({}, f)
else:
    with open(FILE_PATH, 'r') as f:
        loaded = json.load(f)
        ACTIVE_BUYS = {
            pair: {
                'price': data['close_price_m15'],
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
                'price': data['close_price_m15'],
                'time': data['time'].isoformat()
            }
            
        with open(FILE_PATH, 'w') as f:
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
                            reverse=True)[:50]
        return [f"{p['base']}USDT" for p in sorted_pairs]
    
    except Exception as e:
        print(f"❌ Error fetching data: {e}")
        return []
      
# ==============================
# FUNGSI ANALISIS
# ==============================
def analyze_pair(symbol):
    try:
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

        analysis_m15 = handler_m15.get_analysis()
        analysis_h1 = handler_h1.get_analysis()

        return {
                'ema9_m15': analysis_m15.indicators.get('EMA9'),
                'ema21_m15': analysis_m15.indicators.get('EMA21'),
                'rsi_m15': analysis_m15.indicators.get('RSI'),
                'macd_m15': analysis_m15.indicators.get('MACD.macd'),
                'macd_signal_m15': analysis_m15.indicators.get('MACD.signal'),
                'bb_lower_m15': analysis_m15.indicators.get('BB.lower'),
                'bb_upper_m15': analysis_m15.indicators.get('BB.upper'),
                'close_price_m15': analysis_m15.indicators.get('close'),
                'adx_m15': analysis_m15.indicators.get('ADX'),
                'obv_m15': analysis_m15.indicators.get('OBV'),
                'candle_m15': analysis_m15.summary['RECOMMENDATION'],

                'ema9_h1': analysis_h1.indicators.get('EMA9'),
                'ema21_h1': analysis_h1.indicators.get('EMA21'),
                'rsi_h1': analysis_h1.indicators.get('RSI'),
                'macd_h1': analysis_h1.indicators.get('MACD.macd'),
                'macd_signal_h1': analysis_h1.indicators.get('MACD.signal'),
                'bb_lower_h1': analysis_h1.indicators.get('BB.lower'),
                'bb_upper_h1': analysis_h1.indicators.get('BB.upper'),
                'close_price_h1': analysis_h1.indicators.get('close'),
                'adx_h1': analysis_h1.indicators.get('ADX'),
                'obv_h1': analysis_h1.indicators.get('OBV'),
                'candle_h1': analysis_h1.summary['RECOMMENDATION']
         }
         
    except Exception as e:
        print(f"⚠️ Error analisis {symbol}: {str(e)}")
        return None

# ==============================
# FUNGSI TRADING
# ==============================
def generate_signal(pair, data):
    """Generate trading signal"""
    ema9_m15 = data.get('ema9_m15', None)
    ema21_m15 = data.get('ema21_m15', None)
    rsi_m15 = data.get('rsi_m15', None)
    macd_m15 = data.get('macd_m15', None)
    macd_signal_m15 = data.get('macd_signal_m15', None)
    bb_lower_m15 = data.get('bb_lower_m15', None)
    bb_upper_m15 = data.get('bb_upper_m15', None)
    close_price_m15 = data.get('close_price_m15', None)
    adx_m15 = data.get('adx_m15', None)
    obv_m15 = data.get('obv_m15', None)
    candle_m15 = data.get('candle_m15', '')

    ema9_h1 = data.get('ema9_h1', None)
    ema21_h1 = data.get('ema21_h1', None)
    rsi_h1 = data.get('rsi_h1', None)
    macd_h1 = data.get('macd_h1', None)
    macd_signal_h1 = data.get('macd_signal_h1', None)
    bb_lower_h1 = data.get('bb_lower_h1', None)
    bb_upper_h1 = data.get('bb_upper_h1', None)
    close_price_h1 = data.get('close_price_h1', None)
    adx_h1 = data.get('adx_h1', None)
    obv_h1 = data.get('obv_h1', None)
    candle_h1 = data.get('candle_h1', '')

    # Pastikan semua nilai bukan None sebelum dibandingkan
    if None in [ema9_m15, ema21_m15, rsi_m15, macd_m15, macd_signal_m15,
                bb_lower_m15, bb_upper_m15, close_price_m15, adx_m15, obv_m15,
                ema9_h1, ema21_h1, rsi_h1, macd_h1, macd_signal_h1,
                bb_lower_h1, bb_upper_h1, close_price_h1, adx_h1, obv_h1]:
        print(f"⚠️ Data tidak lengkap untuk {pair}, dilewati.")
        return None, None

    price = close_price_m15  # Harga terakhir

    buy_signal = (
        ema9_m15 > ema21_m15 and ema9_h1 > ema21_h1 and
        rsi_m15 < 30 and rsi_h1 < 50 and
        macd_m15 > macd_signal_m15 and macd_h1 > macd_signal_h1 and
        close_price_m15 <= bb_lower_m15 and close_price_h1 <= bb_lower_h1 and
        adx_m15 > 25 and adx_h1 > 25 and
        obv_m15 > 0 and obv_h1 > 0 and
        ("BUY" in candle_m15 or "STRONG_BUY" in candle_m15) and
        ("BUY" in candle_h1 or "STRONG_BUY" in candle_h1) and
        pair not in ACTIVE_BUYS
    )

    sell_signal = (
        ema9_m15 < ema21_m15 and ema9_h1 < ema21_h1 and
        rsi_m15 > 70 and rsi_h1 > 50 and
        macd_m15 < macd_signal_m15 and macd_h1 < macd_signal_h1 and
        close_price_m15 >= bb_upper_m15 and close_price_h1 >= bb_upper_h1 and
        adx_m15 > 25 and adx_h1 > 25 and
        obv_m15 < 0 and obv_h1 < 0 and
        ("SELL" in candle_m15 or "STRONG_SELL" in candle_m15) and
        ("SELL" in candle_h1 or "STRONG_SELL" in candle_h1) and
        pair in ACTIVE_BUYS
    )

    take_profit = pair in ACTIVE_BUYS and price > ACTIVE_BUYS[pair]['price'] * 1.05
    stop_loss = pair in ACTIVE_BUYS and price < ACTIVE_BUYS[pair]['price'] * 0.98

    if buy_signal:
        return 'BUY', price
    elif take_profit:
        return 'TAKE PROFIT', price
    elif stop_loss:
        return 'STOP LOSS', price
    elif sell_signal:
        return 'SELL', ACTIVE_BUYS[pair]['price']

    return None, None

def send_telegram_alert(signal_type, pair, price, data, buy_price=None):
    """Kirim notifikasi ke Telegram"""
    display_pair = f"{pair[:-4]}/USDT"
    message = ""
    
    emoji = {
        'BUY': '🚀', 
        'SELL': '⚠️', 
        'TAKE PROFIT': '✅', 
        'STOP LOSS': '🛑'
    }.get(signal_type, 'ℹ️')

    base_msg = f"{emoji} **{signal_type}**\n"
    base_msg += f"💱 {display_pair}\n"
    base_msg += f"💲 Price: ${price:.8f}\n"

    if signal_type == 'BUY':
        message = f"{base_msg}🔍 RSI: {data['rsi']:.1f}\n"
        ACTIVE_BUYS[pair] = {'price': current_price, 'time': datetime.now()}

    elif signal_type in ['TAKE PROFIT', 'STOP LOSS', 'SELL']:
        entry = ACTIVE_BUYS.get(pair)
        if entry:
            profit = ((current_price - entry['close_price_m15'])/entry['close_price_m15'])*100
            duration = str(datetime.now() - entry['time']).split('.')[0]
            
            message = f"{base_msg}💲 Entry: ${entry['close_price_m15']:.8f}\n"
            message += f"💰 {'Profit' if profit > 0 else 'Loss'}: {profit:+.2f}%\n"
            message += f"🕒 Hold Duration: {duration}"

            if signal_type in ['STOP LOSS', 'SELL']:
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
            
            signal, price = generate_signal(pair, data)
            if signal:
                send_telegram_alert(signal, pair, data['close_price_m15'], data, price)
                
            # Auto close position
            if pair in ACTIVE_BUYS:
                position = ACTIVE_BUYS[pair]
                duration = datetime.now() - position['time']
                profit = (data['close_price_m15'] - position['close_price_m15'])/position['close_price_m15']*100
                
                if duration > timedelta(hours=24) or abs(profit) > 8:
                    send_telegram_alert('SELL', pair, data['close_price_m15'], data, position['close_price_m15'])
                    
        except Exception as e:
            print(f"⚠️ Error di {pair}: {str(e)}")
            continue

if __name__ == "__main__":
    main()
