import logging  # Importa la libreria per il logging (registrare messaggi di stato/errore)
import os       # Importa la libreria per interagire con il sistema operativo (per leggere le variabili d'ambiente)
from telegram import Update  # Importa la classe Update, che rappresenta un aggiornamento ricevuto da Telegram (es. un messaggio)
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters  # Importa le classi necessarie dalla libreria python-telegram-bot

# Abilita il logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",  # Formato dei messaggi di log
    level=logging.INFO  # Livello minimo dei messaggi da registrare (INFO, WARNING, ERROR, CRITICAL)
)
# Imposta un livello di logging più alto per 'httpx' per evitare di registrare tutte le richieste GET/POST interne della libreria
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)  # Crea un oggetto logger specifico per questo modulo

# --- Recupero del Token del Bot ---
# Recupera il token del bot dalla variabile d'ambiente 'TELEGRAM_BOT_TOKEN'
# !!!!! IMPORTANTE: Devi impostare TELEGRAM_BOT_TOKEN nelle Variabili d'Ambiente di Render !!!!!
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Controlla se il token è stato effettivamente trovato
if not TELEGRAM_BOT_TOKEN:
    logger.error("FATALE: La variabile d'ambiente TELEGRAM_BOT_TOKEN non è impostata.")
    # In uno scenario reale, qui potresti voler fermare l'esecuzione.
    # Per ora, registriamo solo l'errore e lasciamo continuare per vedere se Render lo avvia.
    # exit() # Decommenta questa linea per forzare l'uscita se il token manca


# --- Definizione dei Gestori di Comandi/Messaggi ---

# Definisce la funzione che gestirà il comando /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Invia un messaggio di benvenuto quando viene eseguito il comando /start."""
    user = update.effective_user  # Ottiene le informazioni sull'utente che ha inviato il comando
    # Compone il messaggio di benvenuto usando formattazione HTML per il nome utente
    welcome_message = (
        f"Ciao {user.mention_html()}!\n\n"
        "Sono il bot per i prezzi medi regionali dei carburanti.\n\n"
        "Per ottenere un prezzo, usa il comando:\n"
        "<code>/prezzo NomeRegione TipoCarburante</code>\n\n"
        "Esempi:\n"
        "<code>/prezzo Lombardia Benzina</code>\n"
        "<code>/prezzo Sicilia Diesel</code>\n\n"
        "(Attualmente posso solo salutarti, la funzione /prezzo è in sviluppo!)"
    )
    # Invia il messaggio di benvenuto come risposta al messaggio dell'utente
    # reply_html permette di usare tag HTML semplici come <b>, <i>, <code>, <a href="...">
    await update.message.reply_html(welcome_message, disable_web_page_preview=True) # disable_web_page_preview evita anteprime se ci fossero link

# Definisce una funzione per gestire comandi sconosciuti o testo semplice non previsto
async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Risponde a comandi non riconosciuti o a messaggi di testo generici."""
    await update.message.reply_text("Comando non riconosciuto. Usa /start per vedere le istruzioni.")


# --- Funzione Principale del Bot ---

def main() -> None:
    """Avvia il bot."""
    # Controlla di nuovo se il token è disponibile prima di tentare l'avvio
    if not TELEGRAM_BOT_TOKEN:
        logger.error("Il bot non può avviarsi senza TELEGRAM_BOT_TOKEN.")
        return  # Esce dalla funzione main se il token manca

    # Crea l'oggetto 'Application' che gestisce tutto il bot.
    # È necessario passare il token del bot qui.
    logger.info("Creazione dell'istanza Application...")
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    logger.info("Application creata.")

    # Registra i gestori (handlers) nell'applicazione.
    # Quando arriva un comando /start, verrà chiamata la funzione 'start'.
    application.add_handler(CommandHandler("start", start))
    logger.info("Handler per /start registrato.")

    # Aggiungi un gestore per qualsiasi messaggio di testo che NON sia un comando.
    # Questo viene dopo /start, quindi se l'utente scrive /start, viene eseguito 'start'.
    # Se scrive qualcos'altro (che non è un comando che gestiremo), viene eseguito 'unknown'.
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown))
    logger.info("Handler per messaggi di testo generici registrato.")

    # Opzionale: Aggiungi un gestore per qualsiasi comando non gestito esplicitamente sopra.
    # Questo cattura comandi come /help o /qualcosaacaso se non li abbiamo definiti.
    application.add_handler(MessageHandler(filters.COMMAND, unknown))
    logger.info("Handler per comandi sconosciuti registrato.")

    # Avvia il bot. Il bot resterà in esecuzione e chiederà aggiornamenti a Telegram (polling).
    logger.info("Avvio del bot in modalità polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES) # Specifica che vogliamo ricevere tutti i tipi di aggiornamenti

# Questo blocco assicura che la funzione main() venga eseguita solo quando lo script viene lanciato direttamente
if __name__ == "__main__":
    main()
