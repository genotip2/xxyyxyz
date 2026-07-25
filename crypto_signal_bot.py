import os
import requests
import json
import time
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

ACTIVE_BUYS = {}
COOLDOWNS = {}

# ==========================================
# TIMEFRAME
# ==========================================
TF_TREND = Interval.INTERVAL_1_DAY
TF_SETUP = Interval.INTERVAL_4_HOURS
TF_ENTRY = Interval.INTERVAL_1_HOUR

# ==========================================
# KONFIGURASI BATCH (Anti-Rate-Limit)
# ==========================================
BATCH_SIZE = 25          # Jumlah pair per batch
BATCH_DELAY = 1          # Delay antar batch (detik)
REQUEST_DELAY = 0        # Delay antar request (detik)
MAX_RETRIES = 3          # Retry jika gagal

# ==========================================
# PARAMETER STRATEGI (V2.1)
# ==========================================
ATR_SL_MULTIPLIER = 1.5
MAX_DISTANCE_FROM_EMA20_PCT = 7.0
RSI_OVERBOUGHT_VETO = 75
COOLDOWN_HOURS = 12
BREAK_EVEN_PCT = 3.0

TRAILING_LEVELS = [
    (15.0, 5.0),
    (8.0,  3.0),
    (5.0,  2.0),
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
# FUNGSI ANALISIS TRADINGVIEW (Anti-Rate-Limit)
# ==========================================
def get_analysis(pair, interval, max_retries=MAX_RETRIES):
    """Ambil analisis dengan retry & delay untuk menghindari rate limit."""
    for attempt in range(max_retries):
        try:
            handler = TA_Handler(
                symbol=pair, 
                exchange="BINANCE",
                screener="CRYPTO", 
                interval=interval
            )
            result = handler.get_analysis()
            time.sleep(REQUEST_DELAY)
            return result
            
        except Exception as e:
            error_msg = str(e).lower()
            
            if "429" in error_msg or "too many requests" in error_msg:
                wait_time = (attempt + 1) * 10
                print(f"⚠️ Rate limit {pair}@{interval}. Tunggu {wait_time}s... ({attempt+1}/{max_retries})")
                time.sleep(wait_time)
                continue
            
            print(f"⚠️ Gagal menganalisis {pair} pada {interval}: {e}")
            return None
    
    print(f"❌ Gagal mengambil data {pair}@{interval} setelah {max_retries} percobaan")
    return None

def extract_indicators(analysis):
    """Tahan None - konversi semua nilai None → 0"""
    if not analysis or not analysis.indicators:
        return {}
    ind = analysis.indicators
    
    def safe_float(value, default=0):
        if value is None:
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default
    
    return {
        'close': safe_float(ind.get('close')),
        'ema10': safe_float(ind.get('EMA10')),
        'ema20': safe_float(ind.get('EMA20')),
        'ema50': safe_float(ind.get('EMA50')),
        'ema200': safe_float(ind.get('EMA200')),
        'macd': safe_float(ind.get('MACD.macd')),
        'macd_signal': safe_float(ind.get('MACD.signal')),
        'rsi': safe_float(ind.get('RSI'), 50),
        'adx': safe_float(ind.get('ADX')),
        'atr': safe_float(ind.get('ATR')),
        'volume': safe_float(ind.get('Volume')),
        'average_volume': safe_float(ind.get('average_volume')),
    }

# ==========================================
# BATCH HELPER: Ambil data 3 TF sekaligus
# ==========================================
def get_all_timeframes_data(pair):
    """Ambil data 1D, 4H, 1H untuk satu pair."""
    analysis_1d = get_analysis(pair, TF_TREND)
    analysis_4h = get_analysis(pair, TF_SETUP)
    analysis_1h = get_analysis(pair, TF_ENTRY)
    
    if not all([analysis_1d, analysis_4h, analysis_1h]):
        return None
    
    return {
        '1d': extract_indicators(analysis_1d),
        '4h': extract_indicators(analysis_4h),
        '1h': extract_indicators(analysis_1h),
    }

# ==========================================
# DEBUG: TAMPILKAN INDIKATOR MENTAH
# ==========================================
def print_raw_indicators(pair, data_1d, data_4h, data_1h, current_price):
    print(f"  📊 Indikator Mentah:")
    print(f"      💲 Harga: ${current_price:.6f}")
    print(f"      📈 1D: EMA50={data_1d['ema50']:.4f} EMA200={data_1d['ema200']:.4f} ADX={data_1d['adx']:.1f}")
    print(f"      📈 4H: EMA20={data_4h['ema20']:.4f} EMA50={data_4h['ema50']:.4f} RSI={data_4h['rsi']:.1f}")
    print(f"      📈 1H: EMA10={data_1h['ema10']:.4f} EMA20={data_1h['ema20']:.4f} RSI={data_1h['rsi']:.1f}")
    print(f"      📈 1H: MACD={data_1h['macd']:.6f} Signal={data_1h['macd_signal']:.6f} ATR={data_1h['atr']:.6f}")

# ==========================================
# SCORING SYSTEM (Weighted - Mandiri)
# ==========================================
def calculate_entry_score(data_1d, data_4h, data_1h, current_price, sl_price):
    score = 0
    reasons = []
    vetoes = []

    # Quick Filter: Downtrend 1D Jelas
    if data_1d['ema50'] < data_1d['ema200'] and data_1d['close'] < data_1d['ema50']:
        vetoes.append("1D Downtrend jelas (Close<EMA50<EMA200)")
        return 0, reasons, vetoes

    # VETO CONDITIONS
    if data_1h['rsi'] > RSI_OVERBOUGHT_VETO:
        vetoes.append(f"RSI 1H OB ({data_1h['rsi']:.1f})")

    if data_4h['ema20'] > 0:
        dist = ((current_price - data_4h['ema20']) / data_4h['ema20']) * 100
        if dist > MAX_DISTANCE_FROM_EMA20_PCT:
            vetoes.append(f"Jauh dari EMA20 4H ({dist:.1f}%)")

    atr = data_1h.get('atr', 0)
    if atr > 0 and (atr / current_price) < 0.008:
        vetoes.append(f"ATR terlalu kecil ({(atr/current_price)*100:.2f}%)")

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

    # SCORING
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

    macd_diff_4h = data_4h['macd'] - data_4h['macd_signal']
    if macd_diff_4h > 0:
        if current_price > 0 and abs(macd_diff_4h) / current_price < 0.002:
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
        if current_price > 0 and abs(macd_diff_1h) / current_price < 0.002:
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
# CHECK ENTRY (Tanpa Filter BTC)
# ==========================================
def check_entry(pair, data_1d, data_4h, data_1h, current_price, sl_price):
    """
    Cek entry berdasarkan kualitas setup coin itu sendiri.
    Tidak ada lagi filter BTC/Dominance.
    """
    score, reasons, vetoes = calculate_entry_score(data_1d, data_4h, data_1h, current_price, sl_price)
    
    if vetoes:
        return None, score, reasons, sl_price, vetoes
    
    # Threshold statis (tidak lagi dinamis berdasarkan BTC)
    if score >= SCORE_BUY:
        signal = "BUY_STRONG" if score >= SCORE_BUY_STRONG else "BUY"
        return signal, score, reasons, sl_price, []
    elif score >= SCORE_WATCH:
        return "WATCH", score, reasons, sl_price, []
    else:
        return None, score, reasons, sl_price, []

# ==========================================
# CHECK EXIT
# ==========================================
def check_exit(pair, current_price, data_1h):
    if pair not in ACTIVE_BUYS:
        return None, ""
        
    entry_data = ACTIVE_BUYS[pair]
    entry_price = entry_data['price']
    stop_loss = entry_data['stop_loss']
    profit_pct = ((current_price - entry_price) / entry_price) * 100

    if current_price <= stop_loss:
        return "STOP_LOSS", f"SL tercapai (${stop_loss:.4f})"

    if profit_pct >= BREAK_EVEN_PCT and not entry_data.get('break_even_active', False):
        ACTIVE_BUYS[pair]['stop_loss'] = entry_price
        ACTIVE_BUYS[pair]['break_even_active'] = True
        save_active_buys()
        send_telegram_alert("BREAK_EVEN", pair, current_price, f"Profit {profit_pct:.2f}%, SL moved to Entry", entry_price=entry_price, profit_pct=profit_pct)

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
# BATCH PROCESSING HELPER
# ==========================================
def chunk_list(lst, chunk_size):
    """Bagi list menjadi chunks berukuran chunk_size"""
    for i in range(0, len(lst), chunk_size):
        yield lst[i:i + chunk_size]

# ==========================================
# PROGRAM UTAMA (V2.1 - Tanpa BTC Filter)
# ==========================================
def main():
    print(f"🕒 Bot V2.1 (Standalone) dimulai: {datetime.now(UTC7).strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    load_active_buys()
    load_cooldowns()
    pairs = get_pairs_from_file()
    
    # Hitung estimasi batch
    total_pairs = len(pairs)
    total_batches = (total_pairs + BATCH_SIZE - 1) // BATCH_SIZE
    total_requests = total_pairs * 3  # pairs × 3 TF (tidak ada BTC check lagi)
    estimated_time = (total_requests * REQUEST_DELAY) + ((total_batches - 1) * BATCH_DELAY)
    
    print(f"📦 Konfigurasi Batch:")
    print(f"   • Total pairs: {total_pairs}")
    print(f"   • Batch size: {BATCH_SIZE} pairs/batch")
    print(f"   • Total batch: {total_batches}")
    print(f"   • Total request: {total_requests}")
    print(f"   • Estimasi waktu: ~{estimated_time:.0f} detik")
    print(f"   • Mode: STANDALONE (tanpa filter BTC/Dominance)")
    print("=" * 60)
    
    stats = {'BUY': 0, 'WATCH': 0, 'SKIP': 0, 'VETO': 0, 'HOLD': 0, 'EXIT': 0, 'ERROR': 0}
    
    # PROSES PER BATCH
    for batch_idx, batch_pairs in enumerate(chunk_list(pairs, BATCH_SIZE), 1):
        print(f"\n{'='*60}")
        print(f"📦 BATCH {batch_idx}/{total_batches} ({len(batch_pairs)} pairs)")
        print(f"{'='*60}")
        
        for pair in batch_pairs:
            print(f"\n🔎 Menganalisis: {pair}")
            
            if pair in COOLDOWNS:
                if datetime.now(UTC7) < COOLDOWNS[pair]:
                    remaining = (COOLDOWNS[pair] - datetime.now(UTC7)).total_seconds() / 3600
                    print(f"  ⏳ {pair} dalam cooldown ({remaining:.1f} jam lagi). Skip.")
                    stats['SKIP'] += 1
                    continue
                else:
                    del COOLDOWNS[pair]
                    save_cooldowns()
            
            tf_data = get_all_timeframes_data(pair)
            
            if not tf_data:
                print(f"⚠️ Gagal mengambil data untuk {pair}. Skip.")
                stats['ERROR'] += 1
                continue
                
            data_1d = tf_data['1d']
            data_4h = tf_data['4h']
            data_1h = tf_data['1h']
            current_price = data_1h['close']
            
            if current_price == 0:
                print(f"⚠️ Harga 0 untuk {pair}. Skip.")
                stats['SKIP'] += 1
                continue
            
            print_raw_indicators(pair, data_1d, data_4h, data_1h, current_price)
                
            atr = data_1h.get('atr', 0)
            if atr > 0:
                sl_price = current_price - (ATR_SL_MULTIPLIER * atr)
            else:
                sl_price = current_price * 0.97

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
                        stats['EXIT'] += 1
                else:
                    profit_pct = ((current_price - ACTIVE_BUYS[pair]['price']) / ACTIVE_BUYS[pair]['price']) * 100
                    print(f"  ⏸️ Hold: Profit {profit_pct:+.2f}%")
                    stats['HOLD'] += 1
                    
            else:
                signal, score, reasons, sl_price, vetoes = check_entry(
                    pair, data_1d, data_4h, data_1h, current_price, sl_price
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
                    stats['BUY'] += 1
                elif signal == "WATCH":
                    print(f"  👀 WATCH (Score: {score}/100) - Pantau")
                    send_telegram_alert("WATCH", pair, current_price, f"Score {score}/100, pantau untuk entry", score=score, reasons=reasons)
                    stats['WATCH'] += 1
                elif vetoes:
                    print(f"  🚫 VETO: {'; '.join(vetoes)}")
                    stats['VETO'] += 1
                else:
                    print(f"  ❌ Skip (Score: {score}/100)")
                    print(f"  📋 Detail Scoring:")
                    for reason in reasons:
                        print(f"      {reason}")
                    stats['SKIP'] += 1
        
        # DELAY ANTAR BATCH (kecuali batch terakhir)
        if batch_idx < total_batches:
            print(f"\n⏸️ Istirahat {BATCH_DELAY} detik sebelum batch berikutnya...")
            time.sleep(BATCH_DELAY)
                
    save_active_buys()
    
    print("\n" + "=" * 60)
    print("📊 RINGKASAN SIKLUS:")
    print(f"   🚀 BUY: {stats['BUY']}")
    print(f"   👀 WATCH: {stats['WATCH']}")
    print(f"   ⏸️ HOLD: {stats['HOLD']}")
    print(f"   ✅ EXIT: {stats['EXIT']}")
    print(f"   🚫 VETO: {stats['VETO']}")
    print(f"   ❌ SKIP: {stats['SKIP']}")
    print(f"   ⚠️ ERROR: {stats['ERROR']}")
    print("=" * 60)
    print("✅ Siklus analisis selesai.")

if __name__ == "__main__":
    main()
