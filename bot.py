import logging
import os
from datetime import datetime
import requests # Importato ma non ancora usato per DB
import csv      # Importato ma non ancora usato per DB
from io import StringIO # Importato ma non ancora usato per DB
import psycopg2 # Importato ma non ancora usato per DB
import psycopg2.extras # Importato ma non ancora usato per DB

# Import per Flask e Threading
from flask import Flask
import threading

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

# Abilita il logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# --- Recupero del Token del Bot ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    logger.error("FATALE: La variabile d'ambiente TELEGRAM_BOT_TOKEN non è impostata.")
    # exit()

# --- Flask App per Health Check di Render ---
flask_app = Flask(__name__)

@flask_app.route('/') # Endpoint radice per health check
def health_check():
    """Risponde OK ai check di Render."""
    logger.debug("Health check endpoint chiamato.") # Log di debug (opzionale)
    return "OK", 200

# --- Costanti e Dati di Validazione ---
REGIONI_ITALIANE = [
    "Abruzzo", "Basilicata", "Calabria", "Campania", "Emilia-Romagna",
    "Friuli Venezia Giulia", "Lazio", "Liguria", "Lombardia", "Marche",
    "Molise", "Piemonte", "Puglia", "Sardegna", "Sicilia", "Toscana",
    "Trentino-Alto Adige", "Umbria", "Valle d'Aosta", "Veneto",
    "Provincia Autonoma Bolzano", "Provincia Autonoma Trento"
]
REGIONI_ITALIANE_LOWER = [r.lower() for r in REGIONI_ITALIANE]

TIPI_CARBURANTE_VALIDI = ["Benzina", "Diesel"]
TIPI_CARBURANTE_VALIDI_LOWER = [c.lower() for c in TIPI_CARBURANTE_VALIDI]

CSV_URL = "https://www.mimit.gov.it/images/stories/carburanti/MediaRegionaleStradale.csv"


# --- Funzioni Helper Database (Simulate per ora) ---

def get_prezzo_simulato(regione: str, carburante: str) -> tuple[float | None, str | None]:
    """
    Simula il recupero del prezzo. In futuro leggerà da Supabase.
    Restituisce (prezzo, data_aggiornamento_str) o (None, None).
    """
    logger.info(f"[SIMULATO] Recupero prezzo per {carburante} in {regione}")
    prezzo = None
    if carburante.lower() == "benzina":
        prezzo = 1.855 # Valore simulato
    elif carburante.lower() == "diesel":
        prezzo = 1.755 # Valore simulato

    if prezzo:
        data_oggi = datetime.now().strftime("%d/%m/%Y")
        return prezzo, data_oggi
    else:
        return None, None

# --- Definizione dei Gestori di Comandi/Messaggi Telegram ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Invia un messaggio di benvenuto."""
    user = update.effective_user
    welcome_message = (
        f"Ciao {user.mention_html()}!\n\n"
        "Sono il bot per i prezzi medi regionali dei carburanti.\n\n"
        "Per ottenere un prezzo, usa il comando:\n"
        "<code>/prezzo NomeRegione TipoCarburante</code>\n\n"
        "Esempi:\n"
        "<code>/prezzo Lombardia Benzina</code>\n"
        "<code>/prezzo Sicilia Diesel</code>\n"
        "<code>/prezzo Friuli Venezia Giulia Diesel</code>"
    )
    await update.message.reply_html(welcome_message, disable_web_page_preview=True)


async def prezzo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gestisce il comando /prezzo."""
    args = context.args
    logger.info(f"Comando /prezzo ricevuto con args: {args}")

    if len(args) < 2:
        await update.message.reply_text(
            "Formato comando errato. Usa: /prezzo NomeRegione TipoCarburante\n"
            "Esempio: <code>/prezzo Lombardia Benzina</code>",
            parse_mode='HTML'
        )
        return

    nome_regione_input = " ".join(args[:-1])
    tipo_carburante_input = args[-1]

    nome_regione_normalizzato = nome_regione_input.strip().title()
    tipo_carburante_normalizzato = tipo_carburante_input.strip().capitalize()

    logger.info(f"Parsing: Regione='{nome_regione_normalizzato}', Carburante='{tipo_carburante_normalizzato}'")

    # Validazione Regione
    regione_valida = False
    nome_regione_validato = ""
    if nome_regione_normalizzato.lower() in REGIONI_ITALIANE_LOWER:
         index = REGIONI_ITALIANE_LOWER.index(nome_regione_normalizzato.lower())
         nome_regione_validato = REGIONI_ITALIANE[index]
         regione_valida = True
    elif nome_regione_normalizzato.lower() == "emilia romagna":
         nome_regione_validato = "Emilia-Romagna"
         regione_valida = True
    elif nome_regione_normalizzato.lower() == "trentino alto adige":
         nome_regione_validato = "Trentino-Alto Adige"
         regione_valida = True

    if not regione_valida:
        logger.warning(f"Regione non valida: '{nome_regione_normalizzato}'")
        await update.message.reply_text(
             f"'{nome_regione_normalizzato}' non sembra essere una regione italiana valida. Controlla il nome e riprova."
        )
        return

    # Validazione Carburante
    carburante_valido = False
    tipo_carburante_validato = ""
    if tipo_carburante_normalizzato.lower() in TIPI_CARBURANTE_VALIDI_LOWER:
        index = TIPI_CARBURANTE_VALIDI_LOWER.index(tipo_carburante_normalizzato.lower())
        tipo_carburante_validato = TIPI_CARBURANTE_VALIDI[index]
        carburante_valido = True

    if not carburante_valido:
        logger.warning(f"Tipo carburante non valido: '{tipo_carburante_normalizzato}'")
        await update.message.reply_text(
            f"Tipo carburante non valido: '{tipo_carburante_normalizzato}'. Usa 'Benzina' o 'Diesel'."
        )
        return

    # Recupero Dati (Simulato per ora)
    logger.info(f"Recupero prezzo (simulato) per {tipo_carburante_validato} in {nome_regione_validato}")
    prezzo_medio, data_aggiornamento = get_prezzo_simulato(nome_regione_validato, tipo_carburante_validato)

    # Risposta all'Utente
    if prezzo_medio is not None and data_aggiornamento is not None:
        messaggio_risposta = (
            f"Prezzo medio <b>{tipo_carburante_validato}</b>\n"
            f"in <b>{nome_regione_validato}</b>\n"
            f"il <b>{data_aggiornamento}</b> (dato simulato):\n\n" # Aggiunto (dato simulato)
            f"<b>€ {prezzo_medio:.3f}</b>"
        )
        logger.info(f"Invio risposta: {messaggio_risposta}")
        await update.message.reply_html(messaggio_risposta)
    else:
        logger.error(f"Errore nel recupero dati simulati per {tipo_carburante_validato} in {nome_regione_validato}")
        await update.message.reply_text(
            f"Spiacente, non sono riuscito a recuperare il dato simulato per {tipo_carburante_validato} in {nome_regione_validato}."
        )


async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Risponde a comandi/messaggi sconosciuti."""
    await update.message.reply_text("Comando non riconosciuto. Usa /start per vedere le istruzioni.")


# --- Funzione Principale del Bot ---

def main() -> None:
    """Avvia il bot Telegram e il server Flask per health check."""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("Il bot non può avviarsi senza TELEGRAM_BOT_TOKEN.")
        return

    # --- Avvio Flask Server in un Thread Separato ---
    flask_port = int(os.environ.get('PORT', 8080)) # Render imposta PORT
    logger.info(f"Avvio del server Flask sulla porta {flask_port} per health check...")
    flask_thread = threading.Thread(
        target=lambda: flask_app.run(host='0.0.0.0', port=flask_port, debug=False, use_reloader=False),
        daemon=True
    )
    flask_thread.start()
    logger.info("Thread Flask avviato.")

    # --- Avvio Bot Telegram (dopo aver avviato Flask) ---
    logger.info("Creazione dell'istanza Application Telegram...")
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    logger.info("Application Telegram creata.")

    # Qui in futuro potremmo voler inizializzare la connessione al DB o fare altri setup
    # Per ora non serve inizializzare il DB Supabase da codice (tabella creata via SQL)

    # Registra i gestori Telegram
    application.add_handler(CommandHandler("start", start))
    logger.info("Handler per /start registrato.")
    application.add_handler(CommandHandler("prezzo", prezzo))
    logger.info("Handler per /prezzo registrato.")
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown))
    logger.info("Handler per messaggi di testo generici registrato.")
    application.add_handler(MessageHandler(filters.COMMAND, unknown))
    logger.info("Handler per comandi sconosciuti registrato.")

    # Avvia il polling del bot Telegram (blocca il thread principale)
    logger.info("Avvio del bot Telegram in modalità polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

    logger.info("Bot Telegram polling terminato.") # Questo log appare solo se il bot viene fermato

# Esegui main() se lo script è lanciato direttamente
if __name__ == "__main__":
    main()
