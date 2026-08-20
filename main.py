import os
import time
import threading
from datetime import datetime
import pytz
import yfinance as yf
import requests
from flask import Flask

# ==========================================
# MINI SERVEUR FLASK POUR RENDER WEB SERVICE
# ==========================================
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot Trading Forex is running!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# ==========================================
# CONFIGURATION ET VARIABLES D'ENVIRONNEMENT
# ==========================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

PAIRES = {
    "EUR/USD": "EURUSD=X",
    "GBP/USD": "GBPUSD=X",
    "GBP/JPY": "GBPJPY=X"
}

dashboard_message_id = None

# ==========================================
# FONCTIONS TELEGRAM API
# ==========================================
def send_telegram_message(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Erreur: Les tokens Telegram ne sont pas configurés.")
        return None
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        res = requests.post(url, json=payload, timeout=10)
        return res.json().get("result", {}).get("message_id")
    except Exception as e:
        print(f"Erreur Telegram : {e}")
        return None

def update_telegram_message(message_id, text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID or not message_id:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageText"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Erreur Mise à jour Telegram : {e}")

# ==========================================
# GESTION DES SESSIONS (24H/24 LUN-VEN)
# ==========================================
def check_session_active():
    now_utc = datetime.now(pytz.utc)
    weekday = now_utc.weekday()
    if weekday < 5:
        return True, "🟢 ACTIVE (24/24 - Lun/Ven)"
    else:
        return False, "🔴 INACTIVE (Week-end)"

# ==========================================
# CALCUL DES INDICATEURS ET ANALYSE
# ==========================================
def get_market_data(ticker):
    try:
        data_h1 = yf.download(ticker, period="10d", interval="1h", progress=False)
        data_m15 = yf.download(ticker, period="5d", interval="15m", progress=False)
        return data_h1, data_m15
    except Exception as e:
        print(f"Erreur téléchargement {ticker} : {e}")
        return None, None

def analyze_h1_trend(df_h1):
    if df_h1 is None or len(df_h1) < 50:
        return "NEUTRE"
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
    if df_m15 is None or len(df_m15) < 200 or trend_h1 == "NEUTRE":
        return None
    close = df_m15['Close']
    high = df_m15['High']
    low = df_m15['Low']

    sma200 = close.rolling(window=200).mean().iloc[-1]
    current_close = close.iloc[-1]

    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    current_rsi = rsi.iloc[-1]

    tr = (high - low).combine((high - close.shift(1)).abs(), max).combine((low - close.shift(1)).abs(), max)
    atr = tr.rolling(window=14).mean().iloc[-1]
    current_candle_size = high.iloc[-1] - low.iloc[-1]
    volatility_ok = current_candle_size >= (0.6 * atr)

    swing_high = high.iloc[-11:-1].max()
    swing_low = low.iloc[-11:-1].min()

    if trend_h1 == "HAUSSIER" and current_close > sma200:
        if 50 < current_rsi < 70 and current_close > swing_high and volatility_ok:
            return "BUY"

    if trend_h1 == "BAISSIER" and current_close < sma200:
        if 30 < current_rsi < 50 and current_close < swing_low and volatility_ok:
            return "SELL"

    return None

def bot_loop():
    """Boucle d'exécution permanente du bot."""
    global dashboard_message_id
    while True:
        try:
            is_active, session_str = check_session_active()
            now_utc_str = datetime.now(pytz.utc).strftime("%H:%M UTC")

            trends = {}
            signals = {}

            for nom_paire, ticker in PAIRES.items():
                df_h1, df_m15 = get_market_data(ticker)
                time.sleep(1)
                trend = analyze_h1_trend(df_h1)
                trends[nom_paire] = trend

                if is_active:
                    sig = check_m15_signal(df_m15, trend)
                    if sig:
                        signals[nom_paire] = sig

            dashboard_text = f"<b>📊 DASHBOARD DAY TRADING FOREX</b>\n"
            dashboard_text += f"-----------------------------------\n"
            dashboard_text += f"⏰ <b>Dernier scan :</b> {now_utc_str}\n"
            dashboard_text += f"🎯 <b>Session :</b> {session_str}\n\n"
            dashboard_text += f"📈 <b>Tendances H1 Actuelles :</b>\n"

            for nom_paire, trend in trends.items():
                emoji = "🟢" if trend == "HAUSSIER" else ("🔴" if trend == "BAISSIER" else "⚪")
                dashboard_text += f"• <b>{nom_paire} :</b> {emoji} {trend}\n"

            dashboard_text += f"\n<b>Filtres :</b> Trend H1 + SMA200 M15 + RSI + ATR Volatilité"

            if dashboard_message_id is None:
                dashboard_message_id = send_telegram_message(dashboard_text)
            else:
                update_telegram_message(dashboard_message_id, dashboard_text)

            for paire, signal in signals.items():
                alert_text = f"🚨 <b>SIGNAL DE TRADING DETECTÉ</b> 🚨\n\n"
                alert_text += f"<b>Paire :</b> {paire}\n"
                alert_text += f"<b>Direction :</b> {'🟢 BUY' if signal == 'BUY' else '🔴 SELL'}\n"
                alert_text += f"<b>Heure :</b> {now_utc_str}\n"
                send_telegram_message(alert_text)

        except Exception as e:
            print(f"Erreur durant la boucle : {e}")

        # Pause de 5 minutes entre chaque scan
        time.sleep(300)

if __name__ == "__main__":
    # Lancement du serveur web Flask sur un thread secondaire
    threading.Thread(target=run_flask, daemon=True).start()
    # Lancement de la boucle d'analyse du bot
    bot_loop()
