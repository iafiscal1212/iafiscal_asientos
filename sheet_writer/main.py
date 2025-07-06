import logging
from typing import List, Any, Optional
from decimal import Decimal

from config.settings import current_config
from generador_asientos.main import AsientoContable, ApunteContable # Input object
from .utils import append_rows_to_sheet, ensure_header_row

logger = logging.getLogger(__name__)

# Define the columns for the Google Sheet as per project specification
# Columnas: fecha, cuenta_debe, importe_debe, cuenta_haber, importe_haber,
#           concepto, proveedor, enlace_documento, iva
# This structure is a bit denormalized if an asiento has multiple debit/credit lines.
# A common way to represent asientos in a flat sheet is one row per *apunte* (line item),
# with some asiento-level info repeated.
# Let's assume one row per apunte for now.

# Header row for the Google Sheet
# This structure assumes we might have some asiento-level data repeated per line if needed,
# or we primarily focus on the individual apuntes.
# The spec "cuenta_debe, importe_debe, cuenta_haber, importe_haber" suggests a single line might represent
# a simple asiento or that we need to decide how to map multi-line asientos.
# Let's try to make each row in Sheets correspond to one ApunteContable, plus asiento-level info.

# Revised header based on "one row per apunte" and including all specified fields:
SHEET_HEADER_COLUMNS = [
    "Asiento_Fecha",        # AsientoContable.fecha
    "Asiento_Diario",       # AsientoContable.diario_code
    "Asiento_Concepto",     # AsientoContable.concepto_general
    "Apunte_Cuenta",        # ApunteContable.cuenta
    "Apunte_Concepto",      # ApunteContable.concepto (specific line concept)
    "Apunte_Debe",          # ApunteContable.debe
    "Apunte_Haber",         # ApunteContable.haber
    "Documento_ID",         # AsientoContable.document_id (e.g. Drive File ID)
    "Enlace_Documento",     # AsientoContable.document_link (e.g. Drive webViewLink)
    "Proveedor_Nombre",     # Extracted from Asiento.extracted_info (if available)
    "Proveedor_NIF",        # Extracted
    "Cliente_Nombre",       # Extracted
    "Cliente_NIF",          # Extracted
    "Base_Imponible",       # Extracted (Asiento level)
    "IVA_Tipo",             # From Classification/Rule (Asiento level)
    "IVA_Cuota_Calculada",  # Calculated (Asiento level)
    "IRPF_Tipo",            # From Classification/Rule (Asiento level)
    "IRPF_Cuota_Calculada", # Calculated (Asiento level)
    "Total_Factura",        # Extracted (Asiento level)
    "Necesita_Revision",    # AsientoContable.needs_manual_review (boolean)
    "Motivo_Revision"       # AsientoContable.review_reason
]
# The original spec was: [fecha, cuenta_debe, importe_debe, cuenta_haber, importe_haber, concepto, proveedor, enlace_documento, iva]
# This is tricky for multi-line asientos.
# If we must stick to that for *each asiento as one row*:
# - How to handle multiple debits/credits? Concatenate? Take first? This is lossy.
# - 'iva': just the rate? the amount?
# Let's assume the more detailed "one row per apunte" is better and can be adapted for export later.
# If the sheet must be simpler, we might need to summarize or pick primary lines.

# For now, sticking to "one row per apunte" as it's more complete.
# The export_contasol part will then re-format this.

# Configuration for the target sheet
SPREADSHEET_ID = current_config.OUTPUT_SHEET_ID # From .env
TARGET_SHEET_NAME = "IAFiscal_Asientos_Generados" # Or make this configurable


def asiento_to_sheet_rows(asiento: AsientoContable) -> List[List[Any]]:
    """
    Converts an AsientoContable object into a list of rows suitable for Google Sheets,
    with one row per apunte (accounting line).

    Args:
        asiento (AsientoContable): The accounting entry to convert.

    Returns:
        List[List[Any]]: A list of lists, where each inner list is a row for the sheet.
                         Returns empty list if asiento has no apuntes.
    """
    rows = []
    if not asiento.apuntes:
        logger.warning(f"Asiento with fecha {asiento.fecha} has no apuntes. Cannot convert to sheet rows.")
        return rows

    # Asiento-level information (repeated for each apunte row, or could be normalized differently)
    asiento_fecha = asiento.fecha
    asiento_diario = asiento.diario_code
    asiento_concepto_general = asiento.concepto_general
    document_id = asiento.document_id
    document_link = asiento.document_link

    # Extract details that were populated by information_extractor into classified_transaction.extracted_info
    # These are now part of the AsientoContable object if generate_asiento was modified to pass them through,
    # or if we assume ClassifiedTransaction is available here.
    # For now, let's assume AsientoContable has an `extracted_info` dict similar to ClassifiedTransaction.
    # This needs to be ensured by `generate_asiento`'s logic.
    # Let's assume `asiento.classified_transaction_details.extracted_info` exists or similar.
    # For this example, let's say `generate_asiento` stores them directly in `asiento.extracted_invoice_data`

    # This part is tricky as AsientoContable doesn't currently store all raw extracted details.
    # It should, or we need to pass ClassifiedTransaction alongside AsientoContable.
    # Let's assume for now that `asiento` object gets these fields populated by the generator.
    # This requires modification in `generador_asientos/main.py` to store these in AsientoContable.
    # For now, we will use placeholders or extract what we can from the current AsientoContable structure.

    # Placeholder: these should come from the classified_transaction used to make the asiento
    # If generate_asiento stored the classified_transaction or its extracted_info:
    # extracted_info = asiento.classified_transaction.extracted_info if hasattr(asiento, 'classified_transaction') else {}
    # For now, we'll simulate that these are accessible or were part of asiento creation.
    # This requires that `generate_asiento` stores these. Let's assume it does for this module.
    # If not, this function signature would need `ClassifiedTransaction` too.

    # Let's make a temporary assumption that some key extracted data is copied to asiento.meta_data by generator
    # This is not ideal. Better to pass ClassifiedTransaction too or embed it.
    # For now, this part will be sparse.
    # This is a GAP: AsientoContable needs to carry more source data for reporting.
    # For the purpose of this module, let's assume these fields are somehow available on `asiento`.
    # We'll use Nones as placeholders if they are not on `asiento` object directly.

    # These would ideally come from `asiento.extracted_info` if populated by `generate_asiento`
    proveedor_nombre = getattr(asiento, 'proveedor_nombre', None)
    proveedor_nif = getattr(asiento, 'proveedor_nif', None)
    cliente_nombre = getattr(asiento, 'cliente_nombre', None)
    cliente_nif = getattr(asiento, 'cliente_nif', None)
    base_imponible_asiento = getattr(asiento, 'base_imponible', None) # Asiento-level base
    iva_tipo_asiento = getattr(asiento, 'iva_type', None) # Asiento-level IVA type
    iva_cuota_asiento = getattr(asiento, 'iva_cuota', None) # Asiento-level IVA amount
    irpf_tipo_asiento = getattr(asiento, 'irpf_type', None)
    irpf_cuota_asiento = getattr(asiento, 'irpf_cuota', None)
    total_factura_asiento = getattr(asiento, 'total_factura', None)


    for apunte in asiento.apuntes:
        row = [
            asiento_fecha,
            asiento_diario,
            asiento_concepto_general,
            apunte.cuenta,
            apunte.concepto, # Specific concept for the line
            # Convert Decimals to string for sheets, or float if preferred and locale handled. String is safer.
            str(apunte.debe) if apunte.debe != Decimal("0.00") else "",
            str(apunte.haber) if apunte.haber != Decimal("0.00") else "",
            document_id,
            document_link,
            proveedor_nombre,
            proveedor_nif,
            cliente_nombre,
            cliente_nif,
            str(base_imponible_asiento) if base_imponible_asiento is not None else "",
            iva_tipo_asiento,
            str(iva_cuota_asiento) if iva_cuota_asiento is not None else "",
            irpf_tipo_asiento,
            str(irpf_cuota_asiento) if irpf_cuota_asiento is not None else "",
            str(total_factura_asiento) if total_factura_asiento is not None else "",
            str(asiento.needs_manual_review).upper(), # TRUE/FALSE string
            asiento.review_reason
        ]
        rows.append(row)

    return rows


def write_asiento_to_sheet(asiento: AsientoContable) -> bool:
    """
    Writes a given AsientoContable to the configured Google Sheet.
    Ensures header exists, then appends rows for each apunte in the asiento.

    Args:
        asiento (AsientoContable): The accounting entry to write.

    Returns:
        bool: True if writing was successful (or no data to write), False otherwise.
    """
    if not SPREADSHEET_ID:
        logger.error("OUTPUT_SHEET_ID is not configured. Cannot write to Google Sheets.")
        return False

    if not asiento:
        logger.warning("No asiento provided to write_asiento_to_sheet.")
        return True # No error, just nothing to do.

    # 1. Ensure the header row is present in the target sheet
    header_ensured = ensure_header_row(SPREADSHEET_ID, TARGET_SHEET_NAME, SHEET_HEADER_COLUMNS)
    if not header_ensured:
        logger.error(f"Failed to ensure header row in sheet '{TARGET_SHEET_NAME}'. Aborting write for asiento fecha {asiento.fecha}.")
        return False

    # 2. Convert AsientoContable to list of rows for the sheet
    rows_to_write = asiento_to_sheet_rows(asiento)
    if not rows_to_write:
        logger.info(f"No rows generated from asiento fecha {asiento.fecha} (e.g., no apuntes). Nothing to write.")
        return True # No error, just no data.

    # 3. Append the rows to the sheet
    logger.info(f"Writing {len(rows_to_write)} row(s) for asiento fecha {asiento.fecha} to sheet '{TARGET_SHEET_NAME}'.")
    append_result = append_rows_to_sheet(SPREADSHEET_ID, TARGET_SHEET_NAME, rows_to_write)

    if append_result and append_result.get("updates", {}).get("updatedCells", 0) > 0:
        logger.info(f"Successfully wrote asiento fecha {asiento.fecha} to Google Sheets.")
        return True
    elif append_result: # No cells updated but no error from API (e.g. empty values list was sent)
        logger.info(f"Asiento fecha {asiento.fecha} resulted in no cells updated in Google Sheets (possibly empty data).")
        return True
    else:
        logger.error(f"Failed to write asiento fecha {asiento.fecha} to Google Sheets.")
        return False


if __name__ == '__main__':
    # Example Usage & Testing
    # Prerequisites for this test:
    # 1. .env file in project root with:
    #    GOOGLE_APPLICATION_CREDENTIALS="path/to/your/credentials.json"
    #    OUTPUT_SHEET_ID="your_test_spreadsheet_id_here"
    # 2. The service account must have editor access to this test spreadsheet.
    # 3. `generador_asientos` module should be runnable to create sample AsientoContable objects.

    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # Load .env from project root
    project_root_env = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '.env')
    if os.path.exists(project_root_env):
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=project_root_env, override=True)
        logger.info(f"Loaded .env from {project_root_env} for sheet_writer.main testing.")
        # Reload current_config for this module
        from config import settings
        settings.current_config = settings.get_config()
        global current_config, SPREADSHEET_ID # Update module-level globals
        current_config = settings.current_config
        SPREADSHEET_ID = current_config.OUTPUT_SHEET_ID
    else:
        logger.error(f".env file not found at {project_root_env}. Cannot run tests.")
        exit(1)

    if not SPREADSHEET_ID:
        logger.error("OUTPUT_SHEET_ID is not set in your .env file. Please set it for testing.")
        exit(1)

    logger.info(f"--- Testing Sheet Writer with Spreadsheet ID: {SPREADSHEET_ID} ---")
    logger.info(f"Target sheet name: {TARGET_SHEET_NAME}")

    # Create a sample AsientoContable object (mimicking output from generador_asientos)
    # This would normally come from `generate_asiento(classified_transaction, ...)`

    # Sample Asiento 1 (Gasto)
    asiento_test_gasto = AsientoContable(fecha="2023-11-20", diario_code="10")
    asiento_test_gasto.concepto_general = "Compra material oficina N.F2023-AB ProveedorX"
    asiento_test_gasto.document_id = "gasto_doc_id_123"
    asiento_test_gasto.document_link = "http://example.com/gasto_doc_123"

    # Populate some dummy extracted data for reporting in sheet
    # In real flow, `generate_asiento` would populate these on the AsientoContable object
    # or this data would be passed alongside. For this test, we set them manually.
    setattr(asiento_test_gasto, 'proveedor_nombre', "ProveedorX Y Z S.L.")
    setattr(asiento_test_gasto, 'proveedor_nif', "B12345678")
    setattr(asiento_test_gasto, 'base_imponible', Decimal("100.00"))
    setattr(asiento_test_gasto, 'iva_type', "General (21%)")
    setattr(asiento_test_gasto, 'iva_cuota', Decimal("21.00"))
    setattr(asiento_test_gasto, 'total_factura', Decimal("121.00"))

    asiento_test_gasto.add_apunte("629", asiento_test_gasto.concepto_general, debe=Decimal("100.00"))
    asiento_test_gasto.add_apunte("472.21", asiento_test_gasto.concepto_general, debe=Decimal("21.00"))
    asiento_test_gasto.add_apunte("400PROVX", asiento_test_gasto.concepto_general, haber=Decimal("121.00"))

    # Sample Asiento 2 (Ingreso, needs review)
    asiento_test_ingreso_review = AsientoContable(fecha="2023-11-21", diario_code="20")
    asiento_test_ingreso_review.concepto_general = "Venta servicios ClienteY F.V23-05 MAL CUADRADO"
    asiento_test_ingreso_review.document_id = "ingreso_doc_id_456"
    asiento_test_ingreso_review.document_link = "http://example.com/ingreso_doc_456"
    asiento_test_ingreso_review.needs_manual_review = True
    asiento_test_ingreso_review.review_reason = "Descuadre detectado y cliente dudoso."

    setattr(asiento_test_ingreso_review, 'cliente_nombre', "Cliente YYYY")
    setattr(asiento_test_ingreso_review, 'cliente_nif', "A87654321")
    setattr(asiento_test_ingreso_review, 'base_imponible', Decimal("2000.00"))
    setattr(asiento_test_ingreso_review, 'iva_type', "General (21%)")
    setattr(asiento_test_ingreso_review, 'iva_cuota', Decimal("420.00"))
    setattr(asiento_test_ingreso_review, 'total_factura', Decimal("2420.00"))

    asiento_test_ingreso_review.add_apunte("705", asiento_test_ingreso_review.concepto_general, haber=Decimal("2000.00"))
    asiento_test_ingreso_review.add_apunte("477.21", asiento_test_ingreso_review.concepto_general, haber=Decimal("420.00"))
    asiento_test_ingreso_review.add_apunte("430CLIENTY", asiento_test_ingreso_review.concepto_general, debe=Decimal("2400.00")) # Intentionally wrong for review

    # Test writing the asientos
    logger.info("\n--- Testing write_asiento_to_sheet for Gasto ---")
    success_gasto = write_asiento_to_sheet(asiento_test_gasto)
    if success_gasto:
        logger.info("Asiento de Gasto escrito correctamente (o sin errores).")
    else:
        logger.error("Fallo al escribir asiento de Gasto.")

    logger.info("\n--- Testing write_asiento_to_sheet for Ingreso (con revisión) ---")
    success_ingreso = write_asiento_to_sheet(asiento_test_ingreso_review)
    if success_ingreso:
        logger.info("Asiento de Ingreso (con revisión) escrito correctamente (o sin errores).")
    else:
        logger.error("Fallo al escribir asiento de Ingreso (con revisión).")

    logger.info("\n--- Sheet Writer Test Finished ---")
    logger.info(f"Please check your Google Sheet: https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}")
    logger.info(f"Look for a sheet named '{TARGET_SHEET_NAME}' with the appended data.")

# Ensure current_config is loaded at module level if this file is imported elsewhere
import os
if not SPREADSHEET_ID and 'current_config' in globals() and not current_config.OUTPUT_SHEET_ID :
    project_root_env = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '.env')
    if os.path.exists(project_root_env):
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=project_root_env, override=True)
        from config import settings
        current_config = settings.get_config()
        SPREADSHEET_ID = current_config.OUTPUT_SHEET_ID
    if not SPREADSHEET_ID:
         logger.warning("sheet_writer.main: OUTPUT_SHEET_ID is not set after attempting .env load. Sheet writing may fail.")
