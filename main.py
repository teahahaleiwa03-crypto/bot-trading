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
    "XAU/USD (Or)": "GC=F",
    "BTC/USD": "BTC-USD"
}

dernier_signal = {actif: None for actif in ACTIFS.keys()}

def envoyer_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Erreur Telegram: {e}")

def est_dans_killzone():
    heure_utc = datetime.utcnow().hour
    # Session Londres (08h-11h) ou New York (13h-17h)
    return (8 <= heure_utc < 11) or (13 <= heure_utc < 17)

def analyser_smc_h1(ticker):
    # Téléchargement des données en 1H pour éviter le bruit
    df = yf.download(ticker, period="15d", interval="1h", progress=False)
    if df.empty or len(df) < 50:
        return None, None

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # Indicateurs de Tendance H4 via EMA
    df['ema20'] = df['Close'].ewm(span=20, adjust=False).mean()
    df['ema50'] = df['Close'].ewm(span=50, adjust=False).mean()

    c1, c2, c3 = df.iloc[-3], df.iloc[-2], df.iloc[-1]
    
    tendance_haussiere = c3['Close'] > df['ema20'].iloc[-1] and df['ema20'].iloc[-1] > df['ema50'].iloc[-1]
    tendance_baissiere = c3['Close'] < df['ema20'].iloc[-1] and df['ema20'].iloc[-1] < df['ema50'].iloc[-1]

    # Détection FVG + Retracement
    swing_low = df['Low'].iloc[-10:-1].min()
    swing_high = df['High'].iloc[-10:-1].max()

    # ACHAT : Tendance Haussière H1 + FVG + Prix qui revient tester le bas du FVG
    if tendance_haussiere:
        fvg_top = c1['High']
        if c2['Low'] > fvg_top: # Présence FVG
            if c3['Low'] <= fvg_top and c3['Close'] > fvg_top: # Retracement validé
                pe = c3['Close']
                sl = swing_low
                tp = pe + (1.5 * (pe - sl)) # Ratio 1:1.5 sécurisé
                return "BUY", (pe, sl, tp)

    # VENTE : Tendance Baissière H1 + FVG + Prix qui reteste la zone
    elif tendance_baissiere:
        fvg_bot = c1['Low']
        if c2['High'] < fvg_bot: # Présence FVG
            if c3['High'] >= fvg_bot and c3['Close'] < fvg_bot: # Retracement validé
                pe = c3['Close']
                sl = swing_high
                tp = pe - (1.5 * (sl - pe)) # Ratio 1:1.5 sécurisé
                return "SELL", (pe, sl, tp)

    return None, None

def analyser_marche():
    global dernier_signal
    en_kz = est_dans_killzone()

    if not en_kz:
        return

    for nom_actif, ticker in ACTIFS.items():
        try:
            signal, niveaux = analyser_smc_h1(ticker)

            if signal in ["BUY", "SELL"] and signal != dernier_signal[nom_actif]:
                pe, sl, tp = niveaux
                sens_txt = "ACHAT HIGH PROBABILITY (H1) 🟢" if signal == "BUY" else "VENTE HIGH PROBABILITY (H1) 🔴"
                
                msg = (
                    f"🎯 *SIGNAL SMC H1 HIGH PROBABILITY* 🎯\n\n"
                    f"• *Actif :* {nom_actif}\n"
                    f"• *Sens :* {sens_txt}\n"
                    f"• *Unité de temps :* 1 Heure (H1)\n\n"
                    f"📌 *Entrée :* ${pe:.2f}\n"
                    f"🛑 *Stop-Loss :* ${sl:.2f}\n"
                    f"🎯 *Take-Profit (R:R 1.5) :* ${tp:.2f}\n\n"
                    f"💡 *Conseil :* N'entrez sur le broker que si le Risk/Reward est respecté."
                )
                envoyer_telegram(msg)
                dernier_signal[nom_actif] = signal

        except Exception as e:
            print(f"Erreur d'analyse sur {nom_actif} : {e}")

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot Trading SMC H1 Actif."

def boucle_bot():
    while True:
        analyser_marche()
        time.sleep(1800) # Scan toutes les 30 minutes

if __name__ == '__main__':
    t = Thread(target=boucle_bot)
    t.daemon = True
    t.start()
    
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
