# This script is intended to be run as a standalone service to monitor Google Drive.
# It's separate from the Flask app (app.py) which might serve API endpoints.

import os
import sys
import logging

# Ensure the project root is in the Python path
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Now import from the project modules
from drive_listener.listener import run_listener, logger as listener_logger # Use the logger from listener module
from config.settings import current_config

def setup_logging():
    # Configure logging for the service if not already done by the listener module
    # The listener module already configures its logger, so this might be redundant
    # or could be used to add service-specific handlers/formatters if needed.
    log_level_str = current_config.LOG_LEVEL.upper()
    log_level = getattr(logging, log_level_str, logging.INFO)

    # Basic configuration (if listener hasn't already set it up system-wide)
    if not logging.getLogger().handlers: # Check if root logger has handlers
        logging.basicConfig(level=log_level,
                            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                            handlers=[logging.StreamHandler(sys.stdout)]) # Ensure logs go to stdout for container environments

    # You can also get the listener's logger and add specific handlers for the service context
    service_logger = logging.getLogger("DriveListenerService")
    if not service_logger.handlers:
        service_logger.setLevel(log_level)
        # Example: Add a handler if you want separate logging for the service runner itself
        # handler = logging.StreamHandler(sys.stdout)
        # formatter = logging.Formatter('%(asctime)s - SERVICE - %(levelname)s - %(message)s')
        # handler.setFormatter(formatter)
        # service_logger.addHandler(handler)
        # service_logger.propagate = False # To avoid duplicate logs if root logger is also configured
    else: # if listener_logger already configured, just use it or get it by name
        pass

    listener_logger.info(f"Logging setup for Drive Listener Service with level {log_level_str}.")
    return listener_logger # Return the main logger used by the listener logic

if __name__ == "__main__":
    # Create a dummy .env if it doesn't exist for local testing, similar to listener.py's main block
    env_path = os.path.join(project_root, '.env')
    if not os.path.exists(env_path):
        listener_logger.warning(f".env file not found at {env_path}. Creating a dummy .env. Please fill it with actual values.")
        with open(env_path, 'w') as f:
            f.write("FLASK_ENV=development\n")
            f.write("SECRET_KEY=pleasereplacethiskey\n")
            f.write("GOOGLE_APPLICATION_CREDENTIALS=\"config/credentials.json\"\n")
            f.write("DRIVE_FOLDER_ID=\"YOUR_GOOGLE_DRIVE_FOLDER_ID_HERE\"\n")
            f.write("POLL_INTERVAL_SECONDS=60\n")
            f.write("OUTPUT_SHEET_ID=\"YOUR_GOOGLE_SHEET_ID_FOR_OUTPUT_HERE\"\n")
            f.write("RULES_SHEET_FILE_ID=\"YOUR_GOOGLE_SHEET_ID_FOR_RULES_HERE_OR_LEAVE_BLANK_IF_LOCAL_XLSX\"\n")
            f.write("RULES_SHEET_NAME_XLSX=\"reglas_contables_IAFiscal.xlsx\"\n")
            f.write("DATABASE_URL=\"sqlite:///./iafiscal_data.db\"\n")
            f.write("LOG_LEVEL=INFO\n")
        listener_logger.info(f"Dummy .env file created at {env_path}. Please edit it with your actual configuration values.")
        print(f"ACTION REQUIRED: Please edit the .env file at {env_path} with your actual Google Drive Folder ID and other settings.")
        # Exit if .env was just created, to force user to fill it.
        sys.exit("Please configure the .env file and restart the service.")


    # (Re)Load .env variables after ensuring it exists
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=env_path, override=True) # Override to ensure fresh values are loaded

    # Update current_config with potentially new values from .env
    # This is a bit of a hack; ideally, config is immutable after first load.
    # However, for this standalone script, it helps ensure .env changes are picked up.
    current_config.DRIVE_FOLDER_ID = os.getenv('DRIVE_FOLDER_ID')
    current_config.GOOGLE_APPLICATION_CREDENTIALS = os.getenv('GOOGLE_APPLICATION_CREDENTIALS', 'config/credentials.json')
    current_config.DATABASE_URL = os.getenv('DATABASE_URL', f'sqlite:///{os.path.join(project_root, "iafiscal_data.db")}')
    current_config.LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')

    # Re-initialize SQLAlchemy engine in listener if DATABASE_URL could have changed
    # This is tricky because the engine might be already initialized when listener module was imported.
    # For simplicity, listener.py's __main__ block already handles re-init if run directly.
    # If run_listener_service.py is the main entry point, we need to ensure listener's components
    # (like SQLAlchemy engine) use the latest config.
    # One way is to have listener.py's functions re-initialize or fetch config on demand,
    # or pass config explicitly.
    # The listener.py's `if __name__ == "__main__":` block has logic to re-init engine.
    # We might need to call a similar setup function here if run_listener_service.py is the primary entry point.
    # For now, assume listener.py handles its DB setup correctly based on current_config.

    logger = setup_logging() # Setup logging for this service context

    logger.info("Starting the Google Drive Listener Service...")

    # Pre-run checks from listener.py's main block
    if not current_config.DRIVE_FOLDER_ID or current_config.DRIVE_FOLDER_ID == "YOUR_GOOGLE_DRIVE_FOLDER_ID_HERE":
        logger.critical("DRIVE_FOLDER_ID is not set or is a placeholder. The listener service cannot run. Please set it in your .env file.")
        sys.exit("CRITICAL: DRIVE_FOLDER_ID configuration is missing or invalid.")

    creds_path = os.path.join(project_root, current_config.GOOGLE_APPLICATION_CREDENTIALS)
    if not os.path.exists(creds_path):
        logger.critical(f"Google credentials file not found at '{creds_path}'. "
                        "Please ensure the path is correct in .env and the file exists.")
        sys.exit(f"CRITICAL: Google credentials file not found at '{creds_path}'.")

    try:
        run_listener() # This function contains the main loop
    except KeyboardInterrupt:
        logger.info("Listener service stopped manually (KeyboardInterrupt).")
    except Exception as e:
        logger.critical(f"Listener service encountered a fatal error and stopped: {e}", exc_info=True)
        sys.exit(f"Listener service failed: {e}")
    finally:
        logger.info("Google Drive Listener Service has shut down.")
