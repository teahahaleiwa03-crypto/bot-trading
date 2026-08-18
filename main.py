import os
import time
import requests
import yfinance as yf
import pandas as pd
from datetime import datetime
from flask import Flask
from threading import Thread

# ==========================================
# CONFIGURATION
# ==========================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

ACTIFS = {
    "EUR/USD": "EURUSD=X",
    "GBP/USD": "GBPUSD=X",
    "GBP/JPY": "GBPJPY=X"
}

dernier_signal = {actif: None for actif in ACTIFS.keys()}
MESSAGE_PIN_ID = None

# ==========================================
# FONCTIONS TELEGRAM & DASHBOARD
# ==========================================
def envoyer_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Variables TELEGRAM manquantes dans Environment.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        res = requests.post(url, json=payload, timeout=10).json()
        if not res.get("ok"):
            print(f"❌ Erreur API Telegram: {res}")
    except Exception as e:
        print(f"❌ Erreur envoi Telegram: {e}")

def mettre_a_jour_dashboard(tendances, en_session):
    global MESSAGE_PIN_ID
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return

    statut_session = "🟢 ACTIVE (Londres / NY)" if en_session else "🔴 INACTIVE (Hors Session)"
    heure_actuelle = datetime.utcnow().strftime("%H:%M UTC")

    texte = (
        f"📊 *DASHBOARD DAY TRADING FOREX*\n"
        f"-----------------------------------\n"
        f"⏰ *Dernier scan :* {heure_actuelle}\n"
        f"🎯 *Session :* {statut_session}\n\n"
        f"📈 *Tendances H1 Actuelles :*\n"
    )

    for actif, tend in tendances.items():
        emoji = "🟢 HAUSSIER" if tend == "HAUSSIER" else ("🔴 BAISSIER" if tend == "BAISSIER" else "⚪ NEUTRE")
        texte += f"• *{actif} :* {emoji}\n"

    texte += "\n*Filtres :* Trend H1 + SMA200 M15 + RSI + ATR Volatilité"

    if MESSAGE_PIN_ID:
        try:
            url_edit = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageText"
            payload = {"chat_id": TELEGRAM_CHAT_ID, "message_id": MESSAGE_PIN_ID, "text": texte, "parse_mode": "Markdown"}
            res = requests.post(url_edit, json=payload, timeout=10).json()
            if res.get("ok"):
                return
        except Exception as e:
            print(f"⚠️ Erreur édition Dashboard: {e}")

    try:
        url_send = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": texte, "parse_mode": "Markdown"}
        res_send = requests.post(url_send, json=payload, timeout=10).json()

        if res_send.get("ok"):
            MESSAGE_PIN_ID = res_send["result"]["message_id"]
            url_pin = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/pinChatMessage"
            requests.post(url_pin, json={"chat_id": TELEGRAM_CHAT_ID, "message_id": MESSAGE_PIN_ID, "disable_notification": True})
            print("📌 Nouveau Dashboard envoyé et épinglé.")
        else:
            print(f"❌ Échec envoi Dashboard: {res_send}")
    except Exception as e:
        print(f"❌ Erreur création Dashboard: {e}")

# ==========================================
# STRATÉGIE DAY TRADING MULTI-TP
# ==========================================
def est_jour_et_session_valide():
    maintenant = datetime.utcnow()
    if maintenant.weekday() > 4:
        return False
    return 7 <= maintenant.hour < 17

def obtenir_tendance_h1(ticker):
    try:
        t = yf.Ticker(ticker)
        data_1h = t.history(period="5d", interval="1h")
        if data_1h.empty or len(data_1h) < 30:
            return "NEUTRE"

        ema20 = data_1h['Close'].ewm(span=20, adjust=False).mean().iloc[-1]
        ema50 = data_1h['Close'].ewm(span=50, adjust=False).mean().iloc[-1]
        prix = data_1h['Close'].iloc[-1]

        if prix > ema20 and ema20 > ema50:
            return "HAUSSIER"
        elif prix < ema20 and ema20 < ema50:
            return "BAISSIER"
        return "NEUTRE"
    except Exception as e:
        print(f"⚠️ Erreur Tendance H1 {ticker}: {e}")
        return "NEUTRE"

def analyser_signal_daytrading(df, tendance_h1):
    if len(df) < 200:
        return None, None

    df['sma200'] = df['Close'].rolling(window=200).mean()
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))

    df['tr'] = pd.concat([
        df['High'] - df['Low'],
        (df['High'] - df['Close'].shift(1)).abs(),
        (df['Low'] - df['Close'].shift(1)).abs()
    ], axis=1).max(axis=1)
    df['atr'] = df['tr'].rolling(window=14).mean()

    c3 = df.iloc[-1]
    rsi_val = c3['rsi']
    atr_val = c3['atr']
    sma200_val = c3['sma200']

    filtre_volatilite = (c3['High'] - c3['Low']) >= (0.6 * atr_val)
    swing_high = df['High'].iloc[-11:-1].max()
    swing_low = df['Low'].iloc[-11:-1].min()

    rsi_buy = (rsi_val > 50) and (rsi_val < 70)
    cond_buy = (tendance_h1 == "HAUSSIER") and (c3['Close'] > sma200_val) and rsi_buy and (c3['Close'] > swing_high) and filtre_volatilite

    rsi_sell = (rsi_val < 50) and (rsi_val > 30)
    cond_sell = (tendance_h1 == "BAISSIER") and (c3['Close'] < sma200_val) and rsi_sell and (c3['Close'] < swing_low) and filtre_volatilite

    if cond_buy:
        pe = float(c3['Close'])
        sl = float(min(c3['Low'], df['Low'].iloc[-2]))
        distance_risk = pe - sl
        if distance_risk <= 0:
            return None, None
        return "BUY", (pe, sl, pe + 0.5 * distance_risk, pe + 1.0 * distance_risk, pe + 1.8 * distance_risk)

    elif cond_sell:
        pe = float(c3['Close'])
        sl = float(max(c3['High'], df['High'].iloc[-2]))
        distance_risk = sl - pe
        if distance_risk <= 0:
            return None, None
        return "SELL", (pe, sl, pe - 0.5 * distance_risk, pe - 1.0 * distance_risk, pe - 1.8 * distance_risk)

    return None, None

def analyser_marche():
    global dernier_signal
    print(f"🔍 [{datetime.utcnow().strftime('%H:%M:%S UTC')}] Début de l'analyse des marchés...")
    session_valide = est_jour_et_session_valide()
    tendances = {}

    for nom_actif, ticker in ACTIFS.items():
        try:
            tendance_h1 = obtenir_tendance_h1(ticker)
            tendances[nom_actif] = tendance_h1

            if not session_valide or tendance_h1 == "NEUTRE":
                continue

            t = yf.Ticker(ticker)
            data = t.history(period="7d", interval="15m")
            if data.empty:
                continue

            signal, niveaux = analyser_signal_daytrading(data, tendance_h1)

            if signal in ["BUY", "SELL"] and signal != dernier_signal[nom_actif]:
                pe, sl, tp1, tp2, tp3 = niveaux
                sens_txt = "ACHAT (LONG) 🟢" if signal == "BUY" else "VENTE (SHORT) 🔴"
                dec = 3 if "JPY" in nom_actif else 5

                msg = (
                    f"🔥 *SIGNAL DAY TRADING HIGH PROBABILITY*\n\n"
                    f"📍 *Actif :* {nom_actif}\n"
                    f"🎯 *Sens :* {sens_txt}\n"
                    f"📈 *Tendance H1 :* {tendance_h1}\n\n"
                    f"💵 *PRIX D'ENTRÉE :* `{pe:.{dec}f}`\n"
                    f"🎯 *TAKE-PROFIT 1 :* `{tp1:.{dec}f}`\n"
                    f"🎯 *TAKE-PROFIT 2 :* `{tp2:.{dec}f}`\n"
                    f"🎯 *TAKE-PROFIT 3 :* `{tp3:.{dec}f}`\n"
                    f"🛡️ *STOP-LOSS :* `{sl:.{dec}f}`\n\n"
                    f"💡 *Gestion du risque :* Dès que TP1 est atteint, déplacez le SL au prix d'entrée."
                )
                envoyer_telegram(msg)
                dernier_signal[nom_actif] = signal

        except Exception as e:
            print(f"❌ Erreur sur {nom_actif}: {e}")

    mettre_a_jour_dashboard(tendances, session_valide)
    print("✅ Scan terminé.")

# ==========================================
# SERVEUR FLASK
# ==========================================
app = Flask(__name__)

@app.route('/')
def home():
    # Déclenche un scan à chaque fois que le serveur est sollicité par un pinger ou un navigateur
    Thread(target=analyser_marche).start()
    return "Bot Day Trading Forex Opérationnel. Scan en cours..."

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
