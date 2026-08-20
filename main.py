import os
import time
from datetime import datetime
import pytz
import yfinance as yf
import requests

# ==========================================
# CONFIGURATION ET VARIABLES D'ENVIRONNEMENT
# ==========================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Liste des paires surveillées
PAIRES = {
    "EUR/USD": "EURUSD=X",
    "GBP/USD": "GBPUSD=X",
    "GBP/JPY": "GBPJPY=X"
}

# Variable pour conserver l'ID du message Dashboard épinglé
dashboard_message_id = None

# ==========================================
# FONCTIONS TELEGRAM API
# ==========================================
def send_telegram_message(text):
    """Envoie un nouveau message sur Telegram."""
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
        print(f"Erreur lors de l'envoi du message Telegram : {e}")
        return None

def update_telegram_message(message_id, text):
    """Met à jour un message Telegram existant (Dashboard)."""
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
        print(f"Erreur lors de la mise à jour du message Telegram : {e}")

# ==========================================
# GESTION DES SESSIONS (24H/24 LUN-VEN)
# ==========================================
def check_session_active():
    """
    Vérifie si le marché Forex est ouvert (Du lundi au vendredi, 24h/24)
    """
    now_utc = datetime.now(pytz.utc)
    weekday = now_utc.weekday()  # 0 = Lundi, ..., 4 = Vendredi, 5 = Samedi, 6 = Dimanche
    
    if weekday < 5:
        return True, "🟢 ACTIVE (24/24 - Lun/Ven)"
    else:
        return False, "🔴 INACTIVE (Week-end)"

# ==========================================
# CALCUL DES INDICATEURS ET ANALYSE
# ==========================================
def get_market_data(ticker):
    """Récupère les données historiques H1 et M15 via yfinance."""
    try:
        data_h1 = yf.download(ticker, period="10d", interval="1h", progress=False)
        data_m15 = yf.download(ticker, period="5d", interval="15m", progress=False)
        return data_h1, data_m15
    except Exception as e:
        print(f"Erreur de téléchargement des données pour {ticker} : {e}")
        return None, None

def analyze_h1_trend(df_h1):
    """Détermine la tendance générale H1 (EMA20 vs EMA50)."""
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
    """Exécute les filtres M15 pour valider un signal de trading."""
    if df_m15 is None or len(df_m15) < 200 or trend_h1 == "NEUTRE":
        return None

    close = df_m15['Close']
    high = df_m15['High']
    low = df_m15['Low']

    # 1. Moyenne Mobile SMA 200 sur M15
    sma200 = close.rolling(window=200).mean().iloc[-1]
    current_close = close.iloc[-1]

    # 2. RSI (14)
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    current_rsi = rsi.iloc[-1]

    # 3. ATR (14) - Volatilité
    tr = (high - low).combine((high - close.shift(1)).abs(), max).combine((low - close.shift(1)).abs(), max)
    atr = tr.rolling(window=14).mean().iloc[-1]
    current_candle_size = high.iloc[-1] - low.iloc[-1]
    volatility_ok = current_candle_size >= (0.6 * atr)

    # 4. Cassure du Plus Haut / Plus Bas des 10 dernières bougies
    swing_high = high.iloc[-11:-1].max()
    swing_low = low.iloc[-11:-1].min()

    # --- Verification BUY ---
    if trend_h1 == "HAUSSIER" and current_close > sma200:
        if 50 < current_rsi < 70 and current_close > swing_high and volatility_ok:
            return "BUY"

    # --- Verification SELL ---
    if trend_h1 == "BAISSIER" and current_close < sma200:
        if 30 < current_rsi < 50 and current_close < swing_low and volatility_ok:
            return "SELL"

    return None

# ==========================================
# FONCTION PRINCIPALE (DASHBOARD & SCRIP)
# ==========================================
def main():
    global dashboard_message_id
    
    is_active, session_str = check_session_active()
    now_utc_str = datetime.now(pytz.utc).strftime("%H:%M UTC")

    trends = {}
    signals = {}

    for nom_paire, ticker in PAIRES.items():
        df_h1, df_m15 = get_market_data(ticker)
        
        # Pause courte pour respecter les limites de l'API yfinance
        time.sleep(1)

        trend = analyze_h1_trend(df_h1)
        trends[nom_paire] = trend

        if is_active:
            sig = check_m15_signal(df_m15, trend)
            if sig:
                signals[nom_paire] = sig

    # Construction du texte du Dashboard
    dashboard_text = f"<b>📊 DASHBOARD DAY TRADING FOREX</b>\n"
    dashboard_text += f"-----------------------------------\n"
    dashboard_text += f"⏰ <b>Dernier scan :</b> {now_utc_str}\n"
    dashboard_text += f"🎯 <b>Session :</b> {session_str}\n\n"
    dashboard_text += f"📈 <b>Tendances H1 Actuelles :</b>\n"

    for nom_paire, trend in trends.items():
        emoji = "🟢" if trend == "HAUSSIER" else ("🔴" if trend == "BAISSIER" else "⚪")
        dashboard_text += f"• <b>{nom_paire} :</b> {emoji} {trend}\n"

    dashboard_text += f"\n<b>Filtres :</b> Trend H1 + SMA200 M15 + RSI + ATR Volatilité"

    # Mise à jour ou envoi du Dashboard Telegram
    if dashboard_message_id is None:
        dashboard_message_id = send_telegram_message(dashboard_text)
    else:
        update_telegram_message(dashboard_message_id, dashboard_text)

    # Envoi des messages d'Alerte si des signaux sont détectés
    for paire, signal in signals.items():
        alert_text = f"🚨 <b>SIGNAL DE TRADING DETECTÉ</b> 🚨\n\n"
        alert_text += f"<b>Paire :</b> {paire}\n"
        alert_text += f"<b>Direction :</b> {'🟢 BUY' if signal == 'BUY' else '🔴 SELL'}\n"
        alert_text += f"<b>Heure :</b> {now_utc_str}\n"
        send_telegram_message(alert_text)

if __name__ == "__main__":
    main()
