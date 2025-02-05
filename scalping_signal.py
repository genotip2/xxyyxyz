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
                'price': data['price'],
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
                'price': data['price'],
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
            symbol=symbol.replace("USDT", ""),
            exchange="BINANCE",
            screener="crypto",
            interval=Interval.INTERVAL_15_MINUTE
        )
        handler_h1 = TA_Handler(
            symbol=symbol.replace("USDT", ""),
            exchange="BINANCE",
            screener="crypto",
            interval=Interval.INTERVAL_1_HOUR
        )

        analysis_m15 = handler_m15.get_analysis()
        analysis_h1 = handler_h1.get_analysis()

        # Data indikator M15
        ema9_m15 = analysis_m15.indicators["EMA9"]
        ema21_m15 = analysis_m15.indicators["EMA21"]
        rsi_m15 = analysis_m15.indicators["RSI"]
        macd_m15 = analysis_m15.indicators["MACD.macd"]
        macd_signal_m15 = analysis_m15.indicators["MACD.signal"]
        bb_lower_m15 = analysis_m15.indicators["BB.lower"]
        bb_upper_m15 = analysis_m15.indicators["BB.upper"]
        close_price_m15 = analysis_m15.indicators["close"]
        adx_m15 = analysis_m15.indicators["ADX"]
        obv_m15 = analysis_m15.indicators["OBV"]
        candle_m15 = analysis_m15.summary["RECOMMENDATION"]

        # Data indikator H1
        ema9_h1 = analysis_h1.indicators["EMA9"]
        ema21_h1 = analysis_h1.indicators["EMA21"]
        rsi_h1 = analysis_h1.indicators["RSI"]
        macd_h1 = analysis_h1.indicators["MACD.macd"]
        macd_signal_h1 = analysis_h1.indicators["MACD.signal"]
        bb_lower_h1 = analysis_h1.indicators["BB.lower"]
        bb_upper_h1 = analysis_h1.indicators["BB.upper"]
        close_price_h1 = analysis_h1.indicators["close"]
        adx_h1 = analysis_h1.indicators["ADX"]
        obv_h1 = analysis_h1.indicators["OBV"]
        candle_h1 = analysis_h1.summary["RECOMMENDATION"]

        # Kembalikan hasil analisis sebagai dictionary
        return {
            "M15": {
                "EMA9": ema9_m15,
                "EMA21": ema21_m15,
                "RSI": rsi_m15,
                "MACD": macd_m15,
                "MACD_signal": macd_signal_m15,
                "BB_lower": bb_lower_m15,
                "BB_upper": bb_upper_m15,
                "Close_price": close_price_m15,
                "ADX": adx_m15,
                "OBV": obv_m15,
                "Candle": candle_m15
            },
            "H1": {
                "EMA9": ema9_h1,
                "EMA21": ema21_h1,
                "RSI": rsi_h1,
                "MACD": macd_h1,
                "MACD_signal": macd_signal_h1,
                "BB_lower": bb_lower_h1,
                "BB_upper": bb_upper_h1,
                "Close_price": close_price_h1,
                "ADX": adx_h1,
                "OBV": obv_h1,
                "Candle": candle_h1
            }
        }

    except Exception as e:
        print(f"⚠️ Error analisis {symbol}: {str(e)}")
        return None

# ==============================
# FUNGSI TRADING
# ==============================
def generate_signal(pair, data):
    """Generate trading signal"""
    price = data['price']
    display_pair = f"{pair[:-4]}/USDT"

    print(f"{display_pair} - Price: {price:.8f} | Buy: {buy_score}/7 | Sell: {sell_score}/6")

    buy_signal = (
            ema9_m15 > ema21_m15 and ema9_h1 > ema21_h1 and  # EMA 9 cross up EMA 21 di M15 & H1
            rsi_m15 < 30 and rsi_h1 < 50 and  # RSI M15 oversold, RSI H1 belum overbought
            macd_m15 > macd_signal_m15 and macd_h1 > macd_signal_h1 and  # MACD bullish crossover di M15 & H1
            close_price_m15 <= bb_lower_m15 and close_price_h1 <= bb_lower_h1 and  # Harga di lower Bollinger Band
            adx_m15 > 25 and adx_h1 > 25 and  # ADX menunjukkan tren kuat di M15 & H1
            obv_m15 > 0 and obv_h1 > 0 and  # OBV meningkat di M15 & H1
            ("BUY" in candle_m15 or "STRONG_BUY" in candle_m15) and  # Candlestick reversal di M15
            ("BUY" in candle_h1 or "STRONG_BUY" in candle_h1) and  # Candlestick reversal di H1
            pair not in ACTIVE_BUYS
        )
    sell_signal = (
            ema9_m15 < ema21_m15 and ema9_h1 < ema21_h1 and  # EMA 9 cross down EMA 21 di M15 & H1
            rsi_m15 > 70 and rsi_h1 > 50 and  # RSI M15 overbought, RSI H1 belum oversold
            macd_m15 < macd_signal_m15 and macd_h1 < macd_signal_h1 and  # MACD bearish crossover di M15 & H1
            close_price_m15 >= bb_upper_m15 and close_price_h1 >= bb_upper_h1 and  # Harga di upper Bollinger Band
            adx_m15 > 25 and adx_h1 > 25 and  # ADX menunjukkan tren kuat di M15 & H1
            obv_m15 < 0 and obv_h1 < 0 and  # OBV menurun di M15 & H1
            ("SELL" in candle_m15 or "STRONG_SELL" in candle_m15) and  # Candlestick reversal di M15
            ("SELL" in candle_h1 or "STRONG_SELL" in candle_h1) and  # Candlestick reversal di H1
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

def send_telegram_alert(signal_type, pair, current_price, data, buy_price=None):
    """Kirim notifikasi ke Telegram"""
    display_pair = f"{pair[:-4]}/USDT"
    message = ""
    buy_score, sell_score = calculate_scores(data)
    
    emoji = {
        'BUY': '🚀', 
        'SELL': '⚠️', 
        'TAKE PROFIT': '✅', 
        'STOP LOSS': '🛑'
    }.get(signal_type, 'ℹ️')

    base_msg = f"{emoji} **{signal_type}**\n"
    base_msg += f"💱 {display_pair}\n"
    base_msg += f"💲 Price: ${current_price:.8f}\n"

    if signal_type == 'BUY':
        message = f"{base_msg}🔍 RSI: {data['rsi']:.1f}\n"
        ACTIVE_BUYS[pair] = {'price': current_price, 'time': datetime.now()}

    elif signal_type in ['TAKE PROFIT', 'STOP LOSS', 'SELL']:
        entry = ACTIVE_BUYS.get(pair)
        if entry:
            profit = ((current_price - entry['price'])/entry['price'])*100
            duration = str(datetime.now() - entry['time']).split('.')[0]
            
            message = f"{base_msg}💲 Entry: ${entry['price']:.8f}\n"
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
            print(f"BB: {data['bb_lower']:.8f} - {data['bb_upper']:.8f}")
            
            signal, price = generate_signal(pair, data)
            if signal:
                send_telegram_alert(signal, pair, data['price'], data, price)
                
            # Auto close position
            if pair in ACTIVE_BUYS:
                position = ACTIVE_BUYS[pair]
                duration = datetime.now() - position['time']
                profit = (data['price'] - position['price'])/position['price']*100
                
                if duration > timedelta(hours=24) or abs(profit) > 8:
                    send_telegram_alert('SELL', pair, data['price'], data, position['price'])
                    
        except Exception as e:
            print(f"⚠️ Error di {pair}: {str(e)}")
            continue

if __name__ == "__main__":
    main()
