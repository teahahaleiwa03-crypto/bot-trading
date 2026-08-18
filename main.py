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

# Mémoire globale pour éviter les signaux répétés et le hedging
dernier_signal = {actif: None for actif in ACTIFS.keys()}

# ==========================================
# FONCTIONS AUXILIAIRES
# ==========================================
def envoyer_telegram(message):
    """Envoie une alerte formatée sur votre canal Telegram."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Erreur : Jetons Telegram manquants dans les variables d'environnement.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Erreur d'envoi Telegram : {e}")

def est_dans_killzone():
    """Vérifie si l'heure actuelle (UTC) correspond aux sessions de Londres ou New York."""
    heure_utc = datetime.utcnow().hour
    # Session de Londres (8h - 11h UTC) OU Session de New York (13h - 17h UTC)
    return (8 <= heure_utc < 11) or (13 <= heure_utc < 17)

def obtenir_tendance_1h(ticker):
    """Détermine la tendance générale sur l'unité de temps 1h (Moyenne Mobile 20)."""
    data_1h = yf.download(ticker, period="5d", interval="1h", progress=False)
    if data_1h.empty:
        return None
    if isinstance(data_1h.columns, pd.MultiIndex):
        data_1h.columns = data_1h.columns.get_level_values(0)
    
    sma20 = data_1h['Close'].rolling(window=20).mean()
    dernier_prix = data_1h['Close'].iloc[-1]
    
    if dernier_prix > sma20.iloc[-1]:
        return "HAUSSIER"
    elif dernier_prix < sma20.iloc[-1]:
        return "BAISSIER"
    return None

def analyser_fvg_haute_probabilite(df, tendance_1h):
    """Filtre et valide un setup SMC/ICT uniquement si aligné avec le timeframe H1."""
    if len(df) < 5:
        return None, None

    c1, c2, c3 = df.iloc[-3], df.iloc[-2], df.iloc[-1]
    plus_haut_recent = df['High'].iloc[-5:-2].max()
    plus_bas_recent = df['Low'].iloc[-5:-2].min()

    # SETUP ACHAT : Tendance H1 Haussière + Break of Structure (BOS) + FVG Haussier
    if tendance_1h == "HAUSSIER":
        if c3['Low'] > c1['High'] and c3['Close'] > plus_haut_recent:
            prix_entree = c3['Close']
            stop_loss = c1['High']
            take_profit = prix_entree + (2.5 * (prix_entree - stop_loss)) # Ratio 1:2.5
            return "BUY", (prix_entree, stop_loss, take_profit)

    # SETUP VENTE : Tendance H1 Baissière + Break of Structure (BOS) + FVG Baissier
    elif tendance_1h == "BAISSIER":
        if c3['High'] < c1['Low'] and c3['Close'] < plus_bas_recent:
            prix_entree = c3['Close']
            stop_loss = c1['Low']
            take_profit = prix_entree - (2.5 * (stop_loss - prix_entree)) # Ratio 1:2.5
            return "SELL", (prix_entree, stop_loss, take_profit)

    return None, None

def analyser_marche():
    """Scanne les actifs et applique les filtres de sécurité."""
    global dernier_signal

    # Filtre 1 : Analyse uniquement durant les Kill Zones
    if not est_dans_killzone():
        print("Hors Kill Zone (Londres/NY). Analyse suspendue pour éviter les faux signaux.")
        return

    for nom_actif, ticker in ACTIFS.items():
        try:
            # Filtre 2 : Vérification de la tendance H1
            tendance_1h = obtenir_tendance_1h(ticker)
            if not tendance_1h:
                continue

            # Téléchargement des bougies 15 minutes
            data = yf.download(ticker, period="3d", interval="15m", progress=False)
            if data.empty:
                continue
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.get_level_values(0)

            # Filtre 3 : Validation du setup SMC/ICT
            signal, niveaux = analyser_fvg_haute_probabilite(data, tendance_1h)

            # Filtre 4 : Anti-doublons et anti-hedging
            if signal in ["BUY", "SELL"] and signal != dernier_signal[nom_actif]:
                pe, sl, tp = niveaux
                sens_txt = "ACHAT (Long) 🟢" if signal == "BUY" else "VENTE (Short) 🔴"
                
                msg = (
                    f"⭐ *SIGNAL HAUTE PROBABILITÉ (SMC/ICT)* ⭐\n\n"
                    f"• *Actif :* {nom_actif}\n"
                    f"• *Sens :* {sens_txt}\n"
                    f"• *Tendance H1 :* {tendance_1h}\n"
                    f"• *Validation :* BOS + FVG en Kill Zone\n\n"
                    f"📌 *PRIX D'ENTRÉE :* ${pe:.2f}\n"
                    f"🛑 *STOP-LOSS (SL) :* ${sl:.2f}\n"
                    f"🎯 *TAKE-PROFIT (TP) :* ${tp:.2f} (R:R 1:2.5)\n\n"
                    f"⚠️ *Gestion du risque recommandée :* 1% max."
                )
                envoyer_telegram(msg)
                dernier_signal[nom_actif] = signal
                print(f"Signal {signal} envoyé pour {nom_actif}")

        except Exception as e:
            print(f"Erreur d'analyse sur {nom_actif} : {e}")

# ==========================================
# SERVEUR FLASK & BOUCLE D'EXÉCUTION
# ==========================================
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot Trading SMC/ICT Haute Probabilité (Telegram) en ligne."

def boucle_bot():
    while True:
        print("Lancement du scan des marchés...")
        analyser_marche()
        time.sleep(900)  # Pause de 15 minutes entre chaque analyse

if __name__ == '__main__':
    # Démarrage du scan en arrière-plan
    t = Thread(target=boucle_bot)
    t.daemon = True
    t.start()
    
    # Lancement du serveur Web pour Render
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
