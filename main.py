import os
import time
import requests
import yfinance as yf
import pandas as pd
from datetime import datetime
from flask import Flask
from threading import Thread

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

ACTIFS = {
    "BTC/USD": "BTC-USD",
    "XAU/USD (Or)": "GC=F"
}

dernier_signal = {actif: None for actif in ACTIFS.keys()}
MESSAGE_PIN_ID = None

def envoyer_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Erreur Telegram: {e}")

def mettre_a_jour_dashboard(tendances, en_killzone):
    global MESSAGE_PIN_ID
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return

    statut_kz = "🟢 ACTIVE (Londres / NY)" if en_killzone else "🔴 INACTIVE (Hors session)"
    heure_actuelle = datetime.utcnow().strftime("%H:%M UTC")

    texte = (
        f"📌 *DASHBOARD BOT TRADING SMC STRICT (M15)*\n"
        f"────────────────────────\n"
        f"⏱️ *Dernier scan :* {heure_actuelle}\n"
        f"🎯 *Kill Zone :* {statut_kz}\n\n"
        f"📊 *Tendances H1 (EMA 50/200) :*\n"
    )

    for actif, tend in tendances.items():
        emoji = "📈" if tend == "HAUSSIER" else ("📉" if tend == "BAISSIER" else "⚪ NEUTRE")
        texte += f"• *{actif} :* {emoji} {tend}\n"

    texte += f"\n⚙️ *Filtre :* Retracement FVG + Validation Swing"

    if MESSAGE_PIN_ID:
        url_edit = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageText"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "message_id": MESSAGE_PIN_ID, "text": texte, "parse_mode": "Markdown"}
        res = requests.post(url_edit, json=payload, timeout=10).json()
        if res.get("ok"):
            return

    url_send = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": texte, "parse_mode": "Markdown"}
    res_send = requests.post(url_send, json=payload, timeout=10).json()

    if res_send.get("ok"):
        MESSAGE_PIN_ID = res_send["result"]["message_id"]
        url_pin = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/pinChatMessage"
        requests.post(url_pin, json={"chat_id": TELEGRAM_CHAT_ID, "message_id": MESSAGE_PIN_ID, "disable_notification": True})

def est_dans_killzone():
    heure_utc = datetime.utcnow().hour
    return (8 <= heure_utc < 11) or (13 <= heure_utc < 17)

def obtenir_tendance_1h_stricte(ticker):
    data_1h = yf.download(ticker, period="10d", interval="1h", progress=False)
    if data_1h.empty or len(data_1h) < 200:
        return "INCONNUE"
    if isinstance(data_1h.columns, pd.MultiIndex):
        data_1h.columns = data_1h.columns.get_level_values(0)
    
    ema50 = data_1h['Close'].ewm(span=50, adjust=False).mean().iloc[-1]
    ema200 = data_1h['Close'].ewm(span=200, adjust=False).mean().iloc[-1]
    dernier_prix = data_1h['Close'].iloc[-1]

    if dernier_prix > ema50 and ema50 > ema200:
        return "HAUSSIER"
    elif dernier_prix < ema50 and ema50 < ema200:
        return "BAISSIER"
    return "NEUTRE"

def analyser_smc_strict(df, tendance_1h):
    if len(df) < 10:
        return None, None

    c1, c2, c3 = df.iloc[-3], df.iloc[-2], df.iloc[-1]
    swing_low = df['Low'].iloc[-6:-1].min()
    swing_high = df['High'].iloc[-6:-1].max()

    # Retracement FVG Achat
    if tendance_1h == "HAUSSIER":
        fvg_top = c1['High']
        if c2['Low'] > fvg_top: # FVG présent
            if c3['Low'] <= fvg_top and c3['Close'] > fvg_top: # Retracement validé
                pe = c3['Close']
                sl = swing_low
                tp = pe + (2.0 * (pe - sl))
                return "BUY", (pe, sl, tp)

    # Retracement FVG Vente
    elif tendance_1h == "BAISSIER":
        fvg_bot = c1['Low']
        if c2['High'] < fvg_bot: # FVG présent
            if c3['High'] >= fvg_bot and c3['Close'] < fvg_bot: # Retracement validé
                pe = c3['Close']
                sl = swing_high
                tp = pe - (2.0 * (sl - pe))
                return "SELL", (pe, sl, tp)

    return None, None

def analyser_marche():
    global dernier_signal
    en_kz = est_dans_killzone()
    tendances = {}

    for nom_actif, ticker in ACTIFS.items():
        try:
            tendance_1h = obtenir_tendance_1h_stricte(ticker)
            tendances[nom_actif] = tendance_1h

            if not en_kz or tendance_1h == "NEUTRE":
                continue

            data = yf.download(ticker, period="3d", interval="15m", progress=False)
            if data.empty:
                continue
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.get_level_values(0)

            signal, niveaux = analyser_smc_strict(data, tendance_1h)

            if signal in ["BUY", "SELL"] and signal != dernier_signal[nom_actif]:
                pe, sl, tp = niveaux
                sens_txt = "ACHAT (Retracement) 🟢" if signal == "BUY" else "VENTE (Retracement) 🔴"
                
                msg = (
                    f"⭐ *SIGNAL SMC STRICT (RETRACEMENT)* ⭐\n\n"
                    f"• *Actif :* {nom_actif}\n"
                    f"• *Sens :* {sens_txt}\n"
                    f"• *Tendance H1 :* {tendance_1h}\n\n"
                    f"📌 *PRIX D'ENTRÉE :* ${pe:.2f}\n"
                    f"🛑 *STOP-LOSS (Swing) :* ${sl:.2f}\n"
                    f"🎯 *TAKE-PROFIT :* ${tp:.2f} (R:R 1:2.0)"
                )
                envoyer_telegram(msg)
                dernier_signal[nom_actif] = signal

        except Exception as e:
            print(f"Erreur d'analyse sur {nom_actif} : {e}")

    mettre_a_jour_dashboard(tendances, en_kz)

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot SMC Strict actif sur Render."

def boucle_bot():
    while True:
        analyser_marche()
        time.sleep(900)

if __name__ == '__main__':
    t = Thread(target=boucle_bot)
    t.daemon = True
    t.start()
    
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
