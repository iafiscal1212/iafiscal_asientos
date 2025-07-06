import os
import logging
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build, Resource
from googleapiclient.errors import HttpError
from typing import List, Dict, Any, Optional

from config.settings import current_config

logger = logging.getLogger(__name__)

SCOPES_SHEETS = ['https://www.googleapis.com/auth/spreadsheets']

# Cache the service object
_sheets_service: Optional[Resource] = None

def get_sheets_service() -> Optional[Resource]:
    """
    Authenticates and returns a Google Sheets service object using service account credentials.
    Caches the service object for reuse.
    """
    global _sheets_service
    if _sheets_service:
        return _sheets_service

    try:
        creds_path_from_config = current_config.GOOGLE_APPLICATION_CREDENTIALS
        # Ensure the path is absolute or correctly relative to the project root
        # Assuming config path is relative to project root if not absolute.
        # The project root is two levels up from this file's directory (iafiscal_asientos_google/sheet_writer/utils.py)
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

        if os.path.isabs(creds_path_from_config):
            creds_path = creds_path_from_config
        else:
            creds_path = os.path.join(project_root, creds_path_from_config)

        if not os.path.exists(creds_path):
            logger.error(f"Google Sheets API credentials file not found at {creds_path}. "
                         "Ensure GOOGLE_APPLICATION_CREDENTIALS is set correctly in .env "
                         "and the file exists.")
            return None

        creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES_SHEETS)
        service = build('sheets', 'v4', credentials=creds)
        _sheets_service = service
        logger.info("Google Sheets service initialized successfully.")
        return service
    except Exception as e:
        logger.error(f"Error building Google Sheets service: {e}", exc_info=True)
        return None


def append_rows_to_sheet(spreadsheet_id: str,
                         sheet_name_or_range: str, # e.g., "Sheet1" or "Sheet1!A1"
                         values: List[List[Any]],
                         value_input_option: str = "USER_ENTERED" # Or "RAW"
                         ) -> Optional[Dict[str, Any]]:
    """
    Appends rows of data to a Google Sheet.

    Args:
        spreadsheet_id (str): The ID of the Google Spreadsheet.
        sheet_name_or_range (str): The name of the sheet (e.g., "Asientos") or a specific range (e.g., "Asientos!A1").
                                   If only sheet name, appends after the last row with data.
        values (List[List[Any]]): A list of rows, where each row is a list of cell values.
        value_input_option (str): How the input data should be interpreted ("USER_ENTERED" or "RAW").

    Returns:
        Optional[Dict[str, Any]]: The API response upon success, or None if an error occurs.
    """
    service = get_sheets_service()
    if not service:
        logger.error("Cannot append rows: Google Sheets service is not available.")
        return None

    if not spreadsheet_id:
        logger.error("Cannot append rows: Spreadsheet ID is not provided or configured.")
        return None

    if not values:
        logger.info("No values provided to append to the sheet.")
        return {"updates": {"updatedCells": 0}} # Mimic API response for no-op

    try:
        body = {
            'values': values
        }
        # If just sheet name is given, it appends. If range like "Sheet1!A1" is given, it starts writing there.
        # To ensure it appends to the first empty row of a sheet, just use the sheet name.
        target_range = sheet_name_or_range

        result = service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=target_range, # e.g., "Sheet1" or "MySheet!A1"
            valueInputOption=value_input_option, # How the input data should be interpreted
            insertDataOption="INSERT_ROWS", # Inserts new rows for the data
            body=body
        ).execute()

        logger.info(f"{result.get('updates').get('updatedCells')} cells appended to sheet '{sheet_name_or_range}'.")
        return result
    except HttpError as error:
        logger.error(f"An API error occurred while appending rows to sheet '{sheet_name_or_range}': {error}", exc_info=True)
        # Detailed error information
        error_details = error.resp.get('content', '{}')
        logger.error(f"Error details: {error_details}")
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred while appending rows: {e}", exc_info=True)
        return None


def ensure_header_row(spreadsheet_id: str, sheet_name: str, header_columns: List[str]) -> bool:
    """
    Checks if the sheet has a header row matching `header_columns`.
    If the sheet is empty or header is different, it writes/overwrites the header.

    Args:
        spreadsheet_id (str): The ID of the Google Spreadsheet.
        sheet_name (str): The name of the sheet.
        header_columns (List[str]): The list of column names for the header.

    Returns:
        bool: True if header is ensured (exists or was written), False otherwise.
    """
    service = get_sheets_service()
    if not service:
        logger.error("Cannot ensure header row: Google Sheets service is not available.")
        return False

    if not spreadsheet_id:
        logger.error("Cannot ensure header row: Spreadsheet ID is not provided or configured.")
        return False

    try:
        # Get the first row of the sheet
        range_to_get = f"{sheet_name}!1:1"
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=range_to_get
        ).execute()

        existing_header = result.get('values', [[]])[0] # Get first row, default to empty list if no values

        if existing_header == header_columns:
            logger.info(f"Header row in sheet '{sheet_name}' is already correct.")
            return True
        else:
            logger.info(f"Header row in sheet '{sheet_name}' is missing or incorrect. Existing: {existing_header}. Writing new header.")

            # If sheet is not empty and header is wrong, this will overwrite first row.
            # If sheet is empty, this writes to the first row.
            range_to_write = f"{sheet_name}!A1" # Write starting at A1
            body = {'values': [header_columns]}
            update_result = service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=range_to_write,
                valueInputOption="USER_ENTERED", # or RAW
                body=body
            ).execute()
            logger.info(f"Header row written to sheet '{sheet_name}'. Cells updated: {update_result.get('updatedCells')}")
            return True

    except HttpError as error:
        # If the error is "Requested entity was not found", it might mean the sheet itself doesn't exist.
        # Or if range is invalid because sheet is empty (though get should return empty values for that).
        if error.resp.status == 400 and "Unable to parse range" in str(error):
            # This can happen if sheet is completely empty or doesn't exist.
            # Let's try to write the header directly, assuming the sheet exists or will be created by Sheets API if it's smart.
            # A better approach for non-existent sheet is to use batchUpdate to add it first.
            # For now, assuming sheet exists.
            logger.info(f"Sheet '{sheet_name}' might be empty or range unparsable. Attempting to write header directly.")
            try:
                range_to_write = f"{sheet_name}!A1"
                body = {'values': [header_columns]}
                update_result = service.spreadsheets().values().update(
                    spreadsheetId=spreadsheet_id,
                    range=range_to_write,
                    valueInputOption="USER_ENTERED",
                    body=body
                ).execute()
                logger.info(f"Header row written to (possibly initially empty) sheet '{sheet_name}'. Cells updated: {update_result.get('updatedCells')}")
                return True
            except HttpError as write_error:
                 logger.error(f"API error writing header to sheet '{sheet_name}' after initial read failed: {write_error}", exc_info=True)
                 return False

        logger.error(f"An API error occurred while ensuring header for sheet '{sheet_name}': {error}", exc_info=True)
        return False
    except Exception as e:
        logger.error(f"An unexpected error occurred while ensuring header: {e}", exc_info=True)
        return False


if __name__ == '__main__':
    # Example Usage & Testing
    # Prerequisites for this test:
    # 1. .env file in project root with:
    #    GOOGLE_APPLICATION_CREDENTIALS="path/to/your/credentials.json"
    #    OUTPUT_SHEET_ID="your_test_spreadsheet_id_here" (Create a blank Google Sheet and get its ID from URL)
    # 2. The service account associated with credentials.json must have editor access to this test spreadsheet.

    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # Load .env from project root to get current_config populated
    project_root_env = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '.env')
    if os.path.exists(project_root_env):
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=project_root_env, override=True)
        logger.info(f"Loaded .env from {project_root_env} for sheet_writer.utils testing.")
        # Reload current_config if it was imported before dotenv load
        from config import settings
        settings.current_config = settings.get_config() # Re-initialize current_config
        global current_config # Make sure current_config in this module is updated
        current_config = settings.current_config
    else:
        logger.error(f".env file not found at {project_root_env}. Cannot run tests that rely on OUTPUT_SHEET_ID.")
        exit(1)

    TEST_SPREADSHEET_ID = current_config.OUTPUT_SHEET_ID
    TEST_SHEET_NAME = "TestSheet_Utils" # A sheet name for testing

    if not TEST_SPREADSHEET_ID:
        logger.error("OUTPUT_SHEET_ID is not set in your .env file. Please set it to a test Google Sheet ID.")
        exit(1)

    logger.info(f"--- Testing Google Sheets Utilities with Spreadsheet ID: {TEST_SPREADSHEET_ID} ---")

    # 1. Test get_sheets_service()
    service = get_sheets_service()
    if service:
        logger.info("Successfully obtained Google Sheets service.")
    else:
        logger.error("Failed to obtain Google Sheets service. Aborting further tests.")
        exit(1)

    # 2. Test ensure_header_row()
    test_headers = ["ID", "Timestamp", "Descripción", "Valor"]
    logger.info(f"\n--- Testing ensure_header_row for sheet '{TEST_SHEET_NAME}' ---")
    header_ok = ensure_header_row(TEST_SPREADSHEET_ID, TEST_SHEET_NAME, test_headers)
    if header_ok:
        logger.info("ensure_header_row test successful (or header already existed).")
    else:
        logger.error("ensure_header_row test failed.")
        # Note: If the sheet TEST_SHEET_NAME doesn't exist, this will likely fail.
        # A robust version would create the sheet if not found using batchUpdate.
        # For now, assume the sheet exists or can be manually created for testing.
        logger.warning(f"If ensure_header_row failed, ensure sheet '{TEST_SHEET_NAME}' exists in spreadsheet '{TEST_SPREADSHEET_ID}'.")


    # 3. Test append_rows_to_sheet()
    logger.info(f"\n--- Testing append_rows_to_sheet for sheet '{TEST_SHEET_NAME}' ---")
    from datetime import datetime as dt # For timestamp
    rows_to_append = [
        ["ID001", dt.now().isoformat(), "Primer evento de prueba", 100.50],
        ["ID002", dt.now().isoformat(), "Segundo evento de prueba con comas, y puntos.", 250.75],
        ["ID003", dt.now().isoformat(), "Tercer evento; con punto y coma", 300.00]
    ]
    # Values must be simple types (str, number, bool) for Sheets API unless "RAW" is used carefully.
    # datetime objects need to be formatted as strings.

    append_result = append_rows_to_sheet(TEST_SPREADSHEET_ID, TEST_SHEET_NAME, rows_to_append)
    if append_result:
        logger.info(f"append_rows_to_sheet test successful. Response: {append_result}")
    else:
        logger.error("append_rows_to_sheet test failed.")

    # Test appending to a specific range (will overwrite if data exists there)
    # logger.info(f"\n--- Testing append_rows_to_sheet to a specific range (e.g., {TEST_SHEET_NAME}!A10) ---")
    # This usage of 'append' with a specific cell like A10 means it will start looking for the table from A10.
    # If you want to overwrite, use `update`. If you want to append after existing data in that range,
    # you'd typically just specify the sheet name.
    # For this example, let's assume we mean to append after all data in TEST_SHEET_NAME.
    # rows_to_append_again = [
    #     ["ID004", dt.now().isoformat(), "Cuarto evento", 50.00]
    # ]
    # append_result_again = append_rows_to_sheet(TEST_SPREADSHEET_ID, TEST_SHEET_NAME, rows_to_append_again)
    # if append_result_again:
    #     logger.info(f"Second append_rows_to_sheet test successful.")
    # else:
    #     logger.error("Second append_rows_to_sheet test failed.")

    logger.info("\n--- Google Sheets Utilities Test Finished ---")
    logger.info(f"Please check your Google Sheet: https://docs.google.com/spreadsheets/d/{TEST_SPREADSHEET_ID}")
    logger.info(f"Look for a sheet named '{TEST_SHEET_NAME}' with the appended data.")
