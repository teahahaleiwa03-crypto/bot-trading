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
    "BTC/USD": "BTC-USD",
    "XAU/USD (Or)": "GC=F"
}

dernier_signal = {actif: None for actif in ACTIFS.keys()}
MESSAGE_PIN_ID = None  # Stocke l'ID du message épinglé pour le mettre à jour

# ==========================================
# FONCTIONS TELEGRAM & DASHBOARD ÉPINGLÉ
# ==========================================
def envoyer_telegram(message):
    """Envoie un message standard (alerte) sur Telegram."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Erreur Telegram: {e}")

def mettre_a_jour_dashboard(tendances, en_killzone):
    """Maintient à jour un message fixe épinglé en haut du canal."""
    global MESSAGE_PIN_ID
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return

    statut_kz = "🟢 ACTIVE (Londres / NY)" if en_killzone else "🔴 INACTIVE (Hors session)"
    heure_actuelle = datetime.utcnow().strftime("%H:%M UTC")

    texte = (
        f"📌 *DASHBOARD BOT TRADING SMC/ICT (M15)*\n"
        f"────────────────────────\n"
        f"⏱️ *Dernier scan :* {heure_actuelle}\n"
        f"🎯 *Kill Zone :* {statut_kz}\n\n"
        f"📊 *Tendances H1 Actuelles :*\n"
    )

    for actif, tend in tendances.items():
        emoji = "📈" if tend == "HAUSSIER" else ("📉" if tend == "BAISSIER" else "❓")
        texte += f"• *{actif} :* {emoji} {tend}\n"

    texte += f"\n⚙️ *Statut :* En attente de setup FVG + BOS..."

    # Édition du message s'il existe déjà
    if MESSAGE_PIN_ID:
        url_edit = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageText"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "message_id": MESSAGE_PIN_ID,
            "text": texte,
            "parse_mode": "Markdown"
        }
        res = requests.post(url_edit, json=payload, timeout=10).json()
        if res.get("ok"):
            return

    # Sinon création du message et épinglage
    url_send = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": texte, "parse_mode": "Markdown"}
    res_send = requests.post(url_send, json=payload, timeout=10).json()

    if res_send.get("ok"):
        MESSAGE_PIN_ID = res_send["result"]["message_id"]
        url_pin = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/pinChatMessage"
        requests.post(url_pin, json={"chat_id": TELEGRAM_CHAT_ID, "message_id": MESSAGE_PIN_ID, "disable_notification": True})

# ==========================================
# STRATÉGIE SMC / ICT (M15)
# ==========================================
def est_dans_killzone():
    heure_utc = datetime.utcnow().hour
    return (8 <= heure_utc < 11) or (13 <= heure_utc < 17)

def obtenir_tendance_1h(ticker):
    data_1h = yf.download(ticker, period="5d", interval="1h", progress=False)
    if data_1h.empty:
        return "INCONNUE"
    if isinstance(data_1h.columns, pd.MultiIndex):
        data_1h.columns = data_1h.columns.get_level_values(0)
    
    sma20 = data_1h['Close'].rolling(window=20).mean()
    dernier_prix = data_1h['Close'].iloc[-1]
    return "HAUSSIER" if dernier_prix > sma20.iloc[-1] else "BAISSIER"

def analyser_fvg_haute_probabilite(df, tendance_1h):
    if len(df) < 5:
        return None, None

    c1, c2, c3 = df.iloc[-3], df.iloc[-2], df.iloc[-1]
    plus_haut_recent = df['High'].iloc[-5:-2].max()
    plus_bas_recent = df['Low'].iloc[-5:-2].min()

    if tendance_1h == "HAUSSIER" and c3['Low'] > c1['High'] and c3['Close'] > plus_haut_recent:
        pe = c3['Close']
        sl = c1['High']
        tp = pe + (2.5 * (pe - sl))
        return "BUY", (pe, sl, tp)

    elif tendance_1h == "BAISSIER" and c3['High'] < c1['Low'] and c3['Close'] < plus_bas_recent:
        pe = c3['Close']
        sl = c1['Low']
        tp = pe - (2.5 * (sl - pe))
        return "SELL", (pe, sl, tp)

    return None, None

def analyser_marche():
    global dernier_signal
    en_kz = est_dans_killzone()
    tendances = {}

    for nom_actif, ticker in ACTIFS.items():
        try:
            tendance_1h = obtenir_tendance_1h(ticker)
            tendances[nom_actif] = tendance_1h

            if not en_kz:
                continue

            data = yf.download(ticker, period="3d", interval="15m", progress=False)
            if data.empty:
                continue
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.get_level_values(0)

            signal, niveaux = analyser_fvg_haute_probabilite(data, tendance_1h)

            if signal in ["BUY", "SELL"] and signal != dernier_signal[nom_actif]:
                pe, sl, tp = niveaux
                sens_txt = "ACHAT (Long) 🟢" if signal == "BUY" else "VENTE (Short) 🔴"
                
                msg = (
                    f"⭐ *SIGNAL HAUTE PROBABILITÉ (SMC/ICT)* ⭐\n\n"
                    f"• *Actif :* {nom_actif}\n"
                    f"• *Sens :* {sens_txt}\n"
                    f"• *Tendance H1 :* {tendance_1h}\n\n"
                    f"📌 *PRIX D'ENTRÉE :* ${pe:.2f}\n"
                    f"🛑 *STOP-LOSS :* ${sl:.2f}\n"
                    f"🎯 *TAKE-PROFIT :* ${tp:.2f} (R:R 1:2.5)"
                )
                envoyer_telegram(msg)
                dernier_signal[nom_actif] = signal

        except Exception as e:
            print(f"Erreur d'analyse sur {nom_actif} : {e}")

    mettre_a_jour_dashboard(tendances, en_kz)

# ==========================================
# SERVEUR FLASK & BOUCLE
# ==========================================
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot Trading SMC/ICT M15 actif sur Render."

def boucle_bot():
    while True:
        analyser_marche()
        time.sleep(900)  # Scan toutes les 15 minutes

if __name__ == '__main__':
    t = Thread(target=boucle_bot)
    t.daemon = True
    t.start()
    
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
