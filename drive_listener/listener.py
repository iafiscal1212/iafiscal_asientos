import time
import os
import logging
from datetime import datetime, timezone

from sqlalchemy import create_engine, Column, String, DateTime, Boolean
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base

from drive_listener.utils import get_drive_service, list_files_in_folder
from config.settings import current_config
from ocr_processor.main import process_document_from_drive
from reglas_clasificacion.main import classify_text_content, ClassifiedTransaction
from generador_asientos.main import generate_asiento, AsientoContable
from sheet_writer.main import write_asiento_to_sheet # Import the sheet writer

# Setup logging
# Configure logging more robustly, perhaps in a central place or app factory if Flask app grows
log_level_enum = getattr(logging, current_config.LOG_LEVEL.upper(), logging.INFO)
logging.basicConfig(level=log_level_enum,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Database setup for tracking processed files
DATABASE_URL = current_config.DATABASE_URL
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class ProcessedFile(Base):
    __tablename__ = "processed_files"

    id = Column(String, primary_key=True, index=True) # Google Drive File ID
    name = Column(String)
    mime_type = Column(String)
    processed_at = Column(DateTime, default=datetime.now(timezone.utc))
    status = Column(String, default="pending") # e.g., pending, ocr_complete, classified, sheet_written, error
    error_message = Column(String, nullable=True)
    last_modified_drive = Column(DateTime) # To detect if file was modified on drive after last processing

Base.metadata.create_all(bind=engine) # Create table if it doesn't exist

def is_file_already_processed(db_session, file_id: str, file_modified_time_str: str):
    """
    Checks if a file has already been processed and if it has been modified since.
    `file_modified_time_str` is the 'modifiedTime' from Google Drive API (RFC 3339 format).
    """
    file_modified_time_drive = datetime.fromisoformat(file_modified_time_str.replace('Z', '+00:00'))

    processed_file = db_session.query(ProcessedFile).filter(ProcessedFile.id == file_id).first()
    if processed_file:
        # If file exists in DB, check if the Drive version is newer
        if processed_file.last_modified_drive and file_modified_time_drive > processed_file.last_modified_drive:
            logger.info(f"File {file_id} ({processed_file.name}) was modified on Drive since last processing. Marking for reprocessing.")
            # Optionally, update status or clear previous error before reprocessing
            processed_file.status = "pending_reprocessing"
            processed_file.last_modified_drive = file_modified_time_drive
            db_session.commit()
            return False # Needs reprocessing

        logger.info(f"File {file_id} ({processed_file.name}) found in database with status '{processed_file.status}'. Skipping unless status indicates reprocessing.")
        # Consider if certain statuses should allow reprocessing (e.g., 'error')
        if processed_file.status not in ["error", "pending_reprocessing"]: # Add other statuses that might warrant a re-check
             return True # Already processed and not modified, or in a final state
        else: # e.g. if it was an error, allow reprocessing
            logger.info(f"File {file_id} had status '{processed_file.status}', allowing re-attempt.")
            return False # Allow reprocessing for error states or specific pending states.
    return False # Not found in DB, so not processed


def mark_file_as_processed(db_session, file_id: str, file_name: str, mime_type: str, modified_time_str: str, status: str = "processing_started", error_msg: str = None):
    """Marks a file as processed or updates its status in the database."""
    modified_time_drive = datetime.fromisoformat(modified_time_str.replace('Z', '+00:00'))

    existing_file = db_session.query(ProcessedFile).filter(ProcessedFile.id == file_id).first()
    if existing_file:
        existing_file.status = status
        existing_file.processed_at = datetime.now(timezone.utc)
        existing_file.last_modified_drive = modified_time_drive
        if error_msg:
            existing_file.error_message = error_msg
        else: # Clear previous error if current status is not error
            existing_file.error_message = None
    else:
        new_file = ProcessedFile(
            id=file_id,
            name=file_name,
            mime_type=mime_type,
            status=status,
            error_message=error_msg,
            last_modified_drive=modified_time_drive
        )
        db_session.add(new_file)
    db_session.commit()

def check_for_new_documents():
    """
    Checks the specified Google Drive folder for new documents
    that match the allowed MIME types and haven't been processed yet.
    """
    logger.info("Checking for new documents in Google Drive...")
    drive_service = None
    try:
        drive_service = get_drive_service()
    except FileNotFoundError as e:
        logger.error(f"Failed to initialize Drive service: {e}. Ensure credentials are set up.")
        return [] # Return empty list or handle error as appropriate
    except Exception as e:
        logger.error(f"An unexpected error occurred while getting Drive service: {e}")
        return []

    if not drive_service:
        logger.error("Drive service could not be initialized. Skipping check.")
        return []

    folder_id = current_config.DRIVE_FOLDER_ID
    if not folder_id:
        logger.error("DRIVE_FOLDER_ID is not configured. Cannot scan for files.")
        return []

    allowed_mimetypes = current_config.ALLOWED_MIMETYPES

    try:
        drive_files = list_files_in_folder(drive_service, folder_id)
        if drive_files is None:
            logger.error("Failed to list files from Google Drive.")
            return []
    except Exception as e:
        logger.error(f"Error listing files from Google Drive: {e}")
        return []

    new_files_to_process = []
    db_session = SessionLocal()
    try:
        for item in drive_files:
            file_id = item['id']
            file_name = item['name']
            mime_type = item['mimeType']
            modified_time = item['modifiedTime'] # e.g., '2023-10-26T10:00:00.000Z'

            if mime_type not in allowed_mimetypes:
                logger.debug(f"Skipping file '{file_name}' (ID: {file_id}) with unsupported MIME type: {mime_type}")
                continue

            if not is_file_already_processed(db_session, file_id, modified_time):
                logger.info(f"New/modified file detected: '{file_name}' (ID: {file_id}, Type: {mime_type})")
                new_files_to_process.append(item)
                # Mark as 'pending' or 'queued' to avoid picking up in parallel by another worker (if scaled)
                # For a single listener, marking later after successful processing start is okay.
                # mark_file_as_processed(db_session, file_id, file_name, mime_type, modified_time, status="queued")
            else:
                logger.debug(f"File '{file_name}' (ID: {file_id}) already processed and unchanged. Skipping.")
    finally:
        db_session.close()

    return new_files_to_process


def run_listener():
    """
    Main loop for the Drive listener. Periodically checks for new files
    and triggers their processing.
    """
    logger.info("Google Drive Listener started.")
    logger.info(f"Monitoring folder ID: {current_config.DRIVE_FOLDER_ID}")
    logger.info(f"Polling interval: {current_config.POLL_INTERVAL_SECONDS} seconds.")

    if not current_config.DRIVE_FOLDER_ID:
        logger.error("DRIVE_FOLDER_ID is not set. Listener cannot start.")
        return

    while True:
        try:
            new_files = check_for_new_documents()
            if new_files:
                logger.info(f"Found {len(new_files)} new/modified document(s) to process.")
                for file_data in new_files:
                    logger.info(f"Processing document: {file_data['name']} (ID: {file_data['id']})")
                    db = SessionLocal()
                    try:
                        # Mark as 'ocr_pending' or 'processing_started'
                        mark_file_as_processed(db, file_data['id'], file_data['name'], file_data['mimeType'], file_data['modifiedTime'], status="ocr_initiated")

                        # Call OCR Processor
                        extracted_text_content = None
                        ocr_error = None
                        try:
                            # Pass the existing drive_service to avoid re-authentication if possible (though process_document_from_drive can create its own)
                            # drive_service might need to be refreshed if it's been idle for too long.
                            # get_drive_service() handles credential loading.
                            current_drive_service = get_drive_service() # Ensure fresh service or handle token expiry if it was long-lived
                            extracted_text_content = process_document_from_drive(
                                file_id=file_data['id'],
                                file_name=file_data['name'],
                                mime_type=file_data['mimeType'],
                                drive_service=current_drive_service
                            )
                            if extracted_text_content is not None: # Could be empty string if file is blank but processed ok
                                logger.info(f"OCR processing successful for {file_data['name']}. Extracted content length: {len(extracted_text_content)}")
                                # Update status to ocr_completed before attempting classification
                                mark_file_as_processed(db, file_data['id'], file_data['name'], file_data['mimeType'], file_data['modifiedTime'], status="ocr_completed")

                                # Now, attempt to classify the extracted text
                                logger.info(f"Attempting classification for {file_data['name']}...")
                                classified_transaction = classify_text_content(extracted_text_content)

                                if classified_transaction:
                                    logger.info(f"Classification successful for {file_data['name']}: {classified_transaction.tipo_operacion} - {classified_transaction.account}")
                                    # Store classification details or update status
                                    # For now, just update status to 'classified'.
                                    # In a real scenario, you might store matched_rule details or key classification results in the DB.
                                    # e.g. ProcessedFile could have columns for 'account', 'iva_type', etc.
                                    mark_file_as_processed(db, file_data['id'], file_data['name'], file_data['mimeType'], file_data['modifiedTime'], status="classification_completed")

                                    # Attempt to generate the accounting entry (asiento)
                                    logger.info(f"Attempting to generate asiento for {file_data['name']}...")
                                    asiento_contable = generate_asiento(
                                        classified_transaction,
                                        original_document_id=file_data['id'],
                                        document_link=file_data.get('webViewLink') # Pass Drive link if available
                                    )

                                    if asiento_contable:
                                        if asiento_contable.needs_manual_review:
                                            logger.warning(f"Asiento generated for {file_data['name']} but requires manual review: {asiento_contable.review_reason}")
                                            mark_file_as_processed(db, file_data['id'], file_data['name'], file_data['mimeType'], file_data['modifiedTime'], status="needs_manual_review_asiento", error_msg=asiento_contable.review_reason)
                                        else:
                                            logger.info(f"Asiento successfully generated for {file_data['name']}.")
                                            mark_file_as_processed(db, file_data['id'], file_data['name'], file_data['mimeType'], file_data['modifiedTime'], status="asiento_generated")

                                        # Write the asiento to Google Sheets
                                        logger.info(f"Attempting to write asiento for {file_data['name']} to Google Sheets...")
                                        sheet_write_success = write_asiento_to_sheet(asiento_contable)

                                        if sheet_write_success:
                                            logger.info(f"Asiento for {file_data['name']} successfully written to Google Sheets.")
                                            mark_file_as_processed(db, file_data['id'], file_data['name'], file_data['mimeType'], file_data['modifiedTime'], status="completed_sheet_written")

                                            # TODO: The export to Contasol CSV is usually a batch operation (e.g., end of month).
                                            # It's not typically triggered per-document processed by the listener.
                                            # The current plan has "Implement the exportador_contasol module" which is done.
                                            # Triggering export from here would mean one CSV per document, which is not standard.
                                            # The exportador_contasol.main.export_data_to_contasol_csv function expects
                                            # `cliente` and `mes_anio` to generate a consolidated CSV.
                                            #
                                            # For now, the listener will mark as "completed_sheet_written".
                                            # A separate process or API endpoint should trigger the batch export.
                                            # If an immediate export per document was intended by the plan (unlikely for Contasol),
                                            # then this is where it would be called, but it needs client/month context.
                                            #
                                            # Example of what NOT to do here typically:
                                            # from exportador_contasol.main import export_data_to_contasol_csv
                                            # some_client = "default_client" # This context is missing
                                            # current_month_year = datetime.now().strftime("%Y%m") # This context is missing
                                            # export_data_to_contasol_csv(some_client, current_month_year) -> This would re-export ALL data each time.
                                            logger.info(f"Document {file_data['name']} processed and written to sheet. Contasol export is a separate batch process.")

                                        else: # Sheet write failed
                                            logger.error(f"Failed to write asiento for {file_data['name']} to Google Sheets.")
                                            mark_file_as_processed(db, file_data['id'], file_data['name'], file_data['mimeType'], file_data['modifiedTime'], status="error_sheet_write", error_msg="Failed to write to Google Sheets")

                                    elif asiento_contable and asiento_contable.needs_manual_review: # Asiento generated but needs review
                                        # Log the asiento for debugging/review purposes
                                        logger.debug(f"Reviewable Asiento for {file_data['name']}:\n{str(asiento_contable)}")
                                        # Not writing reviewable asientos to the main sheet automatically, or write to a different "review" sheet?
                                        # For now, we don't write them if they need review. Status remains 'needs_manual_review_asiento'.
                                        logger.info(f"Asiento for {file_data['name']} needs manual review. Not writing to sheet automatically.")

                                    else: # generate_asiento returned None (critical failure)
                                        logger.error(f"Asiento generation failed critically for {file_data['name']}. No asiento object returned.")
                                        mark_file_as_processed(db, file_data['id'], file_data['name'], file_data['mimeType'], file_data['modifiedTime'], status="error_asiento_generation_failed", error_msg="generate_asiento returned None")
                                else: # Classification failed
                                    logger.warning(f"Classification failed for {file_data['name']}. No matching rule found. Marking for review.")
                                    mark_file_as_processed(db, file_data['id'], file_data['name'], file_data['mimeType'], file_data['modifiedTime'], status="needs_manual_review_classification")

                            elif extracted_text_content == "": # OCR was successful but returned empty text (e.g. blank page)
                                logger.info(f"OCR processing for {file_data['name']} resulted in empty text. Marking as 'ocr_empty_content'.")
                                mark_file_as_processed(db, file_data['id'], file_data['name'], file_data['mimeType'], file_data['modifiedTime'], status="ocr_empty_content")
                                # No classification attempt if text is empty. Could also be 'needs_manual_review_ocr_empty'.
                            else: # OCR returned None, which implies an error during OCR itself (already logged by ocr_processor)
                                # This case should ideally be caught by the ocr_exc below if process_document_from_drive raises an error.
                                # If it returns None without error, it's an unexpected state.
                                logger.error(f"OCR processing for {file_data['name']} returned None without raising an exception. This is unexpected.")
                                mark_file_as_processed(db, file_data['id'], file_data['name'], file_data['mimeType'], file_data['modifiedTime'], status="error_ocr_unexpected_none")

                        except Exception as ocr_exc:
                            logger.error(f"OCR processing failed for {file_data['name']} (ID: {file_data['id']}): {ocr_exc}", exc_info=True)
                            ocr_error = str(ocr_exc)
                            mark_file_as_processed(db, file_data['id'], file_data['name'], file_data['mimeType'], file_data['modifiedTime'], status="error_ocr", error_msg=ocr_error)

                    except Exception as e: # Catch errors from the outer loop (e.g., DB connection issues)
                        logger.error(f"Outer error processing file {file_data['name']} (ID: {file_data['id']}): {e}", exc_info=True)
                        # Ensure status reflects error if not already set by inner try-except
                        if db.query(ProcessedFile).filter(ProcessedFile.id == file_data['id']).first().status not.startswith("error"):
                             mark_file_as_processed(db, file_data['id'], file_data['name'], file_data['mimeType'], file_data['modifiedTime'], status="error_listener", error_msg=str(e))
                    finally:
                        db.close()
            else:
                logger.info("No new documents found this cycle.")

        except Exception as e:
            logger.error(f"An error occurred in the listener loop: {e}", exc_info=True)
            # Potentially add a longer sleep here if there are persistent errors like network issues

        logger.info(f"Waiting for {current_config.POLL_INTERVAL_SECONDS} seconds before next check...")
        time.sleep(current_config.POLL_INTERVAL_SECONDS)

if __name__ == "__main__":
    # This allows running the listener directly for testing or as a standalone service.
    # Ensure .env file is present in the project root (iafiscal_asientos_google)
    # and GOOGLE_APPLICATION_CREDENTIALS points to a valid service account JSON key.

    # Create a dummy .env if it doesn't exist for local testing
    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
    if not os.path.exists(env_path):
        logger.warning(f".env file not found at {env_path}. Creating a dummy .env. Please fill it with actual values.")
        with open(env_path, 'w') as f:
            f.write("FLASK_ENV=development\n")
            f.write("SECRET_KEY=pleasereplacethiskey\n")
            f.write("# --- Google Drive API ---\n")
            f.write("GOOGLE_APPLICATION_CREDENTIALS=\"config/credentials.json\" # IMPORTANT: Replace with actual path to your service account key\n")
            f.write("DRIVE_FOLDER_ID=\"YOUR_GOOGLE_DRIVE_FOLDER_ID_HERE\"\n") # IMPORTANT
            f.write("POLL_INTERVAL_SECONDS=60\n")
            f.write("# --- Google Sheets API ---\n")
            f.write("OUTPUT_SHEET_ID=\"YOUR_GOOGLE_SHEET_ID_FOR_OUTPUT_HERE\"\n") # IMPORTANT
            f.write("RULES_SHEET_FILE_ID=\"YOUR_GOOGLE_SHEET_ID_FOR_RULES_HERE_OR_LEAVE_BLANK_IF_LOCAL_XLSX\"\n")
            f.write("RULES_SHEET_NAME_XLSX=\"reglas_contables_IAFiscal.xlsx\"\n")
            f.write("# --- Database ---\n")
            f.write("DATABASE_URL=\"sqlite:///./iafiscal_data.db\"\n") # Creates db in project root
            f.write("# --- OCR ---\n")
            f.write("#TESSERACT_CMD=\"/usr/bin/tesseract\" # Optional: if tesseract is not in PATH\n")
            f.write("# --- Logging ---\n")
            f.write("LOG_LEVEL=INFO\n")
        logger.info(f"Dummy .env file created at {env_path}. Please edit it with your actual configuration values.")
        print(f"ACTION REQUIRED: Please edit the .env file at {env_path} with your actual Google Drive Folder ID and other settings.")
    else:
        # Attempt to load environment variables again in case current_config was initialized before .env existed
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=env_path, override=True)
        current_config.DRIVE_FOLDER_ID = os.getenv('DRIVE_FOLDER_ID') # Re-load specific critical vars
        current_config.GOOGLE_APPLICATION_CREDENTIALS = os.getenv('GOOGLE_APPLICATION_CREDENTIALS', 'config/credentials.json')
        current_config.DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///./iafiscal_data.db')

        # Re-initialize engine and SessionLocal if DATABASE_URL might have changed
        global engine, SessionLocal, Base
        engine = create_engine(current_config.DATABASE_URL)
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        Base.metadata.create_all(bind=engine)


    if not current_config.DRIVE_FOLDER_ID:
        logger.error("DRIVE_FOLDER_ID is not set even after .env check. Please set it in your .env file.")
        print("CRITICAL: DRIVE_FOLDER_ID is not set. The listener cannot run. Please set it in your .env file.")
    elif current_config.DRIVE_FOLDER_ID == "YOUR_GOOGLE_DRIVE_FOLDER_ID_HERE":
        logger.error("DRIVE_FOLDER_ID is set to the placeholder value. Please update it in your .env file with the actual Folder ID.")
        print("CRITICAL: DRIVE_FOLDER_ID is a placeholder. The listener cannot run. Please set it in your .env file.")
    elif not os.path.exists(os.path.join(os.path.dirname(os.path.dirname(__file__)), current_config.GOOGLE_APPLICATION_CREDENTIALS)):
        logger.error(f"Google credentials file not found at '{current_config.GOOGLE_APPLICATION_CREDENTIALS}'. "
                     "Please ensure the path is correct in .env and the file exists.")
        print(f"CRITICAL: Google credentials file not found at '{current_config.GOOGLE_APPLICATION_CREDENTIALS}'. The listener cannot run.")
    else:
        logger.info("Starting listener...")
        run_listener()

# To make ProcessedFile accessible for alembic or other ORM tools if this file is imported
# db_models.py could be a better place for this if the project grows.
# For now, keeping it here as it's tightly coupled with the listener's logic.
# from sqlalchemy.ext.declarative import declarative_base
# Base = declarative_base() # already defined above

# If you intend to use Flask-SQLAlchemy, the setup is a bit different:
# from flask_sqlalchemy import SQLAlchemy
# db = SQLAlchemy() # initialized in app.py
# class ProcessedFile(db.Model): ...
# But for a standalone listener, SQLAlchemy directly is fine.
