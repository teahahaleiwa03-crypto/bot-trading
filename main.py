import os
import time
import threading
from datetime import datetime
import pytz
import yfinance as yf
import requests
from flask import Flask

# ==========================================
# SERVEUR WEB FLASK
# ==========================================
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot Trading Forex is running!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# ==========================================
# CONFIGURATION
# ==========================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

PAIRES = {
    "EUR/USD": "EURUSD=X",
    "GBP/USD": "GBPUSD=X",
    "GBP/JPY": "GBPJPY=X"
}

dashboard_msg_id = None

# ==========================================
# TELEGRAM API
# ==========================================
def send_telegram_message(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return None
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        res = requests.post(url, json=payload, timeout=10)
        data = res.json()
        if data.get("ok"):
            return data.get("result", {}).get("message_id")
    except Exception as e:
        print(f"Erreur Envoi Telegram : {e}")
    return None

def update_telegram_message(message_id, text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID or not message_id:
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageText"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "message_id": message_id, "text": text, "parse_mode": "HTML"}
    try:
        res = requests.post(url, json=payload, timeout=10)
        return res.json().get("ok", False)
    except Exception as e:
        print(f"Erreur Edit Telegram : {e}")
        return False

# ==========================================
# GESTION DES SESSIONS
# ==========================================
def check_session_active():
    now_utc = datetime.now(pytz.utc)
    if now_utc.weekday() < 5:
        return True, "🟢 ACTIVE (24/24 - Lun/Ven)"
    else:
        return False, "🔴 INACTIVE (Week-end)"

# ==========================================
# DONNEES & ANALYSE
# ==========================================
def get_market_data(ticker):
    try:
        t = yf.Ticker(ticker)
        data_h1 = t.history(period="10d", interval="1h")
        time.sleep(1)
        data_m15 = t.history(period="10d", interval="15m")
        if data_h1.empty or data_m15.empty:
            return None, None
        
        data_h1 = data_h1.ffill()
        data_m15 = data_m15.ffill()
        return data_h1, data_m15
    except Exception as e:
        print(f"Erreur téléchargement {ticker} : {e}")
        return None, None

def analyze_h1_trend(df_h1):
    if df_h1 is None or len(df_h1) < 50:
        return "INDISPONIBLE"
    close = df_h1['Close']
    ema20 = close.ewm(span=20, adjust=False).mean().iloc[-1]
    ema50 = close.ewm(span=50, adjust=False).mean().iloc[-1]
    current_price = close.iloc[-1]
    if current_price > ema20 and ema20 > ema50:
        return "HAUSSIER"
    elif current_price < ema20 and ema20 < ema50:
        return "BAISSIER"
    else:
        return "NEUTRE"

def check_m15_signal(df_m15, trend_h1):
    if df_m15 is None or len(df_m15) < 50 or trend_h1 in ["NEUTRE", "INDISPONIBLE"]:
        return None

    close = df_m15['Close']
    high = df_m15['High']
    low = df_m15['Low']

    sma200 = close.rolling(window=min(200, len(close))).mean().iloc[-1]
    current_close = float(close.iloc[-1])

    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    current_rsi = float(rsi.iloc[-1])

    tr = (high - low).combine((high - close.shift(1)).abs(), max).combine((low - close.shift(1)).abs(), max)
    atr = float(tr.rolling(window=14).mean().iloc[-1])
    
    if str(atr) == "nan" or atr == 0:
        atr = current_close * 0.0015

    current_candle_size = float(high.iloc[-1] - low.iloc[-1])
    volatility_ok = current_candle_size >= (0.6 * atr)

    swing_high = float(high.iloc[-11:-1].max())
    swing_low = float(low.iloc[-11:-1].min())

    direction = None
    if trend_h1 == "HAUSSIER" and current_close > sma200:
        if 50 < current_rsi < 70 and current_close > swing_high and volatility_ok:
            direction = "BUY"

    if trend_h1 == "BAISSIER" and current_close < sma200:
        if 30 < current_rsi < 50 and current_close < swing_low and volatility_ok:
            direction = "SELL"

    if not direction:
        return None

    sl_distance = 1.5 * atr
    if direction == "BUY":
        entry = current_close
        sl = entry - sl_distance
        tp1 = entry + (1.0 * sl_distance)
        tp2 = entry + (1.5 * sl_distance)
        tp3 = entry + (2.5 * sl_distance)
    else:
        entry = current_close
        sl = entry + sl_distance
        tp1 = entry - (1.0 * sl_distance)
        tp2 = entry - (1.5 * sl_distance)
        tp3 = entry - (2.5 * sl_distance)

    return {
        "direction": direction,
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3
    }

# ==========================================
# BOUCLE PRINCIPALE
# ==========================================
def bot_loop():
    global dashboard_msg_id
    
    while True:
        try:
            is_active, session_str = check_session_active()
            now_utc_str = datetime.now(pytz.utc).strftime("%H:%M UTC")

            trends = {}
            signals = {}

            for nom_paire, ticker in PAIRES.items():
                df_h1, df_m15 = get_market_data(ticker)
                trend = analyze_h1_trend(df_h1)
                trends[nom_paire] = trend

                if is_active and trend != "INDISPONIBLE":
                    trade_info = check_m15_signal(df_m15, trend)
                    if trade_info:
                        signals[nom_paire] = trade_info

            dashboard_text = f"<b>📊 DASHBOARD DAY TRADING FOREX</b>\n"
            dashboard_text += f"-----------------------------------\n"
            dashboard_text += f"⏰ <b>Dernier scan :</b> {now_utc_str}\n"
            dashboard_text += f"🎯 <b>Session :</b> {session_str}\n\n"
            dashboard_text += f"📈 <b>Tendances H1 Actuelles :</b>\n"

            for nom_paire, trend in trends.items():
                emoji = "🟢" if trend == "HAUSSIER" else ("🔴" if trend == "BAISSIER" else ("⚠️" if trend == "INDISPONIBLE" else "⚪"))
                dashboard_text += f"• <b>{nom_paire} :</b> {emoji} {trend}\n"

            dashboard_text += f"\n<b>Filtres :</b> Trend H1 + SMA200 M15 + RSI + ATR"

            success = False
            if dashboard_msg_id:
                success = update_telegram_message(dashboard_msg_id, dashboard_text)

            if not success:
                dashboard_msg_id = send_telegram_message(dashboard_text)

            # Envoi forcé des détails du signal
            for paire, trade in signals.items():
                digits = 3 if "JPY" in paire else 5
                dir_symbol = "🟢 BUY" if trade['direction'] == 'BUY' else "🔴 SELL"
                
                alert_text = f"🚨 <b>SIGNAL DE TRADING DETECTÉ</b> 🚨\n\n"
                alert_text += f"<b>Paire :</b> {paire}\n"
                alert_text += f"<b>Direction :</b> {dir_symbol}\n\n"
                alert_text += f"📍 <b>Prix d'entrée :</b> {trade['entry']:.{digits}f}\n"
                alert_text += f"🛑 <b>Stop Loss (SL) :</b> {trade['sl']:.{digits}f}\n"
                alert_text += f"🎯 <b>Take Profit 1 (TP1) :</b> {trade['tp1']:.{digits}f}\n"
                alert_text += f"🎯 <b>Take Profit 2 (TP2) :</b> {trade['tp2']:.{digits}f}\n"
                alert_text += f"🎯 <b>Take Profit 3 (TP3) :</b> {trade['tp3']:.{digits}f}\n\n"
                alert_text += f"⏰ <i>Heure : {now_utc_str}</i>"
                
                send_telegram_message(alert_text)

        except Exception as e:
            print(f"Erreur durant la boucle : {e}")

        time.sleep(300)

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    bot_loop()
