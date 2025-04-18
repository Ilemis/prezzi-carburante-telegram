import logging  # Importa la libreria per il logging
import os       # Importa la libreria per interagire con il sistema operativo
from datetime import datetime # Importa datetime per ottenere la data odierna (ci servirà dopo)

from telegram import Update  # Importa la classe Update da telegram
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters # Importa classi da telegram.ext

# Abilita il logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING) # Riduci verbosità logger http
logger = logging.getLogger(__name__)

# --- Recupero del Token del Bot ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    logger.error("FATALE: La variabile d'ambiente TELEGRAM_BOT_TOKEN non è impostata.")
    # Potremmo voler uscire qui in un caso reale: exit()

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
        "<code>/prezzo Sicilia Diesel</code>\n\n"
        # Rimuoviamo la nota "(Attualmente posso solo salutarti...)"
        # perché ora /prezzo fa qualcosa (anche se non cerca ancora il prezzo)
    )
    await update.message.reply_html(welcome_message, disable_web_page_preview=True)

# --- Definizione del Gestore per /prezzo ---
async def prezzo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gestisce il comando /prezzo NomeRegione TipoCarburante."""
    # context.args è una lista delle stringhe inserite dopo il comando /prezzo
    args = context.args

    logger.info(f"Comando /prezzo ricevuto con args: {args}") # Log per debugging

    # Controlla se il numero di argomenti è corretto (devono essere almeno 2)
    # Il nome della regione può contenere spazi, l'ultimo è il carburante.
    if len(args) < 2:
        await update.message.reply_text(
            "Formato comando errato. Usa: /prezzo NomeRegione TipoCarburante\n"
            "Esempio: <code>/prezzo Lombardia Benzina</code>",
            parse_mode='HTML' # Usiamo HTML per poter usare <code>
        )
        return # Esce dalla funzione se il formato è sbagliato

    # Ricostruisce il nome della regione (potrebbe contenere spazi)
    # Prende tutti gli argomenti tranne l'ultimo come potenziale nome regione
    nome_regione_input = " ".join(args[:-1])
    # Prende l'ultimo argomento come potenziale tipo carburante
    tipo_carburante_input = args[-1]

    # Normalizza l'input per facilitare i controlli successivi
    # .strip() toglie spazi bianchi iniziali/finali
    # .title() mette Maiuscola Ogni Iniziale Di Parola (utile per regioni tipo "Valle D'Aosta")
    nome_regione_normalizzato = nome_regione_input.strip().title()
    # .capitalize() mette solo la prima lettera maiuscola, il resto minuscolo (es. "Benzina", "Diesel")
    tipo_carburante_normalizzato = tipo_carburante_input.strip().capitalize()

    logger.info(f"Parsing: Regione='{nome_regione_normalizzato}', Carburante='{tipo_carburante_normalizzato}'")

    # --- VALIDAZIONE INPUT (Aggiungeremo dopo) ---
    # Qui dovremmo controllare se la regione è valida e se il carburante è "Benzina" o "Diesel"

    # --- RECUPERO DATI (Aggiungeremo dopo) ---
    # Qui interrogheremo lo storage (il nostro futuro DB SQLite)

    # --- RISPOSTA TEMPORANEA ---
    # Per ora, rispondiamo semplicemente confermando cosa abbiamo capito

    await update.message.reply_text(
        f"OK, hai chiesto il prezzo per:\n"
        f"Regione: <b>{nome_regione_normalizzato}</b>\n" # Usa grassetto per chiarezza
        f"Carburante: <b>{tipo_carburante_normalizzato}</b>\n\n"
        f"<i>(Logica di ricerca prezzo e data non ancora implementata)</i>", # Usa corsivo
        parse_mode='HTML' # Abilita l'uso di <b> e <i>
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

    # Registra i gestori (handlers) nell'applicazione.
    # L'ordine può essere importante se i filtri si sovrappongono
    application.add_handler(CommandHandler("start", start))
    logger.info("Handler per /start registrato.")
    application.add_handler(CommandHandler("prezzo", prezzo)) # Gestore per /prezzo
    logger.info("Handler per /prezzo registrato.")

    # Gestore per messaggi di testo che non sono comandi (deve venire DOPO i CommandHandler)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown))
    logger.info("Handler per messaggi di testo generici registrato.")

    # Gestore per comandi non riconosciuti (generico, cattura tutto ciò che inizia con /)
    # Mettendolo per ultimo, cattura solo i comandi non gestiti sopra.
    application.add_handler(MessageHandler(filters.COMMAND, unknown))
    logger.info("Handler per comandi sconosciuti registrato.")

    # Avvia il bot in modalità polling
    logger.info("Avvio del bot in modalità polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

# Esegui main() se lo script è lanciato direttamente
if __name__ == "__main__":
    main()
