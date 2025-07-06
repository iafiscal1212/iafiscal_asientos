import logging
import os
from datetime import datetime
from typing import Optional, List, Dict, Any

from config.settings import current_config
from .utils import (
    read_data_from_google_sheet,
    generate_contasol_csv_rows,
    write_contasol_csv_file
)
# Assuming sheet_writer.main.TARGET_SHEET_NAME is the name of the sheet to read from
from sheet_writer.main import TARGET_SHEET_NAME as DEFAULT_SOURCE_SHEET_NAME

logger = logging.getLogger(__name__)

# Default directory for exports, relative to project root
DEFAULT_EXPORT_SUBDIR = "exports"

def export_data_to_contasol_csv(
        cliente: str,
        mes_anio: str, # Expected format e.g., "YYYYMM" or "MMYYYY" or a date object
        spreadsheet_id: Optional[str] = None,
        source_sheet_name: Optional[str] = None,
        export_base_dir: Optional[str] = None
    ) -> Optional[str]:
    """
    Orchestrates the export of accounting data to a Contasol-compatible CSV file.
    Reads data from the specified Google Sheet (typically written by sheet_writer).
    Filters data for the given client and month/year (if applicable - current implementation reads all).
    Formats and writes the CSV file to the /exports/{cliente}_{mes}.csv path.

    Args:
        cliente (str): Client identifier, used for the output filename.
        mes_anio (str): Month and year string (e.g., "202311" for Nov 2023) for the filename.
                        Also used for filtering data if data contains multiple periods.
        spreadsheet_id (Optional[str]): The Google Spreadsheet ID to read from.
                                        Defaults to `current_config.OUTPUT_SHEET_ID`.
        source_sheet_name (Optional[str]): The name of the sheet to read data from.
                                           Defaults to `DEFAULT_SOURCE_SHEET_NAME`.
        export_base_dir (Optional[str]): Base directory for placing the exported CSV.
                                         Defaults to project_root/exports.

    Returns:
        Optional[str]: The full path to the generated CSV file if successful, else None.
    """
    logger.info(f"Starting Contasol CSV export for cliente '{cliente}', mes/año '{mes_anio}'.")

    # Determine configuration values
    sid = spreadsheet_id or current_config.OUTPUT_SHEET_ID
    sheet_name = source_sheet_name or DEFAULT_SOURCE_SHEET_NAME

    if not sid:
        logger.error("Spreadsheet ID for data source is not configured. Cannot export.")
        return None

    # 1. Read data from Google Sheets
    logger.info(f"Reading data from Spreadsheet ID '{sid}', Sheet '{sheet_name}'...")
    sheet_data = read_data_from_google_sheet(sid, sheet_name)

    if sheet_data is None: # Error during read
        logger.error("Failed to read data from Google Sheets. Export aborted.")
        return None
    if not sheet_data: # Sheet is empty
        logger.info("No data found in the source Google Sheet. Resulting CSV will be empty (header only).")
        # Continue to generate an empty CSV with header, as Contasol might expect this.

    # TODO: Filter sheet_data by `cliente` and `mes_anio` if the sheet contains multi-client/multi-period data.
    # This requires that the sheet_data (from sheet_writer) includes columns for client and a parseable date
    # that allows filtering by month/year.
    # For now, assuming all data in the sheet is for the target export.
    # Example filtering logic (if 'Asiento_Fecha' and a 'Cliente_ID' column existed in sheet_data):
    #
    # def filter_data(data, target_cliente_id, target_mes_anio_str):
    #     # target_mes_anio_str e.g. "202311"
    #     filtered = []
    #     for row in data:
    #         row_cliente = row.get('Cliente_ID_Asociado_Al_Documento') # Hypothetical column
    #         fecha_asiento_str = row.get('Asiento_Fecha') # YYYY-MM-DD
    #         if fecha_asiento_str:
    #             try:
    #                 dt_obj = datetime.strptime(fecha_asiento_str, "%Y-%m-%d")
    #                 row_mes_anio = dt_obj.strftime("%Y%m")
    #                 if (row_cliente == target_cliente_id or not target_cliente_id) and \
    #                    (row_mes_anio == target_mes_anio_str):
    #                     filtered.append(row)
    #             except ValueError:
    #                 continue # Skip rows with unparseable dates
    #     return filtered
    #
    # filtered_sheet_data = filter_data(sheet_data, cliente, mes_anio)
    # if not filtered_sheet_data:
    #    logger.info(f"No data found for cliente '{cliente}' and mes/año '{mes_anio}' after filtering.")
    #    # Proceed to generate empty CSV

    # For now, use all data read:
    data_to_export = sheet_data


    # 2. Transform data into Contasol CSV format
    logger.info("Generating Contasol CSV formatted rows...")
    contasol_rows = generate_contasol_csv_rows(data_to_export)

    if not contasol_rows and data_to_export: # Data existed but transformation yielded nothing (e.g. all rows had errors)
        logger.error("Failed to generate any Contasol compatible rows from the source data. Export aborted.")
        return None

    # 3. Determine export file path
    if export_base_dir is None:
        # Default to 'exports' directory in the project root
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        export_base_dir = os.path.join(project_root, DEFAULT_EXPORT_SUBDIR)

    # Ensure the base export directory exists
    try:
        os.makedirs(export_base_dir, exist_ok=True)
    except OSError as e:
        logger.error(f"Could not create export directory '{export_base_dir}': {e}. Export aborted.")
        return None

    # Format filename as per spec: /exports/{cliente}_{mes}.csv
    # Ensure mes_anio is just the month-year part for filename, e.g., 202311
    # The input `mes_anio` should already be in this format.
    sanitized_cliente_name = "".join(c if c.isalnum() or c in ('_', '-') else '_' for c in cliente) # Sanitize client name for filename
    csv_filename = f"{sanitized_cliente_name}_{mes_anio}.csv"
    full_export_path = os.path.join(export_base_dir, csv_filename)

    logger.info(f"Prepared {len(contasol_rows)} rows for export to: {full_export_path}")

    # 4. Write to CSV file
    write_success = write_contasol_csv_file(full_export_path, contasol_rows)

    if write_success:
        logger.info(f"Contasol CSV export successful. File saved to: {full_export_path}")
        return full_export_path
    else:
        logger.error("Failed to write Contasol CSV file.")
        return None


if __name__ == '__main__':
    # Example Usage & Testing
    # Prerequisites:
    # 1. .env file configured for Google Sheets API (credentials, OUTPUT_SHEET_ID).
    # 2. Data should exist in the Google Sheet specified by OUTPUT_SHEET_ID and
    #    sheet_writer.main.TARGET_SHEET_NAME (e.g., "IAFiscal_Asientos_Generados").
    #    This data should be in the format written by the sheet_writer module.

    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # Load .env from project root
    project_root_env = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '.env')
    if os.path.exists(project_root_env):
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=project_root_env, override=True)
        from config import settings # Ensure current_config is fresh
        settings.current_config = settings.get_config()
        global current_config
        current_config = settings.current_config
        logger.info(f"Loaded .env from {project_root_env} for exportador_contasol.main testing.")
    else:
        logger.error(f".env file not found at {project_root_env}. Cannot run tests effectively.")
        exit(1)

    if not current_config.OUTPUT_SHEET_ID:
        logger.error("OUTPUT_SHEET_ID is not set in .env. Cannot run export test.")
        exit(1)

    logger.info("--- Testing Contasol CSV Export Main Function ---")

    # Define parameters for the test export
    test_cliente_id = "ClientePruebaSA"
    # Use current month and year for testing, e.g., "202311"
    test_mes_anio_export = datetime.now().strftime("%Y%m")

    # Optional: specify a different export directory for testing
    # test_export_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "temp_exports_test")
    test_export_dir = None # Use default (project_root/exports)

    exported_file_path = export_data_to_contasol_csv(
        cliente=test_cliente_id,
        mes_anio=test_mes_anio_export,
        # spreadsheet_id=current_config.OUTPUT_SHEET_ID, # Uses default from config
        # source_sheet_name=DEFAULT_SOURCE_SHEET_NAME, # Uses default
        export_base_dir=test_export_dir
    )

    if exported_file_path:
        logger.info(f"Test export successful. CSV file generated at: {exported_file_path}")
        logger.info("Please verify the contents of the CSV file, especially formatting and encoding.")
    else:
        logger.error("Test export failed. Check logs for details.")

    logger.info("\n--- Contasol CSV Export Main Test Finished ---")
