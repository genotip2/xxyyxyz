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
ACTIVE_BUYS = {}

# ==========================================
# TIMEFRAME (Sesuai Strategi Anda)
# ==========================================
TF_TREND = Interval.INTERVAL_1_DAY       # Untuk filter trend makro
TF_SETUP = Interval.INTERVAL_4_HOURS     # Untuk cari pullback
TF_ENTRY = Interval.INTERVAL_1_HOUR      # Untuk entry & exit

# ==========================================
# PARAMETER STRATEGI
# ==========================================
# Stop Loss berbasis ATR (adaptif per coin)
ATR_SL_MULTIPLIER = 1.5

# Veto Conditions (Hard Filter - tidak bisa di-skip)
MAX_DISTANCE_FROM_EMA20_PCT = 7.0   # Jika >7% dari EMA20 4H, JANGAN BUY
RSI_OVERBOUGHT_VETO = 75            # Jika RSI 1H > 75, JANGAN BUY

# Dynamic Trailing Stop (Profit-based)
TRAILING_LEVELS = [
    (15.0, 5.0),   # Profit >= 15% → Trailing 5%
    (8.0,  3.0),   # Profit >= 8%  → Trailing 3%
    (4.0,  2.0),   # Profit >= 4%  → Trailing 2%
]

# Scoring Thresholds
SCORE_BUY_STRONG = 90   # Sinyal sangat kuat
SCORE_BUY = 80          # Sinyal cukup kuat → BUY
SCORE_WATCH = 60        # Pantau saja
# < 60 → Skip

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
                'price': d['price'],
                'time': d['time'].isoformat(),
                'stop_loss': d['stop_loss'],
                'trailing_active': d['trailing_active'],
                'highest_price': d['highest_price'],
                'current_trailing_pct': d['current_trailing_pct'],
                'entry_score': d['entry_score'],
            }
        with open(ACTIVE_BUYS_FILE, 'w') as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"❌ Gagal menyimpan posisi aktif: {e}")

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
# FUNGSI ANALISIS TRADINGVIEW
# ==========================================
def get_analysis(pair, interval):
    try:
        handler = TA_Handler(
            symbol=pair, exchange="BINANCE",
            screener="CRYPTO", interval=interval
        )
        return handler.get_analysis()
    except Exception as e:
        print(f"⚠️ Gagal menganalisis {pair} pada {interval}: {e}")
        return None

def extract_indicators(analysis):
    if not analysis or not analysis.indicators:
        return {}
    ind = analysis.indicators
    return {
        'close': ind.get('close', 0),
        'ema10': ind.get('EMA10', 0),
        'ema20': ind.get('EMA20', 0),
        'ema50': ind.get('EMA50', 0),
        'ema200': ind.get('EMA200', 0),
        'macd': ind.get('MACD.macd', 0),
        'macd_signal': ind.get('MACD.signal', 0),
        'rsi': ind.get('RSI', 50),
        'adx': ind.get('ADX', 0),
        'atr': ind.get('ATR', 0),
        'volume': ind.get('Volume', 0),
        'average_volume': ind.get('average_volume', 0),
    }

# ==========================================
# FILTER BTC (Market Leader)
# ==========================================
def check_btc_bullish():
    """
    Cek apakah BTC sedang bullish di timeframe 1D.
    Jika BTC bearish, JANGAN beli altcoin.
    """
    print("🔍 Mengecek kondisi BTC sebagai market leader...")
    analysis = get_analysis("BTCUSDT", TF_TREND)
    if not analysis:
        print("⚠️ Gagal mengambil data BTC. Melanjutkan dengan asumsi bullish.")
        return True
    
    data = extract_indicators(analysis)
    
    # Kondisi 1: EMA50 > EMA200 (Uptrend jangka panjang)
    trend_ok = data['ema50'] > data['ema200']
    # Kondisi 2: MACD bullish (momentum positif)
    momentum_ok = data['macd'] > data['macd_signal']
    
    is_bullish = trend_ok and momentum_ok
    
    status = "✅ BULLISH" if is_bullish else "❌ BEARISH"
    print(f"   BTC 1D: EMA50={'>' if trend_ok else '<'}EMA200, MACD={'Bullish' if momentum_ok else 'Bearish'} → {status}")
    
    return is_bullish

# ==========================================
# SCORING SYSTEM (Jantung Strategi)
# ==========================================
def calculate_entry_score(data_1d, data_4h, data_1h, current_price):
    """
    Hitung skor entry berdasarkan kondisi multi-timeframe.
    Total maksimal: 100 poin
    """
    score = 0
    reasons = []
    vetoes = []
    
    # ==========================================
    # VETO CONDITIONS (Hard Filter)
    # ==========================================
    # Veto 1: RSI 1H > 75 (overbought)
    if data_1h['rsi'] > RSI_OVERBOUGHT_VETO:
        vetoes.append(f"RSI 1H terlalu tinggi ({data_1h['rsi']:.1f} > {RSI_OVERBOUGHT_VETO})")
    
    # Veto 2: Harga terlalu jauh dari EMA20 4H (>7%)
    if data_4h['ema20'] > 0:
        distance_pct = ((current_price - data_4h['ema20']) / data_4h['ema20']) * 100
        if distance_pct > MAX_DISTANCE_FROM_EMA20_PCT:
            vetoes.append(f"Harga terlalu jauh dari EMA20 4H ({distance_pct:.1f}% > {MAX_DISTANCE_FROM_EMA20_PCT}%)")
    
    if vetoes:
        return 0, reasons, vetoes
    
    # ==========================================
    # SCORING CONDITIONS (Soft Filter)
    # ==========================================
    
    # 1. Trend 1D bullish (EMA50 > EMA200): +25 poin
    if data_1d['ema50'] > data_1d['ema200']:
        score += 25
        reasons.append("✅ 1D Uptrend (EMA50>EMA200) [+25]")
    else:
        reasons.append("❌ 1D Downtrend [+0]")
    
    # 2. ADX 1D > 25 (trend kuat): +10 poin
    if data_1d['adx'] > 25:
        score += 10
        reasons.append(f"✅ 1D ADX Kuat ({data_1d['adx']:.1f}) [+10]")
    else:
        reasons.append(f"❌ 1D ADX Lemah ({data_1d['adx']:.1f}) [+0]")
    
    # 3. Setup 4H: EMA20 > EMA50 (pullback structure): +20 poin
    if data_4h['ema20'] > data_4h['ema50']:
        score += 20
        reasons.append("✅ 4H Pullback Structure (EMA20>EMA50) [+20]")
    else:
        reasons.append("❌ 4H Bukan Pullback [+0]")
    
    # 4. Setup 4H: Harga dekat EMA20 (<3%): +5 poin
    if data_4h['ema20'] > 0:
        distance_pct = abs(current_price - data_4h['ema20']) / data_4h['ema20'] * 100
        if distance_pct < 3:
            score += 5
            reasons.append(f"✅ 4H Harga Dekat EMA20 ({distance_pct:.1f}%) [+5]")
        else:
            reasons.append(f"⚠️ 4H Harga Jauh dari EMA20 ({distance_pct:.1f}%) [+0]")
    
    # 5. Setup 4H: RSI 40-60 (zona ideal pullback): +10 poin
    if 40 <= data_4h['rsi'] <= 60:
        score += 10
        reasons.append(f"✅ 4H RSI Ideal ({data_4h['rsi']:.1f}) [+10]")
    else:
        reasons.append(f"⚠️ 4H RSI Tidak Ideal ({data_4h['rsi']:.1f}) [+0]")
    
    # 6. Setup 4H: MACD mulai crossover: +10 poin
    if data_4h['macd'] > data_4h['macd_signal']:
        score += 10
        reasons.append("✅ 4H MACD Bullish [+10]")
    else:
        reasons.append("❌ 4H MACD Bearish [+0]")
    
    # 7. Entry 1H: EMA10 > EMA20 (momentum pendek): +10 poin
    if data_1h['ema10'] > data_1h['ema20']:
        score += 10
        reasons.append("✅ 1H Momentum (EMA10>EMA20) [+10]")
    else:
        reasons.append("❌ 1H Momentum Lemah [+0]")
    
    # 8. Entry 1H: MACD crossover: +5 poin
    if data_1h['macd'] > data_1h['macd_signal']:
        score += 5
        reasons.append("✅ 1H MACD Bullish [+5]")
    else:
        reasons.append("❌ 1H MACD Bearish [+0]")
    
    # 9. Entry 1H: RSI 50-65 (momentum sehat): +5 poin
    if 50 <= data_1h['rsi'] <= 65:
        score += 5
        reasons.append(f"✅ 1H RSI Optimal ({data_1h['rsi']:.1f}) [+5]")
    else:
        reasons.append(f"⚠️ 1H RSI Tidak Optimal ({data_1h['rsi']:.1f}) [+0]")
    
    # 10. Entry 1H: Volume tinggi (> average): +5 poin
    volume = data_1h.get('volume', 0)
    avg_volume = data_1h.get('average_volume', 0)
    if avg_volume > 0 and volume > avg_volume:
        score += 5
        reasons.append(f"✅ 1H Volume Tinggi (>{avg_volume:.0f}) [+5]")
    elif avg_volume == 0 and volume > 1_000_000:  # Fallback
        score += 5
        reasons.append(f"✅ 1H Volume Tinggi (fallback) [+5]")
    else:
        reasons.append("❌ 1H Volume Rendah [+0]")
    
    return score, reasons, vetoes

# ==========================================
# DYNAMIC TRAILING STOP
# ==========================================
def get_trailing_percentage(profit_pct):
    """
    Kembalikan persentase trailing stop berdasarkan profit.
    Profit lebih besar → trailing lebih longgar (amankan profit besar).
    """
    for threshold, trailing in TRAILING_LEVELS:
        if profit_pct >= threshold:
            return trailing
    return 0  # Belum aktif

# ==========================================
# CHECK ENTRY
# ==========================================
def check_entry(pair, data_1d, data_4h, data_1h, current_price, btc_bullish):
    """
    Cek apakah kondisi entry terpenuhi.
    Return: (signal, score, reasons, sl_price, vetoes)
    """
    # Filter BTC untuk altcoin
    is_btc = pair == "BTCUSDT"
    if not is_btc and not btc_bullish:
        return None, 0, [], 0, ["BTC sedang bearish, altcoin tidak aman"]
    
    # Hitung skor
    score, reasons, vetoes = calculate_entry_score(data_1d, data_4h, data_1h, current_price)
    
    # Jika ada veto, jangan beli
    if vetoes:
        return None, score, reasons, 0, vetoes
    
    # Hitung Stop Loss berbasis ATR
    atr = data_1h.get('atr', 0)
    if atr > 0:
        sl_price = current_price - (ATR_SL_MULTIPLIER * atr)
    else:
        # Fallback jika ATR tidak tersedia: gunakan 3% dari harga
        sl_price = current_price * 0.97
    
    # Keputusan berdasarkan skor
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
    """
    Cek kondisi exit untuk posisi yang sedang dibuka.
    Prioritas: SL → Trailing Stop → EMA Cross → RSI
    """
    if pair not in ACTIVE_BUYS:
        return None, ""
    
    entry_data = ACTIVE_BUYS[pair]
    entry_price = entry_data['price']
    stop_loss = entry_data['stop_loss']
    profit_pct = ((current_price - entry_price) / entry_price) * 100
    
    # 1. Stop Loss (ATR-based) - Prioritas tertinggi
    if current_price <= stop_loss:
        return "STOP_LOSS", f"ATR SL tercapai (${stop_loss:.4f})"
    
    # 2. Dynamic Trailing Stop
    trailing_pct = get_trailing_percentage(profit_pct)
    
    if trailing_pct > 0:
        # Aktifkan trailing jika belum aktif
        if not entry_data['trailing_active']:
            ACTIVE_BUYS[pair]['trailing_active'] = True
            ACTIVE_BUYS[pair]['highest_price'] = current_price
            ACTIVE_BUYS[pair]['current_trailing_pct'] = trailing_pct
            return "ACTIVATE_TRAIL", f"Profit {profit_pct:.2f}%, Trailing {trailing_pct}% diaktifkan"
        
        # Update highest price
        if current_price > entry_data['highest_price']:
            ACTIVE_BUYS[pair]['highest_price'] = current_price
            ACTIVE_BUYS[pair]['current_trailing_pct'] = trailing_pct
        
        # Cek apakah harga jatuh melewati trailing stop
        trailing_limit = entry_data['highest_price'] * (1 - trailing_pct / 100)
        if current_price <= trailing_limit:
            return "TRAILING_STOP", f"Trailing {trailing_pct}% kena (High: ${entry_data['highest_price']:.4f}, Limit: ${trailing_limit:.4f})"
    
    # 3. Exit: EMA10 < EMA20 (1H) - Trend breakdown
    if data_1h['ema10'] < data_1h['ema20']:
        # Hanya exit jika profit sudah cukup atau loss sudah dalam
        if profit_pct > 2 or profit_pct < -1:
            return "SELL_EMA", f"EMA10 < EMA20 (1H trend breakdown)"
    
    # 4. Exit: RSI < 45 (1H) - Momentum hilang
    if data_1h['rsi'] < 45:
        if profit_pct > 1 or profit_pct < -1:
            return "SELL_RSI", f"RSI 1H lemah ({data_1h['rsi']:.1f} < 45)"
    
    return None, "Hold"

# ==========================================
# TELEGRAM NOTIFICATION
# ==========================================
def send_telegram_alert(signal_type, pair, current_price, details, 
                       entry_price=None, profit_pct=None, score=None, reasons=None):
    display_pair = f"{pair[:-4]}/USDT"
    
    emojis = {
        'BUY': '🚀', 'BUY_STRONG': '🚀🔥', 'WATCH': '👀',
        'SELL_EMA': '📉', 'SELL_RSI': '📊',
        'STOP_LOSS': '🛑', 'TRAILING_STOP': '💰',
        'ACTIVATE_TRAIL': '🔒'
    }
    emoji = emojis.get(signal_type, 'ℹ️')
    
    binance_url = f"https://www.binance.com/en/trade/{pair[:-4]}_USDT"
    tv_url = f"https://www.tradingview.com/chart/?symbol=BINANCE:{pair}"
    
    message = f"{emoji} *{signal_type.replace('_', ' ')}*\n"
    message += f"💱 *Pair:* [{display_pair}]({binance_url}) | [TV]({tv_url})\n"
    message += f"💲 *Price:* ${current_price:.4f}\n"
    
    # Info entry & profit
    if entry_price is not None and profit_pct is not None:
        status = "Profit" if profit_pct > 0 else "Loss"
        message += f"▫️ *Entry:* ${entry_price:.4f}\n"
        message += f"📊 *{status}:* {profit_pct:+.2f}%\n"
    
    # Info skor (untuk BUY/WATCH)
    if score is not None:
        message += f"🎯 *Score:* {score}/100\n"
    
    # Detail
    if details:
        message += f"📝 *Note:* {details}\n"
    
    # Alasan (untuk BUY)
    if reasons:
        message += "\n*Analisis:*\n"
        for reason in reasons[:8]:  # Batasi 8 alasan agar tidak terlalu panjang
            message += f"  {reason}\n"
    
    print(f"📢 {message.replace('*', '').replace('[', '').replace(']', '')}")
    
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                'chat_id': TELEGRAM_CHAT_ID,
                'text': message,
                'parse_mode': 'Markdown',
                'disable_web_page_preview': True
            },
            timeout=10
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
    pairs = get_pairs_from_file()
    
    # Cek kondisi BTC terlebih dahulu
    btc_bullish = check_btc_bullish()
    if not btc_bullish:
        print("⚠️ PERINGATAN: BTC sedang bearish. Hanya BTC yang akan dianalisis.")
    print("=" * 60)
    
    for pair in pairs:
        print(f"\n🔎 Menganalisis: {pair}")
        
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
                
                # Hapus dari active buys jika exit final
                if signal in ["STOP_LOSS", "TRAILING_STOP", "SELL_EMA", "SELL_RSI"]:
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
                pair, data_1d, data_4h, data_1h, current_price, btc_bullish
            )
            
            if signal == "BUY" or signal == "BUY_STRONG":
                print(f"  ✅ SINYAL {signal} (Score: {score}/100)")
                ACTIVE_BUYS[pair] = {
                    'price': current_price,
                    'time': datetime.now(UTC7),
                    'stop_loss': sl_price,
                    'trailing_active': False,
                    'highest_price': current_price,
                    'current_trailing_pct': 0,
                    'entry_score': score,
                }
                sl_info = f"SL: ${sl_price:.4f} (ATR-based)"
                send_telegram_alert(
                    signal, pair, current_price, sl_info,
                    score=score, reasons=reasons
                )
            
            elif signal == "WATCH":
                print(f"  👀 WATCH (Score: {score}/100) - Pantau")
                send_telegram_alert(
                    "WATCH", pair, current_price, f"Score {score}/100, pantau untuk entry",
                    score=score, reasons=reasons
                )
            
            elif vetoes:
                print(f"  🚫 VETO: {'; '.join(vetoes)}")
            
            else:
                print(f"  ❌ Skip (Score: {score}/100)")
    
    save_active_buys()
    print("\n" + "=" * 60)
    print("✅ Siklus analisis selesai.")

if __name__ == "__main__":
    main()
