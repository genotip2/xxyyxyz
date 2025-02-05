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

        analysis_m15 = handler_m15.get_analysis()

        return {
                'ema9_m15': analysis_m15.indicators.get('EMA9'),
                'ema21_m15': analysis_m15.indicators.get('EMA21'),
                'rsi_m15': analysis_m15.indicators.get('RSI'),
                'macd_m15': analysis_m15.indicators.get('MACD.MACD'),
                'macd_signal_m15': analysis_m15.indicators.get('MACD.signal'),
                'bb_lower_m15': analysis_m15.indicators.get('BB.lower'),
                'bb_upper_m15': analysis_m15.indicators.get('BB.upper'),
                'close_price_m15': analysis_m15.indicators.get('close'),
                'adx_m15': analysis_m15.indicators.get('ADX'),
                'obv_m15': analysis_m15.indicators.get('OBV'),
                'candle_m15': analysis_m15.summary['RECOMMENDATION']
         }
         
    except Exception as e:
        print(f"⚠️ Error analisis {symbol}: {str(e)}")
        return None

# ==============================
# FUNGSI TRADING
# ==============================
def generate_signal(pair, data):
    """Generate trading signal"""
    price = data['close_price_m15']
    ema9_m15 = data['ema9_m15']
    ema21_m15 = data['ema21_m15']
    rsi_m15 = data['rsi_m15']
    macd_m15 = data['macd_m15']
    macd_signal_m15 = data['macd_signal_m15']
    bb_lower_m15 = data['bb_lower_m15']
    bb_upper_m15 = data['bb_upper_m15']
    close_price_m15 = data['close_price_m15']
    adx_m15 = data['adx_m15']
    obv_m15 = data['obv_m15']
    candle_m15 = data['candle_m15']
    
    buy_signal = (
            ema9_m15 > ema21_m15 and  # EMA 9 cross up EMA 21 di M15
            rsi_m15 < 30 and  # RSI M15 oversold
            macd_m15 > macd_signal_m15 and  # MACD bullish crossover di M15
            close_price_m15 <= bb_lower_m15 and  # Harga di lower Bollinger Band
            adx_m15 > 25 and  # ADX menunjukkan tren kuat di M15
            obv_m15 > 0 and  # OBV meningkat di M15
            ("BUY" in candle_m15 or "STRONG_BUY" in candle_m15) and  # Candlestick reversal di M15
            pair not in ACTIVE_BUYS
        )
    sell_signal = (
            ema9_m15 < ema21_m15 and  # EMA 9 cross down EMA 21 di M15
            rsi_m15 > 70 and  # RSI M15 overbought
            macd_m15 < macd_signal_m15 and  # MACD bearish crossover di M15
            close_price_m15 >= bb_upper_m15 and  # Harga di upper Bollinger Band
            adx_m15 > 25 and  # ADX menunjukkan tren kuat di M15
            obv_m15 < 0 and  # OBV menurun di M15
            ("SELL" in candle_m15 or "STRONG_SELL" in candle_m15) and  # Candlestick reversal di M15
            pair in ACTIVE_BUYS
        )
    take_profit = pair in ACTIVE_BUYS and price > ACTIVE_BUYS[pair]['close_price_m15'] * 1.05
    stop_loss = pair in ACTIVE_BUYS and price < ACTIVE_BUYS[pair]['close_price_m15'] * 0.98

    if buy_signal:
        return 'BUY', price
    elif take_profit:
        return 'TAKE PROFIT', price
    elif stop_loss:
        return 'STOP LOSS', price
    elif sell_signal:
        return 'SELL', ACTIVE_BUYS[pair]['close_price_m15']
    
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
        message = f"{base_msg}🔍 RSI: {data['rsi_m15']:.1f}\n"
        ACTIVE_BUYS[pair] = {'price': price, 'time': datetime.now()}

    elif signal_type in ['TAKE PROFIT', 'STOP LOSS', 'SELL']:
        entry = ACTIVE_BUYS.get(pair)
        if entry:
            profit = ((price - entry['close_price_m15']) / entry['close_price_m15']) * 100
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
                profit = (data['close_price_m15'] - position['close_price_m15']) / position['close_price_m15'] * 100
                
                if duration > timedelta(hours=24) or abs(profit) > 8:
                    send_telegram_alert('SELL', pair, data['close_price_m15'], data, position['close_price_m15'])
                    
        except Exception as e:
            print(f"⚠️ Error di {pair}: {str(e)}")
            continue

if __name__ == "__main__":
    main()
