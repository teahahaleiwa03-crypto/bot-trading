import time
import datetime
import pytz
import requests
import yfinance as yf
import pandas as pd

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
        response = requests.post(url, json=payload, timeout=10)
        return response.ok
    except Exception as e:
        print(f"Erreur Telegram : {e}")
        return False

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
        
        # 1. FVG Haussier
        if b3_low > b1_high:
            sl = round(b1_low, 2)
            distance_risque = prix_actuel - sl
            if distance_risque > 0:
                tp = round(prix_actuel + (distance_risque * 2), 2)
                signal = {
                    "sens": "ACHAT (Long) 🟢",
                    "motif": "Fair Value Gap (FVG) Haussier",
                    "entree": prix_actuel,
                    "sl": sl,
                    "tp": tp
                }
                
        # 2. FVG Baissier
        elif b3_high < b1_low:
            sl = round(b1_high, 2)
            distance_risque = sl - prix_actuel
            if distance_risque > 0:
                tp = round(prix_actuel - (distance_risque * 2), 2)
                signal = {
                    "sens": "VENTE (Short) 🔴",
                    "motif": "Fair Value Gap (FVG) Baissier",
                    "entree": prix_actuel,
                    "sl": sl,
                    "tp": tp
                }
            
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
            f"⚠️ *Gestion du risque : 1% de capital max.*"
        )
        envoyer_message_telegram(msg)

# Boucle d'exécution continue H24
print("🤖 Bot démarré et en ligne 24/7...")
while True:
    try:
        executer_scan("BTC/USD (Bitcoin)", "BTC-USD")
        executer_scan("XAU/USD (Or)", "GC=F")
    except Exception as e:
        print(f"Erreur globale : {e}")
    
    # Pause de 15 minutes entre chaque analyse
    time.sleep(900)
