import os
import time
import threading
import datetime
import pytz
import requests
import yfinance as yf
from flask import Flask

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot SMC/ICT actif 24/7 !"

TOKEN_TELEGRAM = "8678124689:AAEwSb2_TTiSrFDR5K56ac3vER0gVpyZrNQ"
CHAT_ID_TELEGRAM = "6552598655"
FUSEAU_TAHITI = pytz.timezone('Pacific/Tahiti')

def envoyer_message_telegram(message):
    url = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/sendMessage"
    payload = {
        "chat_id": CHAT_ID_TELEGRAM,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Erreur Telegram : {e}")

def analyser_smc_ict(ticker_symbol):
    try:
        df = yf.Ticker(ticker_symbol).history(period="5d", interval="15m")
        if len(df) < 3:
            return None, None
        
        prix_actuel = round(df['Close'].iloc[-1], 2)
        b1_high = df['High'].iloc[-3]
        b3_low = df['Low'].iloc[-1]
        b1_low = df['Low'].iloc[-3]
        b3_high = df['High'].iloc[-1]
        
        signal = None
        
        if b3_low > b1_high:
            sl = round(b1_low, 2)
            distance_risque = prix_actuel - sl
            if distance_risque > 0:
                tp = round(prix_actuel + (distance_risque * 2), 2)
                signal = {"sens": "ACHAT (Long) 🟢", "motif": "Fair Value Gap (FVG) Haussier", "entree": prix_actuel, "sl": sl, "tp": tp}
        elif b3_high < b1_low:
            sl = round(b1_high, 2)
            distance_risque = sl - prix_actuel
            if distance_risque > 0:
                tp = round(prix_actuel - (distance_risque * 2), 2)
                signal = {"sens": "VENTE (Short) 🔴", "motif": "Fair Value Gap (FVG) Baissier", "entree": prix_actuel, "sl": sl, "tp": tp}
            
        return signal, prix_actuel
    except Exception as e:
        print(f"Erreur sur {ticker_symbol} : {e}")
        return None, None

def executer_scan(actif, ticker):
    signal, prix = analyser_smc_ict(ticker)
    maintenant_str = datetime.datetime.now(FUSEAU_TAHITI).strftime("%H:%M:%S")
    
    if signal:
        msg = (
            f"🎯 **SIGNAL SMC/ICT DÉTECTÉ** [{maintenant_str}]\n\n"
            f"• **Actif :** {actif}\n"
            f"• **Sens :** {signal['sens']}\n"
            f"• **Motif :** {signal['motif']}\n\n"
            f"📌 **PRIX D'ENTRÉE :** ${signal['entree']}\n"
            f"🛑 **STOP-LOSS (SL) :** ${signal['sl']}\n"
            f"🎯 **TAKE-PROFIT (TP) :** ${signal['tp']}\n\n"
            f"⚠️ *Gestion du risque : 1% max.*"
        )
        envoyer_message_telegram(msg)

def boucle_bot():
    while True:
        try:
            executer_scan("BTC/USD (Bitcoin)", "BTC-USD")
            executer_scan("XAU/USD (Or)", "GC=F")
        except Exception as e:
            print(f"Erreur : {e}")
        time.sleep(900)

threading.Thread(target=boucle_bot, daemon=True).start()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
