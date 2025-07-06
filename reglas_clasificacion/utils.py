import pandas as pd
import os
import logging
import re
from typing import List, Dict, Optional, Tuple, Any

from config.settings import current_config
# To download rules file from Drive if needed
from drive_listener.utils import get_drive_service, download_file as download_drive_file
# Assuming TEMP_DOWNLOAD_DIR is accessible or defined in current_config for temporary rule file storage
from ocr_processor.main import TEMP_DOWNLOAD_DIR as SHARED_TEMP_DIR


logger = logging.getLogger(__name__)

# Global variable to cache the loaded rules, to avoid reading the file on every call
# The structure could be a list of rule dictionaries, or a Pandas DataFrame
CACHED_RULES: Optional[pd.DataFrame] = None
RULES_FILE_PATH: Optional[str] = None # Path to the local rules file (either provided or downloaded)
RULES_FILE_LAST_MODIFIED: Optional[float] = None # Timestamp of the last modification of the rules file

# Define expected columns in the Excel rule sheet (can be adjusted)
# These names should match the column headers in 'reglas_contables_IAFiscal.xlsx'
# Example columns:
# - 'PalabraClave' (Keyword(s) to search in OCR text, can be regex)
# - 'Prioridad' (Numeric, for resolving conflicts if multiple rules match; higher wins)
# - 'CuentaDebe' (Debit Account)
# - 'CuentaHaber' (Credit Account - often a provider or bank, might be more complex)
# - 'TipoIVA' (e.g., 'General 21%', 'Reducido 10%', 'Superreducido 4%', 'Exento', 'NoSujeto')
# - 'TratamientoEspecial' (e.g., 'IRPF', 'InversionSujetoPasivo', 'RetencionAlquiler')
# - 'RequiereProveedor' (Boolean: True if this rule implies a specific provider account needs to be found/created)
# - 'ProveedorSubcuentaBase' (e.g., 400, 410 - base for provider subaccounts if not specific)
# - 'ConceptoAsiento' (Template for the accounting entry concept, can use placeholders like {FacturaN})

# For simplicity, let's start with a few key columns. This needs to match the actual Excel.
# Let's assume the project description's output: "cuenta contable, tipo, tratamiento especial"
# And input: "concepto extraído por OCR"
# So, rules should map keywords in "concepto" to "cuenta contable", "tipo", "tratamiento especial".

# Revised assumed columns for `reglas_contables_IAFiscal.xlsx`
# 'Keywords': Comma-separated strings or regex patterns to search in the OCR text.
# 'Priority': Integer, higher value means higher priority.
# 'Account': The primary account to be used (e.g., a Gasto account like 628, or an Ingreso account like 700).
#            This might be the 'cuenta_debe' for expenses or 'cuenta_haber' for income.
# 'Contrapartida': The typical contra-account (e.g., 572 for bank, 400 for supplier, 430 for client).
#                  This can be generic and refined later.
# 'TipoOperacion': (e.g., 'Gasto', 'Ingreso', 'CompraActivo') - helps determine Debe/Haber logic.
# 'IVAType': (e.g., '21%', '10%', '4%', '0% Exento', 'No Sujeto', 'ISP') - for IVA calculation.
# 'SpecialTreatment': (e.g., 'IRPF 15%', 'Retencion Alquiler 19%', 'BienInversion') - for special logic.
# 'ConceptoPatron': A pattern for the accounting entry's concept, e.g., "Factura {proveedor} Nro {factura_n}"

EXPECTED_RULE_COLUMNS = {
    "Keywords": str,
    "Priority": int,
    "Account": str,
    "Contrapartida": str, # Can be more complex, e.g. a function to determine it
    "TipoOperacion": str, # e.g., 'Gasto corriente', 'Ingreso ventas', 'Compra Activo Fijo'
    "IVAType": str, # e.g., 'General (21%)', 'Reducido (10%)', 'Exento', 'No Sujeto', 'ISP'
    "SpecialTreatment": str, # e.g., 'IRPF (15%)', 'Retención Alquiler (19%)', 'Recargo Equivalencia'
    "ConceptoPatron": str, # e.g., "Factura {proveedor} N. {factura_num}"
    # "CuentaDebe": str, # Alternative to Account/Contrapartida/TipoOperacion
    # "CuentaHaber": str, # Alternative
}


def get_rules_file_path() -> Optional[str]:
    """
    Determines the path to the rules file.
    It can be a local path or downloaded from Google Drive.
    """
    global RULES_FILE_PATH

    # Option 1: Rules file is specified as a local path in .env
    local_rules_path_env = os.getenv('LOCAL_RULES_FILE_PATH') # e.g., "config/reglas_contables_IAFiscal.xlsx"
    if local_rules_path_env:
        # Ensure it's an absolute path or relative to project root
        if os.path.isabs(local_rules_path_env):
            RULES_FILE_PATH = local_rules_path_env
        else:
            RULES_FILE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), local_rules_path_env) # Project root

        if os.path.exists(RULES_FILE_PATH):
            logger.info(f"Using local rules file: {RULES_FILE_PATH}")
            return RULES_FILE_PATH
        else:
            logger.warning(f"Local rules file specified but not found: {RULES_FILE_PATH}. Will attempt Drive download if configured.")
            RULES_FILE_PATH = None # Reset if not found, to allow fallback

    # Option 2: Rules file ID is specified for Google Drive download
    rules_file_id_drive = current_config.RULES_SHEET_FILE_ID
    rules_file_name_xlsx = current_config.RULES_SHEET_NAME_XLSX # Default: "reglas_contables_IAFiscal.xlsx"

    if rules_file_id_drive:
        logger.info(f"Rules file ID from Drive configured: {rules_file_id_drive}. Attempting to download/use cached.")
        # Define a path to store the downloaded rules file, e.g., in a config or temp directory
        # Using the SHARED_TEMP_DIR from ocr_processor for consistency, or a dedicated config dir
        # Make sure this directory exists
        os.makedirs(SHARED_TEMP_DIR, exist_ok=True)
        downloaded_rules_path = os.path.join(SHARED_TEMP_DIR, rules_file_name_xlsx)

        # Potentially check if the file on Drive is newer than local cache before re-downloading
        # This would require getting file metadata (modifiedTime) from Drive API.
        # For simplicity now, we might re-download if cache is stale or always if configured.
        # Let's assume load_rules will handle freshness check of the file itself.

        if not os.path.exists(downloaded_rules_path): # Or if it's stale
             logger.info(f"Local cache of rules file not found at {downloaded_rules_path} or is stale. Downloading from Drive ID {rules_file_id_drive}...")
             try:
                 drive_service = get_drive_service()
                 download_success_path = download_drive_file(drive_service, rules_file_id_drive, downloaded_rules_path)
                 if download_success_path and os.path.exists(download_success_path):
                     logger.info(f"Successfully downloaded rules file to {download_success_path}")
                     RULES_FILE_PATH = download_success_path
                 else:
                     logger.error(f"Failed to download rules file from Drive ID {rules_file_id_drive}.")
                     return None # Fallback or error
             except Exception as e:
                 logger.error(f"Error downloading rules file from Drive: {e}")
                 return None
        else:
            logger.info(f"Using cached rules file from Drive download: {downloaded_rules_path}")
            RULES_FILE_PATH = downloaded_rules_path
        return RULES_FILE_PATH

    # Option 3: Default local path if no other config (as per project description)
    # The project description implies `reglas_contables_IAFiscal.xlsx` is a known file.
    # Assume it's in the project root or a 'config' subdirectory if not otherwise specified.
    if not RULES_FILE_PATH:
        default_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), current_config.RULES_SHEET_NAME_XLSX) # Project root
        if os.path.exists(default_path):
            logger.info(f"Using default local rules file: {default_path}")
            RULES_FILE_PATH = default_path
            return RULES_FILE_PATH

        default_config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'config', current_config.RULES_SHEET_NAME_XLSX) # Project root/config
        if os.path.exists(default_config_path):
            logger.info(f"Using default local rules file from config dir: {default_config_path}")
            RULES_FILE_PATH = default_config_path
            return RULES_FILE_PATH

    if not RULES_FILE_PATH:
        logger.error("Rules file (reglas_contables_IAFiscal.xlsx) not found or configured. "
                     "Set LOCAL_RULES_FILE_PATH or RULES_SHEET_FILE_ID in .env, "
                     "or place the file in the project root /config directory.")
        return None

    return RULES_FILE_PATH


def load_rules(force_reload: bool = False) -> Optional[pd.DataFrame]:
    """
    Loads the classification rules from the Excel file.
    Caches the rules in memory to avoid repeated file I/O.
    Checks if the file has been modified since last load and reloads if necessary.

    Args:
        force_reload (bool): If True, bypasses cache and forces a reload from file.

    Returns:
        pd.DataFrame: DataFrame containing the rules, or None if loading fails.
    """
    global CACHED_RULES, RULES_FILE_PATH, RULES_FILE_LAST_MODIFIED

    # Determine the rules file path (handles local vs. Drive download logic)
    # This call might download the file if it's from Drive and not cached/stale
    current_rules_file_path = get_rules_file_path()

    if not current_rules_file_path or not os.path.exists(current_rules_file_path):
        logger.error(f"Rules file path not resolved or file does not exist: {current_rules_file_path}")
        CACHED_RULES = None
        return None

    # Check if file modification time has changed
    try:
        modified_time = os.path.getmtime(current_rules_file_path)
        if RULES_FILE_LAST_MODIFIED is not None and modified_time == RULES_FILE_LAST_MODIFIED and \
           CACHED_RULES is not None and not force_reload and current_rules_file_path == RULES_FILE_PATH:
            logger.debug("Using cached rules (file unchanged).")
            return CACHED_RULES

        logger.info(f"Loading rules from: {current_rules_file_path} (Force reload: {force_reload}, File modified: {modified_time != RULES_FILE_LAST_MODIFIED})")

        # Read the Excel file. Assuming rules are in the first sheet.
        # Add error handling for file reading (e.g., if file is corrupted, wrong format)
        rules_df = pd.read_excel(current_rules_file_path, sheet_name=0, dtype=str) # Read all as string first

        # Validate and preprocess rules
        # 1. Check for expected columns
        missing_cols = [col for col in EXPECTED_RULE_COLUMNS if col not in rules_df.columns]
        if missing_cols:
            logger.error(f"Rules file '{current_rules_file_path}' is missing expected columns: {', '.join(missing_cols)}. "
                         f"Expected columns are: {', '.join(EXPECTED_RULE_COLUMNS.keys())}")
            CACHED_RULES = None # Invalidate cache
            return None

        # 2. Convert columns to their expected types and handle potential errors
        for col, col_type in EXPECTED_RULE_COLUMNS.items():
            if col in rules_df.columns:
                try:
                    if col_type == int:
                        # Handle non-integer values gracefully, e.g., set to 0 or NaN then drop/fill
                        rules_df[col] = pd.to_numeric(rules_df[col], errors='coerce').fillna(0).astype(int)
                    elif col_type == float: # If you had float types
                        rules_df[col] = pd.to_numeric(rules_df[col], errors='coerce').astype(float)
                    elif col_type == bool: # If you had boolean types
                         # Assuming 'True', 'true', '1' are True, others False
                        rules_df[col] = rules_df[col].astype(str).str.lower().isin(['true', '1', 'yes'])
                    else: # string type (already mostly str, but ensure)
                        rules_df[col] = rules_df[col].astype(str).fillna('') # Fill NaN with empty string for text fields
                except ValueError as ve:
                    logger.error(f"Error converting column '{col}' to type {col_type.__name__} in rules file: {ve}. Check data.")
                    # Mark relevant rows as invalid or skip them, or fail loading
                    # For now, let's assume it might partially convert and NaNs might appear for unconvertible values
                    CACHED_RULES = None
                    return None

        # 3. Sort by Priority (descending, so higher priority comes first)
        if "Priority" in rules_df.columns:
            rules_df = rules_df.sort_values(by="Priority", ascending=False).reset_index(drop=True)
        else:
            logger.warning("No 'Priority' column found in rules. Rules will be processed in order of appearance.")

        # 4. Pre-compile regex if Keywords are regex patterns (optional optimization)
        # For now, assume direct string matching or simple "in" checks.
        # If using regex, you might add a column like 'RegexPattern' to the DataFrame.
        # Example for regex compilation (if Keywords are regex):
        # def compile_regex(pattern_str):
        #     try: return re.compile(pattern_str, re.IGNORECASE) # IGNORECASE is often useful
        #     except re.error: return None # Handle invalid regex
        # if 'KeywordsAreRegex' in rules_df.columns and rules_df['KeywordsAreRegex'].any():
        #    rules_df['CompiledKeywordRegex'] = rules_df.apply(
        #        lambda row: compile_regex(row['Keywords']) if row['KeywordsAreRegex'] else None, axis=1
        #    )

        CACHED_RULES = rules_df
        RULES_FILE_PATH = current_rules_file_path # Update path if it changed (e.g. first load)
        RULES_FILE_LAST_MODIFIED = modified_time
        logger.info(f"Successfully loaded and processed {len(CACHED_RULES)} rules.")
        return CACHED_RULES

    except FileNotFoundError:
        logger.error(f"Rules file not found at path: {current_rules_file_path}")
        CACHED_RULES = None
        return None
    except pd.errors.EmptyDataError:
        logger.error(f"Rules file is empty or not a valid Excel file: {current_rules_file_path}")
        CACHED_RULES = None
        return None
    except Exception as e:
        logger.error(f"Failed to load or parse rules from '{current_rules_file_path}': {e}", exc_info=True)
        CACHED_RULES = None
        return None


def match_rule(text_content: str, rules_df: pd.DataFrame) -> Optional[Dict[str, Any]]:
    """
    Matches the given text content against the loaded rules.
    Returns the highest priority matching rule.

    Args:
        text_content (str): The OCR'd text or content from the document.
        rules_df (pd.DataFrame): The DataFrame of loaded rules.

    Returns:
        Optional[Dict[str, Any]]: A dictionary representing the matched rule, or None if no match.
    """
    if not text_content or rules_df is None or rules_df.empty:
        return None

    text_content_lower = text_content.lower() # Normalize text for matching (optional)

    for index, rule in rules_df.iterrows():
        keywords_str = rule.get("Keywords", "")
        if not keywords_str or pd.isna(keywords_str): # Skip if keywords are missing for this rule
            continue

        # Keywords can be comma-separated. Each part should be checked.
        # We can implement AND logic (all keywords must match) or OR logic (any keyword matches).
        # Let's assume OR logic for individual keywords listed, and AND for keywords separated by a special character if needed.
        # For now, simple comma-separated OR logic:
        rule_keywords = [kw.strip().lower() for kw in keywords_str.split(',')]

        # If using regex:
        # compiled_regex = rule.get('CompiledKeywordRegex')
        # if compiled_regex and compiled_regex.search(text_content): # No need for lower() if regex handles case-insensitivity
        #    logger.info(f"Rule matched (Regex: '{rule['Keywords']}')")
        #    return rule.to_dict()

        # Simple string search (any keyword match)
        if any(kw in text_content_lower for kw in rule_keywords if kw): # Ensure kw is not empty string
            logger.info(f"Rule matched (Keywords: '{keywords_str}', Priority: {rule.get('Priority', 'N/A')})")
            # Return the first match due to pre-sorting by priority
            return rule.to_dict()

    logger.info("No classification rule matched the provided text content.")
    return None


if __name__ == '__main__':
    # Example Usage & Testing
    logging.basicConfig(level=logging.DEBUG) # Set to DEBUG to see more detailed logs

    # Ensure .env is loaded for current_config to have values (especially for Drive download)
    env_path_proj = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '.env')
    if os.path.exists(env_path_proj):
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=env_path_proj, override=True)
        logger.info(f"Loaded .env from {env_path_proj} for testing.")
    else:
        logger.warning(f".env file not found at {env_path_proj}. Some configurations might be missing.")


    # 1. Test loading rules (this might trigger a download if configured for Drive)
    logger.info("--- Testing Rule Loading ---")
    rules = load_rules(force_reload=True) # Force reload for testing
    if rules is not None:
        logger.info(f"Loaded {len(rules)} rules. Columns: {rules.columns.tolist()}")
        # print("\nSample of loaded rules:")
        # print(rules.head())
    else:
        logger.error("Failed to load rules. Check previous error messages.")
        # Create a dummy rules file if none could be loaded, for further testing of match_rule
        logger.info("Attempting to create a dummy rules Excel file for testing match_rule...")
        dummy_rules_data = {
            "Keywords": ["factura energia,luz,gas", "alquiler local", "compra ordenador,portatil", "nomina empleado", "ingreso servicio web"],
            "Priority": [10, 10, 8, 12, 10],
            "Account": ["628", "621", "217", "640", "705"],
            "Contrapartida": ["410ENDESA", "410PROPIETARIO", "410PCSTORE", "465REMUNERACIONES", "430CLIENTEWEB"],
            "TipoOperacion": ["Gasto Suministros", "Gasto Alquiler", "Compra Inmovilizado", "Gasto Personal", "Ingreso Servicios"],
            "IVAType": ["General (21%)", "General (21%)", "General (21%)", "No Sujeto", "General (21%)"],
            "SpecialTreatment": ["", "Retencion Alquiler (19%)", "", "", ""],
            "ConceptoPatron": ["Factura luz {proveedor} N.{factura_n}", "Alquiler local {mes}/{ano}", "Compra PC {marca_modelo}", "Nomina {empleado} {mes}", "Servicio diseño web {cliente}"]
        }
        dummy_rules_df = pd.DataFrame(dummy_rules_data)

        # Save to where get_rules_file_path would expect it, e.g., project root/config
        dummy_file_name = current_config.RULES_SHEET_NAME_XLSX or "reglas_contables_IAFiscal.xlsx"
        dummy_rules_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'config', dummy_file_name)
        os.makedirs(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'config'), exist_ok=True)
        try:
            dummy_rules_df.to_excel(dummy_rules_path, index=False)
            logger.info(f"Created dummy rules file at {dummy_rules_path}. Please populate it with realistic rules.")
            # Try loading again
            rules = load_rules(force_reload=True)
            if rules is not None:
                 logger.info(f"Successfully loaded dummy rules: {len(rules)} rules.")
            else:
                 logger.error("Still failed to load dummy rules.")
        except Exception as e:
            logger.error(f"Could not create or load dummy rules file: {e}")


    # 2. Test rule matching (if rules were loaded)
    if rules is not None and not rules.empty:
        logger.info("\n--- Testing Rule Matching ---")

        test_ocr_content_1 = """
        Factura Simplificada
        Concepto: Consumo energía eléctrica
        Proveedor: Iberdrola Clientes S.A.U.
        NIF: A12345678
        Importe Total: 75.50 EUR
        Fecha: 2023-10-15
        """

        test_ocr_content_2 = """
        Recibo de alquiler del local comercial sito en Calle Falsa 123.
        Mes de Octubre 2023.
        Arrendador: Juan Pérez.
        Importe: 600 EUR + IVA. Retención IRPF: 19%.
        """

        test_ocr_content_3 = "Compra de nuevo portátil HP Spectre para desarrollo. Tienda: PCComponentes. Garantía 3 años."

        test_ocr_content_no_match = "Este es un documento que no debería coincidir con ninguna regla específica de gastos o ingresos comunes."

        for i, content in enumerate([test_ocr_content_1, test_ocr_content_2, test_ocr_content_3, test_ocr_content_no_match]):
            logger.info(f"\nMatching content {i+1}:")
            # print(content[:100] + "...") # Print snippet of content
            matched = match_rule(content, rules)
            if matched:
                logger.info(f"Matched Rule: {matched}")
            else:
                logger.info("No rule matched.")
    else:
        logger.warning("Skipping rule matching test as rules were not loaded.")

    logger.info("\n--- Test Finished ---")
