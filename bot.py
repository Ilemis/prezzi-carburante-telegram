import logging
import os
from datetime import datetime
import requests # Importa requests per scaricare il CSV (lo useremo dopo)
import csv      # Importa il modulo csv per leggere i dati (lo useremo dopo)
from io import StringIO # Importa StringIO per leggere stringhe come file (lo useremo dopo)

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

# --- Costanti e Dati di Validazione ---
# Lista (semplificata) delle regioni italiane per la validazione
# Nota: Andrebbe migliorata per gestire accenti, apostrofi, bilinguismo, etc.
REGIONI_ITALIANE = [
    "Abruzzo", "Basilicata", "Calabria", "Campania", "Emilia-Romagna",
    "Friuli Venezia Giulia", "Lazio", "Liguria", "Lombardia", "Marche",
    "Molise", "Piemonte", "Puglia", "Sardegna", "Sicilia", "Toscana",
    "Trentino-Alto Adige", "Umbria", "Valle d'Aosta", "Veneto",
    # Consideriamo anche le province autonome come 'regioni' per il file MIMIT
    "Provincia Autonoma Bolzano", "Provincia Autonoma Trento"
]
# Converti in minuscolo per confronto case-insensitive più semplice
REGIONI_ITALIANE_LOWER = [r.lower() for r in REGIONI_ITALIANE]

TIPI_CARBURANTE_VALIDI = ["Benzina", "Diesel"]
TIPI_CARBURANTE_VALIDI_LOWER = [c.lower() for c in TIPI_CARBURANTE_VALIDI]

# URL del file CSV (lo useremo più avanti)
CSV_URL = "https://www.mimit.gov.it/images/stories/carburanti/MediaRegionaleStradale.csv"

# --- Funzioni Helper (per ora simulate) ---

def get_prezzo_simulato(regione: str, carburante: str) -> tuple[float | None, str | None]:
    """
    Simula il recupero del prezzo.
    In futuro, questa funzione leggerà dal DB SQLite.
    Restituisce una tupla: (prezzo, data_aggiornamento_str) o (None, None) se non trovato.
    """
    logger.info(f"Simulazione recupero prezzo per {carburante} in {regione}")
    # Logica simulata: restituisci un prezzo fisso se l'input è valido
    # (la validazione vera è fatta prima di chiamare questa funzione)
    if carburante.lower() == "benzina":
        prezzo = 1.85
    elif carburante.lower() == "diesel":
        prezzo = 1.75
    else:
        prezzo = None # Non dovrebbe succedere se validato prima

    if prezzo:
        # Restituisce il prezzo simulato e la data di oggi come stringa
        data_oggi = datetime.now().strftime("%d/%m/%Y")
        return prezzo, data_oggi
    else:
        return None, None

# --- Definizione dei Gestori di Comandi/Messaggi ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Invia un messaggio di benvenuto quando viene eseguito il comando /start."""
    user = update.effective_user
    welcome_message = (
        f"Ciao {user.mention_html()}!\n\n"
        "Sono il bot per i prezzi medi regionali dei carburanti.\n\n"
        "Per ottenere un prezzo, usa il comando:\n"
        "<code>/prezzo NomeRegione TipoCarburante</code>\n\n"
        "Esempi:\n"
        "<code>/prezzo Lombardia Benzina</code>\n"
        "<code>/prezzo Sicilia Diesel</code>\n"
        "<code>/prezzo Friuli Venezia Giulia Diesel</code>" # Esempio con spazi
    )
    await update.message.reply_html(welcome_message, disable_web_page_preview=True)


async def prezzo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gestisce il comando /prezzo NomeRegione TipoCarburante."""
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

    # Normalizzazione
    nome_regione_normalizzato = nome_regione_input.strip().title()
    tipo_carburante_normalizzato = tipo_carburante_input.strip().capitalize()

    logger.info(f"Parsing: Regione='{nome_regione_normalizzato}', Carburante='{tipo_carburante_normalizzato}'")

    # --- VALIDAZIONE INPUT ---
    regione_valida = False
    # Confronto case-insensitive (ignora maiuscole/minuscole)
    if nome_regione_normalizzato.lower() in REGIONI_ITALIANE_LOWER:
         # Se troviamo corrispondenza, usiamo il nome corretto dalla nostra lista
         # per consistenza (es. utente scrive "valle d'aosta", noi usiamo "Valle d'Aosta")
         index = REGIONI_ITALIANE_LOWER.index(nome_regione_normalizzato.lower())
         nome_regione_validato = REGIONI_ITALIANE[index]
         regione_valida = True
         logger.info(f"Regione '{nome_regione_normalizzato}' validata come '{nome_regione_validato}'.")
    else:
        # Tentativo extra per nomi comuni errati (esempio)
        if nome_regione_normalizzato.lower() == "emilia romagna":
             nome_regione_validato = "Emilia-Romagna"
             regione_valida = True
        elif nome_regione_normalizzato.lower() == "trentino alto adige":
             nome_regione_validato = "Trentino-Alto Adige"
             regione_valida = True
        # Aggiungere altre mappature se necessario...

    if not regione_valida:
        logger.warning(f"Regione non valida: '{nome_regione_normalizzato}'")
        await update.message.reply_text(
             f"'{nome_regione_normalizzato}' non sembra essere una regione italiana valida. Controlla il nome e riprova."
        )
        return

    carburante_valido = False
    if tipo_carburante_normalizzato.lower() in TIPI_CARBURANTE_VALIDI_LOWER:
        # Usa il nome corretto dalla nostra lista ("Benzina" o "Diesel")
        index = TIPI_CARBURANTE_VALIDI_LOWER.index(tipo_carburante_normalizzato.lower())
        tipo_carburante_validato = TIPI_CARBURANTE_VALIDI[index]
        carburante_valido = True
        logger.info(f"Carburante '{tipo_carburante_normalizzato}' validato come '{tipo_carburante_validato}'.")

    if not carburante_valido:
        logger.warning(f"Tipo carburante non valido: '{tipo_carburante_normalizzato}'")
        await update.message.reply_text(
            f"Tipo carburante non valido: '{tipo_carburante_normalizzato}'. Usa 'Benzina' o 'Diesel'."
        )
        return

    # --- RECUPERO DATI (Simulato) ---
    logger.info(f"Recupero prezzo per {tipo_carburante_validato} in {nome_regione_validato}")
    prezzo_medio, data_aggiornamento = get_prezzo_simulato(nome_regione_validato, tipo_carburante_validato)

    # --- RISPOSTA ALL'UTENTE ---
    if prezzo_medio is not None and data_aggiornamento is not None:
        messaggio_risposta = (
            f"Prezzo medio <b>{tipo_carburante_validato}</b>\n"
            f"in <b>{nome_regione_validato}</b>\n"
            f"il <b>{data_aggiornamento}</b>:\n\n"
            f"<b>€ {prezzo_medio:.3f}</b>" # Formatta a 3 decimali come nel file MIMIT
        )
        logger.info(f"Invio risposta: {messaggio_risposta}")
        await update.message.reply_html(messaggio_risposta)
    else:
        # Questo non dovrebbe accadere con la simulazione, ma serve per il futuro
        logger.error(f"Errore nel recupero dati simulati per {tipo_carburante_validato} in {nome_regione_validato}")
        await update.message.reply_text(
            f"Spiacente, non sono riuscito a recuperare il dato per {tipo_carburante_validato} in {nome_regione_validato}."
        )


async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Risponde a comandi non riconosciuti o a messaggi di testo generici."""
    await update.message.reply_text("Comando non riconosciuto. Usa /start per vedere le istruzioni.")


# --- Funzione Principale del Bot ---

def main() -> None:
    """Avvia il bot."""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("Il bot non può avviarsi senza TELEGRAM_BOT_TOKEN.")
        return

    logger.info("Creazione dell'istanza Application...")
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    logger.info("Application creata.")

    # Registra i gestori
    application.add_handler(CommandHandler("start", start))
    logger.info("Handler per /start registrato.")
    application.add_handler(CommandHandler("prezzo", prezzo))
    logger.info("Handler per /prezzo registrato.")
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown))
    logger.info("Handler per messaggi di testo generici registrato.")
    application.add_handler(MessageHandler(filters.COMMAND, unknown))
    logger.info("Handler per comandi sconosciuti registrato.")

    # Avvia il bot
    logger.info("Avvio del bot in modalità polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
