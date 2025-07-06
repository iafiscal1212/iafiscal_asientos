import os
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')) # Load .env from project root

class Config:
    """Base configuration."""
    SECRET_KEY = os.getenv('SECRET_KEY', 'mysecretkey')
    DEBUG = False
    TESTING = False
    DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///iafiscal_data.db')

    # Google Drive API
    GOOGLE_APPLICATION_CREDENTIALS = os.getenv('GOOGLE_APPLICATION_CREDENTIALS', 'config/credentials.json')
    DRIVE_FOLDER_ID = os.getenv('DRIVE_FOLDER_ID') # ID of the "IAFiscal-Jules" folder
    ALLOWED_MIMETYPES = {
        'application/pdf': 'pdf', # PDF
        'image/jpeg': 'jpg',      # JPG
        'image/png': 'png',       # PNG (add if needed, though spec said JPG)
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'xlsx', # Excel
        'application/vnd.ms-excel': 'xls' # Older Excel
    }
    POLL_INTERVAL_SECONDS = int(os.getenv('POLL_INTERVAL_SECONDS', 60)) # Time to wait between Drive scans

    # Google Sheets API
    OUTPUT_SHEET_ID = os.getenv('OUTPUT_SHEET_ID') # ID of the Google Sheet to write entries
    RULES_SHEET_FILE_ID = os.getenv('RULES_SHEET_FILE_ID') # ID of the Google Sheet containing rules (if on Drive)
    RULES_SHEET_NAME_XLSX = os.getenv('RULES_SHEET_NAME_XLSX', "reglas_contables_IAFiscal.xlsx") # Or local path

    # OCR Processor
    TESSERACT_CMD = os.getenv('TESSERACT_CMD') # Path to tesseract executable if not in PATH

    # Exportador Contasol
    CONTASOL_CSV_SEPARATOR = ";"
    CONTASOL_ENCODING = "utf-8" # utf-8-sig might be needed for Excel to correctly open CSVs with BOM

    # Application specific
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')


class DevelopmentConfig(Config):
    DEBUG = True
    LOG_LEVEL = 'DEBUG'

class TestingConfig(Config):
    TESTING = True
    DATABASE_URL = os.getenv('TEST_DATABASE_URL', 'sqlite:///:memory:') # Use in-memory for tests
    DRIVE_FOLDER_ID = "test_drive_folder_id"
    OUTPUT_SHEET_ID = "test_output_sheet_id"
    RULES_SHEET_FILE_ID = "test_rules_sheet_id"


class ProductionConfig(Config):
    # Production specific settings
    POLL_INTERVAL_SECONDS = int(os.getenv('POLL_INTERVAL_SECONDS', 300)) # Poll less frequently in prod
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'WARNING')


# Helper to get config based on environment variable
def get_config():
    env = os.getenv('FLASK_ENV', 'development')
    if env == 'production':
        return ProductionConfig()
    elif env == 'testing':
        return TestingConfig()
    return DevelopmentConfig()

# Initialize config instance for easy import
current_config = get_config()

# Example of how to use in your app.py:
# from config.settings import current_config
# app.config.from_object(current_config)
# print(current_config.DRIVE_FOLDER_ID)
