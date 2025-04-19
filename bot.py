import asyncio # Assicurati che sia presente
import logging
import os
from datetime import datetime
import requests
import csv
from io import StringIO
import psycopg2
import threading
from flask import Flask, request, abort # Aggiunto request e abort per il trigger

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

# --- Configurazione Logging ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# --- Recupero del Token del Bot e Variabili d'Ambiente ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
# Recupero credenziali DB (saranno usate in get_db_connection)
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")

# Secret per il trigger di aggiornamento (DEVI impostarlo come var d'ambiente su Render!)
UPDATE_SECRET = os.getenv("UPDATE_SECRET", "imposta_un_secret_sicuro") # Default debole, sovrascrivi!

if not TELEGRAM_BOT_TOKEN:
    logger.critical("FATALE: La variabile d'ambiente TELEGRAM_BOT_TOKEN non è impostata.")
    # Potresti voler uscire qui se TELEGRAM_BOT_TOKEN è essenziale per avviare
    # exit(1)
if not all([DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD]):
     logger.warning("ATTENZIONE: Una o più variabili d'ambiente del database (DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD) non sono impostate.")
     # Il bot potrebbe avviarsi ma le funzioni DB falliranno.

# --- Costanti ---
# URL del file CSV dal MIMIT
CSV_URL = "https://www.mimit.gov.it/images/stories/carburanti/MediaRegionaleStradale.csv"
# Questo formato ha la data in prima riga e usa ';' come separatore
IS_MIMIT_FORMAT = False # Lo impostiamo a False per usare la logica di parsing corretta

# Lista REGIONI valide (basata sui nomi esatti nel CSV MIMIT)
# NOTA: "Trentino-Alto Adige/Südtirol" non sembra esserci nel file, ci sono Bolzano e Trento separate
REGIONI_VALIDATE = sorted([
    "Abruzzo", "Basilicata", "Bolzano", "Calabria", "Campania",
    "Emilia Romagna", "Friuli Venezia Giulia", "Lazio", "Liguria", "Lombardia",
    "Marche", "Molise", "Piemonte", "Puglia", "Sardegna", "Sicilia",
    "Toscana", "Trento", "Umbria", "Valle d'Aosta", "Veneto"
])

# --- Flask App per Health Check di Render e Trigger Aggiornamento ---
flask_app = Flask(__name__)

@flask_app.route('/') # Endpoint radice per health check
def health_check():
    """Risponde OK ai check di Render."""
    logger.debug("Health check endpoint '/' chiamato.")
    return "OK", 200

@flask_app.route('/trigger-update', methods=['POST']) # Endpoint per aggiornamento DB
def trigger_update_http():
    """
    Endpoint sicuro per triggerare l'aggiornamento del database.
    Richiede un parametro 'secret' nella query string.
    Esempio chiamata (da Render Cron Job):
    curl -X POST "https://TUA_APP_URL.onrender.com/trigger-update?secret=IL_TUO_SECRET"
    """
    logger.info("Chiamata ricevuta a /trigger-update")
    secret_ricevuto = request.args.get('secret')

    if not secret_ricevuto:
        logger.warning("Trigger update chiamato senza parametro 'secret'.")
        abort(400, description="Parametro 'secret' mancante.") # Bad Request

    if secret_ricevuto != UPDATE_SECRET:
        logger.warning("Trigger update chiamato con secret errato.")
        abort(403, description="Secret non valido.") # Forbidden

    logger.info("Secret valido, avvio aggiornamento database in background...")
    # Avviamo l'aggiornamento in un thread separato per non bloccare la richiesta HTTP
    update_thread = threading.Thread(target=update_database_wrapper)
    update_thread.start()

    return "Aggiornamento avviato in background.", 202 # Accepted

def update_database_wrapper():
    """ Chiamata a update_database con gestione inizio/fine log. """
    logger.info("Esecuzione di update_database() avviata dal trigger HTTP...")
    success = update_database()
    if success:
        logger.info("Esecuzione di update_database() completata con successo.")
    else:
        logger.error("Esecuzione di update_database() fallita.")

# --- Funzioni Database ---

def get_db_connection():
    """Crea e restituisce una connessione al database PostgreSQL."""
    conn = None # Inizializza a None
    try:
        if not all([DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD]):
             logger.error("Connessione DB fallita: variabili d'ambiente mancanti.")
             return None
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD
        )
        logger.info("Connessione al database Supabase riuscita.")
        return conn
    except psycopg2.OperationalError as e:
        logger.error(f"Errore di connessione al database: {e}")
        if conn: conn.close() # Assicura chiusura se l'errore avviene dopo la connessione parziale
        return None
    except Exception as e:
        logger.error(f"Errore generico durante la connessione al DB: {e}")
        if conn: conn.close()
        return None

def update_database():
    """Scarica il CSV, lo processa, aggiorna il DB e pulisce i dati vecchi."""
    logger.info(f"Tentativo di aggiornamento database da URL: {CSV_URL}")
    conn = None
    cur = None
    cur_delete = None # Inizializza il cursore per la delete
    success = False # Flag per indicare successo/fallimento

    try:
        response = requests.get(CSV_URL, timeout=30)
        response.raise_for_status()
        logger.info("CSV scaricato con successo.")

        # Usiamo StringIO per trattare la stringa del CSV come un file
        try:
            csv_text = response.content.decode('utf-8')
        except UnicodeDecodeError:
             logger.warning("Decodifica UTF-8 fallita, tentativo con ISO-8859-1 (Latin-1)")
             csv_text = response.content.decode('iso-8859-1')

        csv_data = StringIO(csv_text)

        conn = get_db_connection()
        if not conn:
            logger.error("Aggiornamento fallito: impossibile connettersi al DB.")
            return False

        cur = conn.cursor()
        data_aggiornamento = None
        righe_processate = 0
        righe_inserite = 0

        # --- INSERIMENTO DATI NUOVI ---
        prima_riga = csv_data.readline().strip()
        try:
            parti = prima_riga.split()
            if len(parti) < 2: raise ValueError("Formato prima riga non riconosciuto")
            data_str = parti[-1]
            data_aggiornamento = datetime.strptime(data_str, "%d-%m-%Y").date()
            logger.info(f"Data aggiornamento rilevata dal CSV: {data_aggiornamento}")
        except (IndexError, ValueError, TypeError) as e:
            logger.error(f"Impossibile estrarre la data dalla prima riga: '{prima_riga}'. Errore: {e}")
            return False # Errore fatale per questo aggiornamento

        csv_reader = csv.reader(csv_data, delimiter=';')
        try:
             header = next(csv_reader)
             logger.info(f"Intestazione CSV letta: {header}")
        except StopIteration:
             logger.error("Errore: il file CSV sembra vuoto dopo la prima riga.")
             return False

        for row in csv_reader:
            righe_processate += 1
            try:
                if len(row) < 4:
                    logger.warning(f"Riga {righe_processate+2} ignorata (troppo corta): {row}")
                    continue
                regione = row[0].strip()
                tipo_carburante = row[1].strip()
                prezzo_str = row[3].strip()
                if not regione or not tipo_carburante or not prezzo_str:
                    logger.warning(f"Riga {righe_processate+2} ignorata (dati mancanti): {row}")
                    continue
                try:
                   prezzo = float(prezzo_str.replace(",", "."))
                except ValueError:
                   logger.warning(f"Prezzo non valido '{prezzo_str}' per {regione}/{tipo_carburante} (Riga {righe_processate+2}). Ignorata: {row}")
                   continue
                if regione not in REGIONI_VALIDATE:
                     logger.warning(f"Regione '{regione}' letta dal CSV ma non presente nella lista REGIONI_VALIDATE (Riga {righe_processate+2}). Riga ignorata: {row}")
                     continue

                query = """
                    INSERT INTO prezzi_regionali (regione, tipo_carburante, prezzo_medio, data_aggiornamento)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (regione, tipo_carburante, data_aggiornamento) DO NOTHING;
                """
                cur.execute(query, (regione, tipo_carburante, prezzo, data_aggiornamento))
                if cur.rowcount > 0:
                    righe_inserite += 1

            except Exception as e:
                logger.error(f"Errore processando la riga {righe_processate+2}: {row}. Errore: {e}")
                conn.rollback() # Annulla transazione parziale

        # Commit degli inserimenti
        conn.commit()
        logger.info(f"Inserimento dati completato. Righe CSV lette (dopo intestazione): {righe_processate}, Righe nuove inserite: {righe_inserite}.")

        # --- PULIZIA DATI VECCHI ---
        try:
            giorni_da_mantenere = 30 # Mantieni gli ultimi 30 giorni
            logger.info(f"Avvio pulizia dati più vecchi di {giorni_da_mantenere} giorni...")
            cur_delete = conn.cursor() # Usa un nuovo cursore per la delete
            query_delete = """
                DELETE FROM prezzi_regionali
                WHERE data_aggiornamento < CURRENT_DATE - INTERVAL '%s days';
            """
            cur_delete.execute(query_delete, (giorni_da_mantenere,))
            righe_cancellate = cur_delete.rowcount
            conn.commit() # Commit della cancellazione
            logger.info(f"Pulizia completata. Righe vecchie cancellate: {righe_cancellate}.")
            cur_delete.close() # Chiudi il cursore della delete
            cur_delete = None # Resetta la variabile per il blocco finally
        except psycopg2.Error as e:
             logger.error(f"Errore Database durante la pulizia dei dati vecchi: {e}")
             if conn and not conn.closed: conn.rollback() # Annulla cancellazione in caso di errore
        except Exception as e:
             logger.error(f"Errore imprevisto durante la pulizia: {e}")
             if conn and not conn.closed: conn.rollback()

        success = True # L'aggiornamento è considerato riuscito anche se la pulizia fallisce

    except requests.exceptions.RequestException as e:
        logger.error(f"Errore durante il download del CSV: {e}")
    except psycopg2.Error as e:
        logger.error(f"Errore Database durante l'aggiornamento/inserimento: {e}")
        if conn: conn.rollback() # Annulla transazione
    except UnicodeDecodeError as e:
        logger.error(f"Errore di decodifica del file CSV: {e}")
    except Exception as e:
        logger.error(f"Errore imprevisto durante l'aggiornamento del database: {e}")
        if conn and not conn.closed: conn.rollback()
    finally:
        # Assicurati di chiudere tutti i cursori e la connessione
        if cur and not cur.closed:
            cur.close()
        if cur_delete and not cur_delete.closed: # Chiudi anche cur_delete se esiste
            cur_delete.close()
        if conn and not conn.closed:
             conn.close()
             logger.info("Connessione al database chiusa (dopo aggiornamento e pulizia).")
    return success


def get_prezzi_regione_dal_db(nome_regione: str) -> str:
    """Recupera i prezzi più recenti per una regione dal DB e formatta la risposta."""
    logger.info(f"Richiesta prezzi per regione: {nome_regione}")
    conn = None
    cur = None

    try:
        conn = get_db_connection()
        if not conn:
            return "❌ Errore: Impossibile connettersi al database al momento."

        cur = conn.cursor()

        # Trova la data più recente per la regione specificata
        cur.execute("""
            SELECT MAX(data_aggiornamento)
            FROM prezzi_regionali
            WHERE regione = %s;
        """, (nome_regione,))
        result = cur.fetchone()

        if not result or not result[0]:
            logger.warning(f"Nessun dato trovato nel DB per la regione: {nome_regione}")
            return f"❓ Mi dispiace, non ho ancora dati disponibili per la regione '{nome_regione}'."

        data_recente = result[0]
        data_formattata = data_recente.strftime('%d/%m/%Y')

        # Recupera tutti i prezzi per quella regione e quella data
        cur.execute("""
            SELECT tipo_carburante, prezzo_medio
            FROM prezzi_regionali
            WHERE regione = %s AND data_aggiornamento = %s
            ORDER BY CASE tipo_carburante  -- Ordine personalizzato
                     WHEN 'Benzina' THEN 1
                     WHEN 'Gasolio' THEN 2
                     WHEN 'GPL'     THEN 3
                     WHEN 'Metano'  THEN 4
                     ELSE 5
                   END;
        """, (nome_regione, data_recente))
        prezzi = cur.fetchall()

        if not prezzi:
             logger.error(f"DB Inconsistency: Data trovata ({data_recente}) ma nessun prezzo per regione: {nome_regione}")
             return f"⚠️ Errore interno nel recuperare i prezzi per '{nome_regione}' del {data_formattata}."

        # Formattazione dell'output usando HTML
        messaggio = f"⛽ <b>Prezzi Medi - {nome_regione}</b> ({data_formattata}) ⛽\n"
        messaggio += "-------------------------------------------------\n"

        prezzi_dict = {'Benzina': 'N.D.', 'Gasolio': 'N.D.', 'GPL': 'N.D.', 'Metano': 'N.D.'}
        for tipo, prezzo in prezzi:
            if tipo in prezzi_dict:
               prezzi_dict[tipo] = f"€ {prezzo:.3f}" # Formatta a 3 decimali

        messaggio += f"🟢 <b>Benzina:</b> {prezzi_dict['Benzina']}\n"
        messaggio += f"⚫ <b>Gasolio:</b> {prezzi_dict['Gasolio']}\n"
        messaggio += f"🔵 <b>GPL:</b>      {prezzi_dict['GPL']}\n"
        messaggio += f"⚪ <b>Metano:</b>   {prezzi_dict['Metano']}\n"
        messaggio += "-------------------------------------------------"

        logger.info(f"Prezzi trovati e formattati per {nome_regione}: {prezzi_dict}")
        return messaggio

    except psycopg2.Error as e:
        logger.error(f"Errore Database durante la lettura per {nome_regione}: {e}")
        return f"❌ Si è verificato un errore nel recuperare i dati per {nome_regione}. Riprova più tardi."
    except Exception as e:
         logger.error(f"Errore imprevisto durante la lettura per {nome_regione}: {e}")
         return "❌ Si è verificato un errore generico. Riprova più tardi."
    finally:
        if cur: cur.close()
        if conn and not conn.closed: conn.close()
        # logger.debug(f"Connessione DB chiusa per richiesta {nome_regione}.")

# --- Definizione dei Gestori di Comandi/Messaggi Telegram ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Invia un messaggio di benvenuto aggiornato."""
    user = update.effective_user
    elenco_regioni = ", ".join(f"<code>/{r}</code>" for r in REGIONI_VALIDATE)
    welcome_message = (
        f"Ciao {user.mention_html()}!\n\n"
        "Sono il bot per i prezzi medi regionali dei carburanti (Benzina, Gasolio, GPL, Metano).\n\n"
        "Per ottenere i prezzi di una regione, invia il comando corrispondente.\n\n"
        "<b>Regioni disponibili:</b>\n"
        f"{elenco_regioni}\n\n"
        "Esempio: invia <code>/Lombardia</code> per vedere i prezzi in Lombardia."
    )
    await update.message.reply_html(welcome_message, disable_web_page_preview=True)


async def regione_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gestisce i comandi /Regione per richiedere i prezzi."""
    if not update.message or not update.message.text:
        return # Ignora messaggi senza testo

    command_text = update.message.text.strip()
    if not command_text.startswith('/'):
         logger.warning(f"region_command chiamato con testo non-comando: {command_text}")
         return # Dovrebbe essere gestito da unknown_command, ma per sicurezza

    # Estrai il nome della regione (rimuovi '/' iniziale) e normalizza
    nome_regione_input = command_text[1:].strip()

    # Normalizzazione più robusta per matchare REGIONI_VALIDATE
    nome_regione_normalizzato = ' '.join(word.capitalize() for word in nome_regione_input.replace("'", "' ").split())
    nome_regione_normalizzato = nome_regione_normalizzato.replace("' ", "'")
    if "Valle D'aosta" in nome_regione_normalizzato: nome_regione_normalizzato = "Valle d'Aosta"
    if "Emilia Romagna" in nome_regione_normalizzato: nome_regione_normalizzato = "Emilia Romagna"
    if "Friuli Venezia Giulia" in nome_regione_normalizzato: nome_regione_normalizzato = "Friuli Venezia Giulia"

    logger.info(f"Comando ricevuto: {command_text}. Regione estratta/normalizzata: {nome_regione_normalizzato}")

    # Controlla se la regione normalizzata è nella lista delle regioni valide
    if nome_regione_normalizzato in REGIONI_VALIDATE:
        # Mostra "Sto cercando..."
        thinking_message = await update.message.reply_text("🔍 Sto cercando i dati...", disable_notification=True)

        # Esegui la funzione DB in modo sicuro per asyncio
        messaggio_prezzi = await asyncio.to_thread(
            get_prezzi_regione_dal_db, nome_regione_normalizzato
        )

        # Modifica il messaggio "Sto cercando..." con la risposta finale
        try:
            await context.bot.edit_message_text(
                 chat_id=update.effective_chat.id,
                 message_id=thinking_message.message_id,
                 text=messaggio_prezzi,
                 parse_mode='HTML' # Usa HTML per coerenza
            )
            logger.info(f"Risposta inviata (modificando) per {nome_regione_normalizzato}")
        except Exception as e:
             logger.error(f"Errore nel modificare il messaggio per {nome_regione_normalizzato}: {e}")
             # Fallback: invia come nuovo messaggio se modifica fallisce
             await update.message.reply_html(messaggio_prezzi)
    else:
        # Se il comando inizia con / ma non è una regione valida riconosciuta
        logger.warning(f"Comando regione non valido ricevuto: {nome_regione_input} (Normalizzato: {nome_regione_normalizzato})")
        await update.message.reply_text(
            f"⚠️ Non ho riconosciuto '<code>{nome_regione_input}</code>' come una regione valida.\n"
            f"Assicurati di usare il nome corretto. Digita /start per vedere l'elenco.",
            parse_mode='HTML'
        )

async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Risponde a comandi Telegram non gestiti esplicitamente."""
    await update.message.reply_text("Comando non riconosciuto. Digita /start per vedere i comandi disponibili.")

async def unknown_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Risponde a messaggi di testo che non sono comandi."""
    await update.message.reply_text("Non capisco questo messaggio. Digita /start per vedere cosa posso fare.")


# --- Funzione Principale del Bot ---

def main() -> None:
    """Avvia il bot Telegram e il server Flask."""

    # Verifica iniziale variabili essenziali
    if not TELEGRAM_BOT_TOKEN:
        logger.critical("Il bot non può avviarsi senza TELEGRAM_BOT_TOKEN.")
        return
    if not all([DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD]):
        logger.warning("Avvio con variabili DB mancanti. Le funzioni database non opereranno.")

    # --- Avvio Flask Server in un Thread Separato ---
    flask_port = int(os.environ.get('PORT', 8080))
    logger.info(f"Avvio del server Flask su host 0.0.0.0 porta {flask_port}...")
    flask_thread = threading.Thread(
        target=lambda: flask_app.run(host='0.0.0.0', port=flask_port, debug=False, use_reloader=False),
        daemon=True # Il thread termina quando il main termina
    )
    flask_thread.start()
    logger.info("Thread Flask avviato.")

    # --- Avvio Bot Telegram ---
    logger.info("Creazione dell'istanza Application Telegram...")
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    logger.info("Application Telegram creata.")

    # Registra i gestori Telegram
    application.add_handler(CommandHandler("start", start_command))
    logger.info("Handler per /start registrato.")

    # Gestore per i comandi /Regione (cattura tutti i comandi)
    application.add_handler(MessageHandler(filters.COMMAND & filters.ChatType.PRIVATE, regione_command))
    logger.info("Handler principale per /Regione (filters.COMMAND) registrato.")

    # Gestore per messaggi di testo non-comando
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, unknown_message))
    logger.info("Handler per messaggi di testo generici registrato.")


    # Avvia il polling del bot Telegram (blocca il thread principale)
    logger.info("Avvio del bot Telegram in modalità polling...")
    try:
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except Exception as e:
        logger.critical(f"Errore critico durante l'esecuzione del bot: {e}", exc_info=True)
    finally:
        logger.info("Bot Telegram polling terminato.")

# Esegui main() se lo script è lanciato direttamente
if __name__ == "__main__":
    main()
