import os
import requests
import json
from datetime import datetime, timedelta, timezone
from tradingview_ta import TA_Handler, Interval

# ==========================================
# KONFIGURASI DASAR
# ==========================================
UTC7 = timezone(timedelta(hours=7))
TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', 'YOUR_TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', 'YOUR_TELEGRAM_CHAT_ID')
PAIRS_FILE = 'pairs_cache.json'
ACTIVE_BUYS_FILE = 'active_buys.json'
COOLDOWNS_FILE = 'cooldowns.json'
BTC_D_FILE = 'btc_dominance.json'  # BARU: untuk persistensi BTC Dominance

ACTIVE_BUYS = {}
COOLDOWNS = {}

# ==========================================
# TIMEFRAME
# ==========================================
TF_TREND = Interval.INTERVAL_1_DAY
TF_SETUP = Interval.INTERVAL_4_HOURS
TF_ENTRY = Interval.INTERVAL_1_HOUR

# ==========================================
# PARAMETER STRATEGI (V2.0)
# ==========================================
ATR_SL_MULTIPLIER = 1.5
MAX_DISTANCE_FROM_EMA20_PCT = 7.0
RSI_OVERBOUGHT_VETO = 75
COOLDOWN_HOURS = 12
BREAK_EVEN_PCT = 3.0  # Saran 8: Break Even di +3%

TRAILING_LEVELS = [
    (15.0, 5.0),   # Profit >= 15% → Trailing 5%
    (8.0,  3.0),   # Profit >= 8%  → Trailing 3%
    (5.0,  2.0),   # Profit >= 5%  → Trailing 2% (Aktif setelah Break Even)
]

SCORE_BUY_STRONG = 90
SCORE_BUY = 80
SCORE_WATCH = 60

# ==========================================
# FUNGSI UTILITY: LOAD & SAVE
# ==========================================
def load_active_buys():
    global ACTIVE_BUYS
    if os.path.exists(ACTIVE_BUYS_FILE):
        try:
            with open(ACTIVE_BUYS_FILE, 'r') as f:
                data = json.load(f)
                ACTIVE_BUYS = {
                    pair: {
                        'price': float(d['price']),
                        'time': datetime.fromisoformat(d['time']),
                        'stop_loss': float(d['stop_loss']),
                        'trailing_active': d.get('trailing_active', False),
                        'highest_price': float(d.get('highest_price', d['price'])),
                        'current_trailing_pct': float(d.get('current_trailing_pct', 0)),
                        'entry_score': int(d.get('entry_score', 0)),
                        'break_even_active': d.get('break_even_active', False)
                    }
                    for pair, d in data.items()
                }
            print(f"✅ Dimuat {len(ACTIVE_BUYS)} posisi aktif.")
        except Exception as e:
            print(f"❌ Gagal memuat posisi aktif: {e}")
            ACTIVE_BUYS = {}
    else:
        ACTIVE_BUYS = {}

def save_active_buys():
    try:
        data = {}
        for pair, d in ACTIVE_BUYS.items():
            data[pair] = {
                'price': d['price'], 'time': d['time'].isoformat(),
                'stop_loss': d['stop_loss'], 'trailing_active': d['trailing_active'],
                'highest_price': d['highest_price'], 'current_trailing_pct': d['current_trailing_pct'],
                'entry_score': d['entry_score'], 'break_even_active': d['break_even_active']
            }
        with open(ACTIVE_BUYS_FILE, 'w') as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"❌ Gagal menyimpan posisi aktif: {e}")

def load_cooldowns():
    global COOLDOWNS
    if os.path.exists(COOLDOWNS_FILE):
        try:
            with open(COOLDOWNS_FILE, 'r') as f:
                data = json.load(f)
                COOLDOWNS = {k: datetime.fromisoformat(v) for k, v in data.items()}
        except:
            COOLDOWNS = {}

def save_cooldowns():
    try:
        data = {k: v.isoformat() for k, v in COOLDOWNS.items()}
        with open(COOLDOWNS_FILE, 'w') as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"❌ Gagal simpan cooldown: {e}")

def get_pairs_from_file():
    default_pairs = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
    if not os.path.exists(PAIRS_FILE):
        print(f"ℹ️ File {PAIRS_FILE} tidak ditemukan. Membuat default...")
        with open(PAIRS_FILE, 'w') as f:
            json.dump(default_pairs, f, indent=4)
        return default_pairs
    try:
        with open(PAIRS_FILE, 'r') as f:
            pairs = json.load(f)
        print(f"✅ Memuat {len(pairs)} pair: {pairs}")
        return pairs
    except Exception as e:
        print(f"❌ Gagal membaca {PAIRS_FILE}: {e}")
        return default_pairs

# ==========================================
# BTC DOMINANCE (Persistent via CoinGecko)
# ==========================================
def load_last_btc_dominance():
    """Muat nilai BTC.D dari siklus sebelumnya"""
    if os.path.exists(BTC_D_FILE):
        try:
            with open(BTC_D_FILE, 'r') as f:
                data = json.load(f)
                return data.get('last_value', None)
        except Exception as e:
            print(f"⚠️ Gagal memuat BTC Dominance: {e}")
    return None

def save_btc_dominance(value):
    """Simpan nilai BTC.D untuk siklus berikutnya"""
    try:
        with open(BTC_D_FILE, 'w') as f:
            json.dump({
                'last_value': value,
                'updated': datetime.now(UTC7).isoformat()
            }, f, indent=4)
    except Exception as e:
        print(f"⚠️ Gagal simpan BTC Dominance: {e}")

def check_btc_dominance():
    """
    Cek BTC Dominance trend menggunakan CoinGecko API (gratis, tanpa key).
    Membandingkan nilai sekarang dengan siklus sebelumnya untuk menentukan trend.
    """
    print("🔍 Mengecek BTC Dominance via CoinGecko...")
    
    try:
        response = requests.get(
            "https://api.coingecko.com/api/v3/global",
            timeout=10
        )
        response.raise_for_status()
        data = response.json()
        
        btc_d_now = data['data']['market_cap_percentage']['btc']
        last_btc_d = load_last_btc_dominance()
        
        print(f"   BTC Dominance saat ini: {btc_d_now:.2f}%")
        
        if last_btc_d is not None:
            change = btc_d_now - last_btc_d
            print(f"   Perubahan: {change:+.2f}% (dari {last_btc_d:.2f}%)")
            
            # Threshold 0.3% untuk mendeteksi trend signifikan
            if change > 0.3:
                status = "UPTREND"    # ⚠️ Bahaya untuk altcoin
            elif change < -0.3:
                status = "DOWNTREND"  # ✅ Bagus untuk altcoin
            else:
                status = "NEUTRAL"
        else:
            status = "NEUTRAL"
            print(f"   Baseline pertama: {btc_d_now:.2f}% (akan dibandingkan siklus berikutnya)")
        
        # Simpan untuk siklus berikutnya
        save_btc_dominance(btc_d_now)
        print(f"   BTC.D Status: {status}")
        return status
        
    except Exception as e:
        print(f"⚠️ Gagal cek BTC Dominance: {e} → NEUTRAL")
        return "NEUTRAL"

# ==========================================
# FUNGSI ANALISIS TRADINGVIEW
# ==========================================
def get_analysis(pair, interval):
    try:
        handler = TA_Handler(symbol=pair, exchange="BINANCE", screener="CRYPTO", interval=interval)
        return handler.get_analysis()
    except Exception as e:
        print(f"⚠️ Gagal menganalisis {pair} pada {interval}: {e}")
        return None

def extract_indicators(analysis):
    if not analysis or not analysis.indicators:
        return {}
    ind = analysis.indicators
    return {
        'close': ind.get('close', 0), 'ema10': ind.get('EMA10', 0),
        'ema20': ind.get('EMA20', 0), 'ema50': ind.get('EMA50', 0),
        'ema200': ind.get('EMA200', 0), 'macd': ind.get('MACD.macd', 0),
        'macd_signal': ind.get('MACD.signal', 0), 'rsi': ind.get('RSI', 50),
        'adx': ind.get('ADX', 0), 'atr': ind.get('ATR', 0),
        'volume': ind.get('Volume', 0), 'average_volume': ind.get('average_volume', 0),
    }

# ==========================================
# FILTER BTC (Adaptive - 3 Kondisi)
# ==========================================
def check_btc_condition():
    """Mengembalikan BULLISH, SIDEWAYS, atau BEARISH"""
    print("🔍 Mengecek kondisi BTC (Market Leader)...")
    analysis = get_analysis("BTCUSDT", TF_TREND)
    if not analysis: return "SIDEWAYS"
    data = extract_indicators(analysis)
    
    is_uptrend = data['ema50'] > data['ema200']
    is_macd_bull = data['macd'] > data['macd_signal']
    is_close_above = data['close'] > data['ema50']
    
    if is_uptrend and is_macd_bull and is_close_above:
        status = "BULLISH"
    elif is_uptrend:
        status = "SIDEWAYS"
    else:
        status = "BEARISH"
        
    print(f"   BTC 1D: {status}")
    return status

# ==========================================
# SCORING SYSTEM (Weighted V2.0)
# ==========================================
def calculate_entry_score(data_1d, data_4h, data_1h, current_price, sl_price):
    score = 0
    reasons = []
    vetoes = []

    # ==========================================
    # VETO CONDITIONS (Hard Filter)
    # ==========================================
    # Veto 1: RSI 1H Overbought
    if data_1h['rsi'] > RSI_OVERBOUGHT_VETO:
        vetoes.append(f"RSI 1H OB ({data_1h['rsi']:.1f})")

    # Veto 2: Harga terlalu jauh dari EMA20 4H
    if data_4h['ema20'] > 0:
        dist = ((current_price - data_4h['ema20']) / data_4h['ema20']) * 100
        if dist > MAX_DISTANCE_FROM_EMA20_PCT:
            vetoes.append(f"Jauh dari EMA20 4H ({dist:.1f}%)")

    # Veto 3: ATR terlalu kecil (Market mati) - Saran 6
    atr = data_1h.get('atr', 0)
    if atr > 0 and (atr / current_price) < 0.008:
        vetoes.append(f"ATR terlalu kecil ({(atr/current_price)*100:.2f}%)")

    # Veto 4: Risk/Reward < 1:2 - Saran 10
    target_1d = data_1d.get('ema50', 0)
    risk = current_price - sl_price
    if risk > 0:
        if target_1d > current_price:
            reward = target_1d - current_price
        else:
            reward = 3.0 * atr if atr > 0 else current_price * 0.05
            
        rr_ratio = reward / risk
        if rr_ratio < 2.0:
            vetoes.append(f"RR kecil (1:{rr_ratio:.1f} < 1:2.0)")

    if vetoes:
        return 0, reasons, vetoes

    # ==========================================
    # SCORING (Total 100 Poin Berbobot) - Saran 9
    # ==========================================
    
    # 1. TREND (40%)
    if data_1d['ema20'] > data_1d['ema50'] > data_1d['ema200'] and data_1d['close'] > data_1d['ema20']:
        score += 25
        reasons.append("✅ 1D Strong Trend (EMA20>50>200) [+25]")
    elif data_1d['ema50'] > data_1d['ema200'] and data_1d['close'] > data_1d['ema50']:
        score += 20
        reasons.append("✅ 1D Uptrend (Close>EMA50>200) [+20]")
    else:
        reasons.append("❌ 1D Trend Lemah [+0]")

    if data_1d['adx'] > 25:
        score += 15
        reasons.append(f"✅ 1D ADX Kuat ({data_1d['adx']:.1f}) [+15]")
    else:
        reasons.append(f"❌ 1D ADX Lemah ({data_1d['adx']:.1f}) [+0]")

    # 2. PULLBACK (15%)
    if data_4h['ema20'] > data_4h['ema50']:
        dist_4h = abs(current_price - data_4h['ema20']) / data_4h['ema20'] * 100
        if dist_4h <= 2.0:
            score += 10
            reasons.append(f"✅ 4H Perfect Pullback (Dist {dist_4h:.1f}%) [+10]")
        else:
            score += 5
            reasons.append(f"⚠️ 4H Pullback Far (Dist {dist_4h:.1f}%) [+5]")
    else:
        reasons.append("❌ 4H Bukan Pullback [+0]")

    if 45 <= data_4h['rsi'] <= 60:
        score += 5
        reasons.append(f"✅ 4H RSI Rebound ({data_4h['rsi']:.1f}) [+5]")
    else:
        reasons.append(f"⚠️ 4H RSI Tidak Ideal ({data_4h['rsi']:.1f}) [+0]")

    # 3. MOMENTUM (30%)
    macd_diff_4h = data_4h['macd'] - data_4h['macd_signal']
    if macd_diff_4h > 0:
        if abs(macd_diff_4h) / current_price < 0.002:
            score += 15
            reasons.append("✅ 4H MACD Fresh Cross [+15]")
        else:
            score += 10
            reasons.append("✅ 4H MACD Bullish [+10]")
    else:
        reasons.append("❌ 4H MACD Bearish [+0]")

    if data_1h['ema10'] > data_1h['ema20']:
        score += 5
        reasons.append("✅ 1H Momentum (EMA10>20) [+5]")
    else:
        reasons.append("❌ 1H Momentum Lemah [+0]")

    macd_diff_1h = data_1h['macd'] - data_1h['macd_signal']
    if macd_diff_1h > 0:
        if abs(macd_diff_1h) / current_price < 0.002:
            score += 10
            reasons.append("✅ 1H MACD Fresh Cross [+10]")
        else:
            score += 5
            reasons.append("✅ 1H MACD Bullish [+5]")
    else:
        reasons.append("❌ 1H MACD Bearish [+0]")

    if 50 <= data_1h['rsi'] <= 65:
        score += 5
        reasons.append(f"✅ 1H RSI Optimal ({data_1h['rsi']:.1f}) [+5]")
    else:
        reasons.append(f"⚠️ 1H RSI Tidak Optimal ({data_1h['rsi']:.1f}) [+0]")

    # 4. VOLUME (15%)
    vol = data_1h.get('volume', 0)
    avg_vol = data_1h.get('average_volume', 0)
    if avg_vol > 0 and vol > (1.5 * avg_vol):
        score += 15
        reasons.append(f"✅ 1H Volume Spike ({vol/avg_vol:.1f}x) [+15]")
    else:
        reasons.append("❌ 1H Volume Rendah/Tidak Spike [+0]")

    return score, reasons, vetoes

# ==========================================
# DYNAMIC TRAILING & BREAK EVEN
# ==========================================
def get_trailing_percentage(profit_pct):
    for threshold, trailing in TRAILING_LEVELS:
        if profit_pct >= threshold:
            return trailing
    return 0

# ==========================================
# CHECK ENTRY
# ==========================================
def check_entry(pair, data_1d, data_4h, data_1h, current_price, sl_price, btc_condition, btc_d_status):
    score, reasons, vetoes = calculate_entry_score(data_1d, data_4h, data_1h, current_price, sl_price)
    
    if vetoes:
        return None, score, reasons, sl_price, vetoes
        
    # Adaptive BTC & Dominance Scoring
    is_btc = pair == "BTCUSDT"
    if not is_btc:
        if btc_condition == "BULLISH":
            score += 5
            reasons.append("✅ BTC Bullish [+5]")
        elif btc_condition == "BEARISH":
            score -= 10
            reasons.append("⚠️ BTC Bearish [-10]")
            
        if btc_d_status == "UPTREND":
            score -= 10
            reasons.append("⚠️ BTC.D Uptrend [-10]")
        elif btc_d_status == "DOWNTREND":
            score += 5
            reasons.append("✅ BTC.D Downtrend [+5]")
            
    score = max(0, min(100, score))
    
    # Dynamic Threshold
    buy_threshold = SCORE_BUY
    if not is_btc:
        if btc_condition == "BULLISH":
            buy_threshold = 80
        elif btc_condition == "SIDEWAYS":
            buy_threshold = 85
        else:
            buy_threshold = 90
            
    if score >= buy_threshold:
        signal = "BUY_STRONG" if score >= SCORE_BUY_STRONG else "BUY"
        return signal, score, reasons, sl_price, []
    elif score >= SCORE_WATCH:
        return "WATCH", score, reasons, sl_price, []
    else:
        return None, score, reasons, sl_price, []

# ==========================================
# CHECK EXIT (Smarter Exit V2.0)
# ==========================================
def check_exit(pair, current_price, data_1h):
    if pair not in ACTIVE_BUYS:
        return None, ""
        
    entry_data = ACTIVE_BUYS[pair]
    entry_price = entry_data['price']
    stop_loss = entry_data['stop_loss']
    profit_pct = ((current_price - entry_price) / entry_price) * 100

    # 1. Hard Stop Loss
    if current_price <= stop_loss:
        return "STOP_LOSS", f"SL tercapai (${stop_loss:.4f})"

    # 2. Break Even Stop (Saran 8)
    if profit_pct >= BREAK_EVEN_PCT and not entry_data.get('break_even_active', False):
        ACTIVE_BUYS[pair]['stop_loss'] = entry_price
        ACTIVE_BUYS[pair]['break_even_active'] = True
        save_active_buys()
        send_telegram_alert("BREAK_EVEN", pair, current_price, f"Profit {profit_pct:.2f}%, SL moved to Entry", entry_price=entry_price, profit_pct=profit_pct)

    # 3. Dynamic Trailing Stop
    trailing_pct = get_trailing_percentage(profit_pct)
    if trailing_pct > 0:
        if not entry_data.get('trailing_active', False):
            ACTIVE_BUYS[pair]['trailing_active'] = True
            ACTIVE_BUYS[pair]['highest_price'] = current_price
            ACTIVE_BUYS[pair]['current_trailing_pct'] = trailing_pct
            send_telegram_alert("ACTIVATE_TRAIL", pair, current_price, f"Profit {profit_pct:.2f}%, Trailing {trailing_pct}%", entry_price=entry_price, profit_pct=profit_pct)
        
        if current_price > entry_data['highest_price']:
            ACTIVE_BUYS[pair]['highest_price'] = current_price
            ACTIVE_BUYS[pair]['current_trailing_pct'] = trailing_pct
            
        trailing_limit = entry_data['highest_price'] * (1 - trailing_pct / 100)
        if current_price <= trailing_limit:
            return "TRAILING_STOP", f"Trailing {trailing_pct}% kena"

    # 4. Smarter Exit (Saran 7)
    ema_cross_down = data_1h['ema10'] < data_1h['ema20']
    macd_bearish = data_1h['macd'] < data_1h['macd_signal']
    
    if ema_cross_down and macd_bearish:
        if profit_pct > 1 or profit_pct < -1:
            return "SELL_EMA_MACD", f"EMA10 < EMA20 & MACD Bearish"

    if current_price < data_1h['ema20']:
        if profit_pct > 0 or profit_pct < -2:
            return "SELL_CLOSE_EMA", f"Close < EMA20 (1H)"

    return None, "Hold"

# ==========================================
# TELEGRAM NOTIFICATION
# ==========================================
def send_telegram_alert(signal_type, pair, current_price, details,
                        entry_price=None, profit_pct=None, score=None, reasons=None):
    display_pair = f"{pair[:-4]}/USDT"
    emojis = {
        'BUY': '🚀', 'BUY_STRONG': '🚀🔥', 'WATCH': '👀',
        'SELL_EMA_MACD': '📉', 'SELL_CLOSE_EMA': '📉',
        'STOP_LOSS': '🛑', 'TRAILING_STOP': '💰',
        'ACTIVATE_TRAIL': '🔒', 'BREAK_EVEN': '🛡️'
    }
    emoji = emojis.get(signal_type, 'ℹ️')
    binance_url = f"https://www.binance.com/en/trade/{pair[:-4]}_USDT"
    tv_url = f"https://www.tradingview.com/chart/?symbol=BINANCE:{pair}"
    
    message = f"{emoji} *{signal_type.replace('_', ' ')}*\n"
    message += f"💱 *Pair:* [{display_pair}]({binance_url}) | [TV]({tv_url})\n"
    message += f"💲 *Price:* ${current_price:.4f}\n"
    
    if entry_price is not None and profit_pct is not None:
        status = "Profit" if profit_pct > 0 else "Loss"
        message += f"▫️ *Entry:* ${entry_price:.4f}\n"
        message += f"📊 *{status}:* {profit_pct:+.2f}%\n"
        
    if score is not None:
        message += f"🎯 *Score:* {score}/100\n"
        
    if details:
        message += f"📝 *Note:* {details}\n"
        
    if reasons:
        message += "\n*Analisis:*\n"
        for reason in reasons[:8]:
            message += f"  {reason}\n"
            
    print(f"📢 {message.replace('*', '').replace('[', '').replace(']', '')}")
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                'chat_id': TELEGRAM_CHAT_ID, 'text': message,
                'parse_mode': 'Markdown', 'disable_web_page_preview': True
            }, timeout=10
        )
    except Exception as e:
        print(f"❌ Gagal kirim Telegram: {e}")

# ==========================================
# PROGRAM UTAMA
# ==========================================
def main():
    print(f"🕒 Bot dimulai: {datetime.now(UTC7).strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    load_active_buys()
    load_cooldowns()
    pairs = get_pairs_from_file()
    
    btc_condition = check_btc_condition()
    btc_d_status = check_btc_dominance()  # Sekarang pakai CoinGecko API
    
    print("=" * 60)
    
    for pair in pairs:
        print(f"\n🔎 Menganalisis: {pair}")
        
        # Cek Cooldown (Saran 11)
        if pair in COOLDOWNS:
            if datetime.now(UTC7) < COOLDOWNS[pair]:
                print(f"  ⏳ {pair} dalam cooldown. Skip.")
                continue
            else:
                del COOLDOWNS[pair]
                save_cooldowns()
        
        # Ambil data multi-timeframe
        analysis_1d = get_analysis(pair, TF_TREND)
        analysis_4h = get_analysis(pair, TF_SETUP)
        analysis_1h = get_analysis(pair, TF_ENTRY)
        
        if not all([analysis_1d, analysis_4h, analysis_1h]):
            print(f"⚠️ Gagal mengambil data untuk {pair}. Skip.")
            continue
            
        data_1d = extract_indicators(analysis_1d)
        data_4h = extract_indicators(analysis_4h)
        data_1h = extract_indicators(analysis_1h)
        current_price = data_1h['close']
        
        if current_price == 0:
            print(f"⚠️ Harga 0 untuk {pair}. Skip.")
            continue
            
        # Hitung SL awal untuk keperluan cek RR
        atr = data_1h.get('atr', 0)
        if atr > 0:
            sl_price = current_price - (ATR_SL_MULTIPLIER * atr)
        else:
            sl_price = current_price * 0.97

        # ==========================================
        # JIKA SUDAH PUNYA POSISI → CEK EXIT
        # ==========================================
        if pair in ACTIVE_BUYS:
            signal, details = check_exit(pair, current_price, data_1h)
            if signal:
                entry_data = ACTIVE_BUYS[pair]
                profit_pct = ((current_price - entry_data['price']) / entry_data['price']) * 100
                send_telegram_alert(
                    signal, pair, current_price, details,
                    entry_price=entry_data['price'], profit_pct=profit_pct
                )
                if signal in ["STOP_LOSS", "TRAILING_STOP", "SELL_EMA_MACD", "SELL_CLOSE_EMA"]:
                    if signal == "STOP_LOSS":
                        COOLDOWNS[pair] = datetime.now(UTC7) + timedelta(hours=COOLDOWN_HOURS)
                        save_cooldowns()
                    del ACTIVE_BUYS[pair]
                    print(f"✅ Posisi {pair} ditutup.")
            else:
                profit_pct = ((current_price - ACTIVE_BUYS[pair]['price']) / ACTIVE_BUYS[pair]['price']) * 100
                print(f"  ⏸️ Hold: Profit {profit_pct:+.2f}%")
                
        # ==========================================
        # JIKA BELUM PUNYA POSISI → CEK ENTRY
        # ==========================================
        else:
            signal, score, reasons, sl_price, vetoes = check_entry(
                pair, data_1d, data_4h, data_1h, current_price, sl_price, btc_condition, btc_d_status
            )
            
            if signal == "BUY" or signal == "BUY_STRONG":
                print(f"  ✅ SINYAL {signal} (Score: {score}/100)")
                ACTIVE_BUYS[pair] = {
                    'price': current_price, 'time': datetime.now(UTC7),
                    'stop_loss': sl_price, 'trailing_active': False,
                    'highest_price': current_price, 'current_trailing_pct': 0,
                    'entry_score': score, 'break_even_active': False
                }
                sl_info = f"SL: ${sl_price:.4f} (ATR-based)"
                send_telegram_alert(signal, pair, current_price, sl_info, score=score, reasons=reasons)
            elif signal == "WATCH":
                print(f"  👀 WATCH (Score: {score}/100) - Pantau")
                send_telegram_alert("WATCH", pair, current_price, f"Score {score}/100, pantau untuk entry", score=score, reasons=reasons)
            elif vetoes:
                print(f"  🚫 VETO: {'; '.join(vetoes)}")
            else:
                print(f"  ❌ Skip (Score: {score}/100)")
                
    save_active_buys()
    print("\n" + "=" * 60)
    print("✅ Siklus analisis selesai.")

if __name__ == "__main__":
    main()
