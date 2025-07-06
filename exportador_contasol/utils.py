import logging
import csv
import os
from datetime import datetime
from typing import List, Dict, Any, Optional

from config.settings import current_config
# To read data from Google Sheets for export
from sheet_writer.utils import get_sheets_service # Reusing the sheets utility

logger = logging.getLogger(__name__)

# Contasol specific configurations (can be expanded or moved to current_config)
CONTASOL_DATE_FORMAT = "%d%m%Y" # DDMMYYYY
CONTASOL_CSV_SEPARATOR = current_config.CONTASOL_CSV_SEPARATOR # Usually ";"
CONTASOL_ENCODING = current_config.CONTASOL_ENCODING # Usually "utf-8" or "utf-8-sig" or "latin1" for older systems

# Define the exact columns required by Contasol import format.
# Based on project spec: [fecha, diario, cuenta, concepto, debe, haber]
# These must be in the correct order.
CONTASOL_CSV_HEADER = ["fecha", "diario", "cuenta", "concepto", "debe", "haber"]


def format_amount_for_contasol(amount: Any) -> str:
    """
    Formats a numeric amount (Decimal, float, or string) into the string representation
    expected by Contasol (e.g., "1234,56" with comma as decimal separator, no thousand separator).
    """
    if amount is None or amount == "":
        return "0,00" # Contasol might expect "0,00" for zero amounts

    try:
        # Convert to string, then replace dot with comma if it's the decimal separator
        # Assuming amounts are already Decimal or valid float strings from sheet/asiento
        s_amount = str(amount)
        # Standardize to use dot as decimal separator first if it's not already
        # (e.g. if it comes as "1.234,56" - this is tricky, parse_amount in information_extractor is better)
        # For now, assume amount is a standard Decimal or float where str() works as expected (e.g. "123.45")

        # Ensure it's a number that can be formatted. If it's already formatted with comma, it might fail float().
        # Let's assume the input `amount` is a Decimal object or a string that float() can parse.
        num_amount = float(amount) # Convert to float for formatting

        # Format with 2 decimal places, using comma as decimal separator
        # "{:.2f}" will use dot. We need to replace it.
        formatted_str = "{:.2f}".format(num_amount).replace('.', ',')
        return formatted_str
    except ValueError:
        logger.warning(f"Could not format amount '{amount}' for Contasol. Returning as is or default.")
        # Fallback: try to return string version, or a default like "0,00"
        if isinstance(amount, str):
            return amount.replace('.', ',') # Simple replacement if already string
        return "0,00"


def read_data_from_google_sheet(spreadsheet_id: str, sheet_name: str) -> Optional[List[Dict[str, Any]]]:
    """
    Reads all data from a specified Google Sheet and returns it as a list of dictionaries.
    Assumes the first row is the header.
    """
    service = get_sheets_service()
    if not service:
        logger.error("Cannot read from sheet: Google Sheets service is not available.")
        return None
    if not spreadsheet_id:
        logger.error("Cannot read from sheet: Spreadsheet ID is not configured.")
        return None

    try:
        # Construct the range to get all data from the sheet
        # e.g., "SheetName!A:Z" to get all columns, or just "SheetName" for all data
        range_name = f"{sheet_name}"
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=range_name,
            valueRenderOption='UNFORMATTED_VALUE' # Get raw numbers, not formatted strings
        ).execute()

        values = result.get('values', [])

        if not values:
            logger.info(f"Sheet '{sheet_name}' is empty or no data found.")
            return []

        header = values[0]
        data_rows = values[1:]

        list_of_dicts = [dict(zip(header, row)) for row in data_rows]
        logger.info(f"Successfully read {len(list_of_dicts)} rows from sheet '{sheet_name}'.")
        return list_of_dicts

    except HttpError as error:
        logger.error(f"An API error occurred while reading sheet '{sheet_name}': {error}", exc_info=True)
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred while reading sheet: {e}", exc_info=True)
        return None


def generate_contasol_csv_rows(sheet_data: List[Dict[str, Any]]) -> List[List[str]]:
    """
    Transforms data (assumed to be from the Google Sheet written by sheet_writer)
    into the specific row format required for Contasol CSV import.

    Args:
        sheet_data: A list of dictionaries, where each dictionary represents a row
                    from the Google Sheet (i.e., an apunte with asiento context).
                    Expected keys are from `sheet_writer.main.SHEET_HEADER_COLUMNS`.

    Returns:
        List[List[str]]: A list of rows, where each row is a list of strings formatted
                         for Contasol CSV.
    """
    contasol_rows = []

    # Check if sheet_data is empty or not in the expected format
    if not sheet_data or not isinstance(sheet_data, list) or not all(isinstance(row, dict) for row in sheet_data):
        logger.warning("Sheet data is empty or not in the expected list of dicts format. Cannot generate Contasol CSV rows.")
        return []

    for row_dict in sheet_data:
        # Extract and format data for each Contasol column
        try:
            # 1. Fecha (DDMMYYYY)
            fecha_asiento_str = row_dict.get("Asiento_Fecha") # Expected YYYY-MM-DD
            if fecha_asiento_str:
                dt_obj = datetime.strptime(str(fecha_asiento_str), "%Y-%m-%d")
                fecha_contasol = dt_obj.strftime(CONTASOL_DATE_FORMAT)
            else:
                logger.warning(f"Missing 'Asiento_Fecha' in row: {row_dict}. Skipping row for Contasol export.")
                continue # Skip row if essential data like date is missing

            # 2. Diario (Contasol diary code)
            diario_code = str(row_dict.get("Asiento_Diario", "1")) # Default to '1' if not found

            # 3. Cuenta (Account number)
            cuenta = str(row_dict.get("Apunte_Cuenta", "")).strip()
            if not cuenta:
                logger.warning(f"Missing 'Apunte_Cuenta' in row: {row_dict}. Skipping row for Contasol export.")
                continue

            # 4. Concepto (Description for the line)
            # Contasol concept length is usually limited (e.g., 38 or 40 chars).
            # The Asiento_Concepto or Apunte_Concepto should already be formatted with this in mind.
            # Let's prioritize Apunte_Concepto if available, else Asiento_Concepto.
            concepto = str(row_dict.get("Apunte_Concepto") or row_dict.get("Asiento_Concepto", "")).strip()
            MAX_CONTASOL_CONCEPTO_LEN = 38 # Make this configurable if needed
            if len(concepto) > MAX_CONTASOL_CONCEPTO_LEN:
                concepto = concepto[:MAX_CONTASOL_CONCEPTO_LEN]

            # 5. Debe (Debit amount, formatted e.g., "1234,56")
            debe_val = row_dict.get("Apunte_Debe") # Should be Decimal or string convertible to float
            debe_contasol = format_amount_for_contasol(debe_val) if (debe_val not in [None, ""]) else "0,00"

            # 6. Haber (Credit amount, formatted)
            haber_val = row_dict.get("Apunte_Haber")
            haber_contasol = format_amount_for_contasol(haber_val) if (haber_val not in [None, ""]) else "0,00"

            # Ensure that for each line, either debe or haber is non-zero, but not both (usually)
            # Or at least, if both are "0,00", Contasol might reject it.
            if debe_contasol == "0,00" and haber_contasol == "0,00":
                logger.warning(f"Row for account {cuenta} has 0.00 for both Debe and Haber. Contasol might ignore/reject. Concepto: '{concepto}'")
                # Depending on Contasol behavior, might skip these rows or let them pass.
                # For now, let them pass.

            contasol_rows.append([
                fecha_contasol,
                diario_code,
                cuenta,
                concepto,
                debe_contasol,
                haber_contasol
            ])
        except ValueError as ve: # Catch errors during date parsing or other conversions
            logger.error(f"ValueError processing row for Contasol: {row_dict}. Error: {ve}. Skipping row.")
            continue
        except Exception as e:
            logger.error(f"Unexpected error processing row for Contasol: {row_dict}. Error: {e}. Skipping row.", exc_info=True)
            continue

    return contasol_rows


def write_contasol_csv_file(filepath: str, contasol_rows: List[List[str]]) -> bool:
    """
    Writes the prepared Contasol data to a CSV file.

    Args:
        filepath (str): The full path to the CSV file to be created.
        contasol_rows (List[List[str]]): The data rows to write (excluding header).

    Returns:
        bool: True if writing was successful, False otherwise.
    """
    if not filepath:
        logger.error("No filepath provided for Contasol CSV export.")
        return False

    if not contasol_rows:
        logger.info("No data rows to write to Contasol CSV file.")
        # Create an empty file with header, or just return true?
        # Contasol might expect a header even if no data.
        # Let's ensure directory exists and write header.
        # os.makedirs(os.path.dirname(filepath), exist_ok=True) # Done by caller usually
        # Fall through to write header only.
        pass # Will write header only if contasol_rows is empty

    try:
        # Ensure the directory exists
        os.makedirs(os.path.dirname(filepath), exist_ok=True)

        with open(filepath, 'w', newline='', encoding=CONTASOL_ENCODING) as csvfile:
            writer = csv.writer(csvfile, delimiter=CONTASOL_CSV_SEPARATOR, quoting=csv.QUOTE_MINIMAL) # QUOTE_MINIMAL or QUOTE_NONE

            # Write header
            writer.writerow(CONTASOL_CSV_HEADER)

            # Write data rows
            if contasol_rows:
                writer.writerows(contasol_rows)

        logger.info(f"Successfully wrote {len(contasol_rows)} data rows to Contasol CSV: {filepath}")
        return True
    except IOError as ioe:
        logger.error(f"IOError writing Contasol CSV file to {filepath}: {ioe}", exc_info=True)
        return False
    except Exception as e:
        logger.error(f"Unexpected error writing Contasol CSV file to {filepath}: {e}", exc_info=True)
        return False


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # Prerequisites for this test:
    # 1. .env file in project root with GOOGLE_APPLICATION_CREDENTIALS and OUTPUT_SHEET_ID.
    # 2. The OUTPUT_SHEET_ID sheet should have data written by sheet_writer.main.py's test,
    #    in a sheet named TARGET_SHEET_NAME (e.g., "IAFiscal_Asientos_Generados").
    # 3. The service account must have read access to this sheet.

    project_root_env = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '.env')
    if os.path.exists(project_root_env):
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=project_root_env, override=True)
        from config import settings
        settings.current_config = settings.get_config() # Re-initialize
        global current_config # Update module-level current_config
        current_config = settings.current_config
        logger.info(f"Loaded .env from {project_root_env} for exportador_contasol.utils testing.")
    else:
        logger.error(f".env file not found at {project_root_env}. Cannot run tests effectively.")
        exit(1)

    TEST_SPREADSHEET_ID_FOR_READ = current_config.OUTPUT_SHEET_ID
    # This should be the sheet name used by sheet_writer.main.py
    TEST_SHEET_NAME_FOR_READ = "IAFiscal_Asientos_Generados" # from sheet_writer.main.TARGET_SHEET_NAME

    if not TEST_SPREADSHEET_ID_FOR_READ:
        logger.error("OUTPUT_SHEET_ID is not set in .env. Cannot test reading from sheet.")
        exit(1)

    logger.info(f"--- Testing Contasol Export Utilities ---")
    logger.info(f"Reading from Spreadsheet ID: {TEST_SPREADSHEET_ID_FOR_READ}, Sheet: {TEST_SHEET_NAME_FOR_READ}")

    # 1. Test read_data_from_google_sheet()
    sheet_data = read_data_from_google_sheet(TEST_SPREADSHEET_ID_FOR_READ, TEST_SHEET_NAME_FOR_READ)

    if sheet_data is None:
        logger.error("Failed to read data from Google Sheet. Aborting further tests.")
        exit(1)

    if not sheet_data:
        logger.warning("No data found in the Google Sheet. CSV export will be empty (header only).")
        # Proceed to test empty CSV generation if desired.
    else:
        logger.info(f"Read {len(sheet_data)} rows from sheet. Sample first row: {sheet_data[0] if sheet_data else 'N/A'}")

    # 2. Test generate_contasol_csv_rows()
    contasol_export_rows = generate_contasol_csv_rows(sheet_data)
    if contasol_export_rows:
        logger.info(f"Generated {len(contasol_export_rows)} rows for Contasol CSV. Sample first export row: {contasol_export_rows[0] if contasol_export_rows else 'N/A'}")
    elif sheet_data: # Data was read, but nothing generated for Contasol
        logger.error("Failed to generate any Contasol CSV rows from the sheet data.")
    else: # No sheet data and no contasol rows
        logger.info("No Contasol CSV rows generated as there was no input sheet data.")


    # 3. Test write_contasol_csv_file()
    # Define a test export path (e.g., in project_root/exports/)
    export_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "exports")
    # Create a filename like /exports/{cliente}_{mes}.csv
    # For test, use fixed name.
    test_cliente = "TestCliente"
    test_mes = datetime.now().strftime("%Y%m") # e.g. 202311
    test_csv_filename = f"{test_cliente}_{test_mes}.csv"
    full_export_path = os.path.join(export_dir, test_csv_filename)

    logger.info(f"Attempting to write Contasol CSV to: {full_export_path}")

    # Ensure CONTASOL_CSV_SEPARATOR and CONTASOL_ENCODING are correctly set from config
    logger.info(f"Using CSV Separator: '{CONTASOL_CSV_SEPARATOR}', Encoding: '{CONTASOL_ENCODING}'")

    write_success = write_contasol_csv_file(full_export_path, contasol_export_rows)
    if write_success:
        logger.info(f"Contasol CSV file writing test successful. File at: {full_export_path}")
    else:
        logger.error(f"Contasol CSV file writing test failed.")

    logger.info("\n--- Contasol Export Utilities Test Finished ---")
