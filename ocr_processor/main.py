import os
import tempfile
import logging

# Project specific imports
from drive_listener.utils import get_drive_service, download_file as download_drive_file
from ocr_processor.utils import extract_text_from_image, extract_text_from_pdf, extract_data_from_excel
from config.settings import current_config # To get allowed mime types, though usually passed in

logger = logging.getLogger(__name__)

# Ensure a temporary directory exists for downloads
# This could also be configured via current_config if needed.
TEMP_DOWNLOAD_DIR = os.path.join(tempfile.gettempdir(), "iafiscal_downloads")
os.makedirs(TEMP_DOWNLOAD_DIR, exist_ok=True)


def process_document_from_drive(file_id: str, file_name: str, mime_type: str, drive_service=None) -> str:
    """
    Downloads a file from Google Drive and extracts text/data from it based on its MIME type.

    Args:
        file_id (str): The Google Drive file ID.
        file_name (str): The name of the file (used for saving locally).
        mime_type (str): The MIME type of the file.
        drive_service: Optional pre-initialized Google Drive service. If None, it will be created.

    Returns:
        str: The extracted text or structured data representation as a string.
             Returns an empty string or raises an error if processing fails.
    """
    logger.info(f"Starting processing for Drive file: {file_name} (ID: {file_id}, MIME: {mime_type})")

    if drive_service is None:
        try:
            drive_service = get_drive_service()
        except Exception as e:
            logger.error(f"Failed to get Google Drive service: {e}")
            raise  # Or return error status

    # Sanitize file_name to prevent path traversal or invalid characters if used directly in path
    safe_file_name = os.path.basename(file_name)
    local_file_path = os.path.join(TEMP_DOWNLOAD_DIR, f"{file_id}_{safe_file_name}")

    try:
        logger.info(f"Downloading {file_name} to {local_file_path}...")
        actual_download_path = download_drive_file(drive_service, file_id, local_file_path)
        if not actual_download_path:
            logger.error(f"Failed to download file {file_name} (ID: {file_id}).")
            # Consider raising a specific error here
            raise Exception(f"Download failed for {file_name}")

        logger.info(f"File downloaded successfully: {actual_download_path}")

        extracted_text = extract_text_from_file(actual_download_path, mime_type)
        return extracted_text

    except Exception as e:
        logger.error(f"Error processing document {file_name} (ID: {file_id}): {e}", exc_info=True)
        # Re-raise the exception to be handled by the caller (e.g., the listener)
        # The listener can then mark the file with an error status in the database.
        raise
    finally:
        # Clean up the downloaded file
        if os.path.exists(local_file_path):
            try:
                os.remove(local_file_path)
                logger.info(f"Cleaned up temporary file: {local_file_path}")
            except OSError as e:
                logger.warning(f"Could not remove temporary file {local_file_path}: {e}")


def extract_text_from_file(file_path: str, mime_type: str) -> str:
    """
    Extracts text/data from a local file based on its MIME type.
    This function is called by `process_document_from_drive` after download,
    but can also be used directly if files are sourced locally.

    Args:
        file_path (str): The local path to the file.
        mime_type (str): The MIME type of the file.

    Returns:
        str: The extracted text or structured data representation as a string.
    """
    logger.info(f"Extracting text from local file: {file_path} (MIME: {mime_type})")
    extracted_text = ""

    # Determine the file extension/type from MIME type for dispatching
    # Using current_config.ALLOWED_MIMETYPES which maps mime_type to simple extensions
    file_ext = current_config.ALLOWED_MIMETYPES.get(mime_type)

    if file_ext is None:
        logger.warning(f"Unsupported MIME type: {mime_type} for file {file_path}. Cannot determine processing method.")
        # Fallback or raise error? For now, try to infer if possible, or skip.
        # Could try to guess from file_path extension if mime_type is generic like application/octet-stream
        _, ext_from_path = os.path.splitext(file_path)
        if ext_from_path:
            file_ext = ext_from_path.lower().lstrip('.')
            logger.info(f"Inferred file extension '{file_ext}' from path for {file_path}")
        else:
            raise ValueError(f"Unsupported MIME type '{mime_type}' and no file extension for {file_path}")


    if file_ext in ['pdf']:
        extracted_text = extract_text_from_pdf(file_path)
    elif file_ext in ['jpg', 'jpeg', 'png', 'tiff', 'bmp', 'gif']: # Common image types
        extracted_text = extract_text_from_image(file_path)
    elif file_ext in ['xlsx', 'xls']:
        extracted_text = extract_data_from_excel(file_path)
    else:
        logger.warning(f"MIME type {mime_type} (ext: {file_ext}) is allowed but no specific extractor configured for file: {file_path}")
        # Potentially raise an error or return empty string if no handler
        raise NotImplementedError(f"No extractor implemented for MIME type {mime_type} (ext: {file_ext})")

    if not extracted_text:
        logger.warning(f"No text extracted from {file_path} (MIME: {mime_type}). The file might be empty, purely graphical, or an issue occurred.")
    else:
        logger.info(f"Successfully extracted content from {file_path}. Length: {len(extracted_text)} characters.")

    return extracted_text


if __name__ == '__main__':
    # This main block is for testing the ocr_processor module directly.
    # It requires:
    # 1. A .env file configured with GOOGLE_APPLICATION_CREDENTIALS and a test DRIVE_FILE_ID,
    #    DRIVE_FILE_NAME, DRIVE_FILE_MIME_TYPE.
    # 2. The specified file must exist in Google Drive and be accessible by the service account.
    # 3. Tesseract OCR installed and configured if testing PDFs/images.
    # 4. Relevant Python libraries (PyMuPDF, Pillow, openpyxl, pandas).

    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger.info("Testing OCR Processor Main...")

    # Attempt to load .env if not already done (e.g. by a calling script)
    env_path_root = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '.env') # Assuming this file is in ocr_processor, two levels down from project root
    env_path_proj = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env') # one level down

    actual_env_path = None
    if os.path.exists(env_path_proj): # iafiscal_asientos_google/.env
        actual_env_path = env_path_proj
    elif os.path.exists(env_path_root): # if script is run from project root
        actual_env_path = env_path_root

    if actual_env_path:
        logger.info(f"Loading .env file from: {actual_env_path}")
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=actual_env_path, override=True)
    else:
        logger.warning(".env file not found in typical locations. Ensure environment variables are set.")

    # Test with environment variables for a specific file in Google Drive
    # These should be set in your .env file for testing purposes
    TEST_DRIVE_FILE_ID = os.getenv("TEST_DRIVE_FILE_ID")
    TEST_DRIVE_FILE_NAME = os.getenv("TEST_DRIVE_FILE_NAME", "test_file_from_drive") # Default name if not set
    TEST_DRIVE_FILE_MIME_TYPE = os.getenv("TEST_DRIVE_FILE_MIME_TYPE")

    if TEST_DRIVE_FILE_ID and TEST_DRIVE_FILE_MIME_TYPE:
        logger.info(f"Attempting to process file from Google Drive: ID={TEST_DRIVE_FILE_ID}, Name={TEST_DRIVE_FILE_NAME}, MIME={TEST_DRIVE_FILE_MIME_TYPE}")
        try:
            extracted_content = process_document_from_drive(
                file_id=TEST_DRIVE_FILE_ID,
                file_name=TEST_DRIVE_FILE_NAME,
                mime_type=TEST_DRIVE_FILE_MIME_TYPE
            )
            logger.info(f"Successfully processed Drive file. Extracted content snippet (first 500 chars):\n"
                        f"{extracted_content[:500]}")

            # Example: Save extracted text to a file for review
            output_dir = "temp_ocr_output"
            os.makedirs(output_dir, exist_ok=True)
            output_file_path = os.path.join(output_dir, f"{TEST_DRIVE_FILE_ID}_{os.path.basename(TEST_DRIVE_FILE_NAME)}.txt")
            with open(output_file_path, "w", encoding="utf-8") as f:
                f.write(extracted_content)
            logger.info(f"Full extracted content saved to: {output_file_path}")

        except Exception as e:
            logger.error(f"Test processing of Drive file failed: {e}", exc_info=True)
    else:
        logger.warning("TEST_DRIVE_FILE_ID or TEST_DRIVE_FILE_MIME_TYPE not set in environment. "
                       "Skipping Google Drive document processing test.")
        logger.info("To test Google Drive integration, set these in your .env file:\n"
                    "TEST_DRIVE_FILE_ID=your_file_id_on_google_drive\n"
                    "TEST_DRIVE_FILE_NAME=your_file_name_on_google_drive (optional, for logging)\n"
                    "TEST_DRIVE_FILE_MIME_TYPE=application/pdf # or image/jpeg, etc.")

    # You can also add tests for extract_text_from_file with local dummy files
    # similar to how it's done in ocr_processor/utils.py's main block.
    # This would require creating dummy files here or referencing those created by utils.
    logger.info("Testing local file extraction (using dummy files from ocr_processor.utils example)...")
    # Note: This assumes ocr_processor.utils created some files in 'temp_test_files_ocr'
    # This is not ideal for clean tests but works for a quick check.
    # A better way would be to create specific test files for this main.py test.

    # Create dummy files for testing local extraction if utils.py's main wasn't run
    test_utils_dir = os.path.join(os.path.dirname(__file__), "temp_test_files_ocr") # relative to this file
    if not os.path.exists(test_utils_dir):
         logger.info(f"Directory {test_utils_dir} not found, attempting to run utils.py to create test files.")
         try:
            # This is a bit of a hack to ensure test files exist.
            # In a real test suite, test files would be fixtures.
            from ocr_processor import utils as ocr_utils_module
            # Calling main of utils if it exists and creates files
            if hasattr(ocr_utils_module, '__main_for_test_files__') or True: # Assume it creates files
                # ocr_utils_module.__main_for_test_files__() # if you add such a function
                # Or, replicate file creation here:
                os.makedirs(test_utils_dir, exist_ok=True)
                from PIL import Image, ImageDraw, ImageFont
                dummy_img_path = os.path.join(test_utils_dir, "dummy_image_main.png")
                img = Image.new('RGB', (200, 50), color = 'white')
                draw = ImageDraw.Draw(img)
                try: font = ImageFont.truetype("arial.ttf", 15)
                except IOError: font = ImageFont.load_default()
                draw.text((10, 10), "Test OCR Main", fill='black', font=font)
                img.save(dummy_img_path)
                logger.info(f"Created dummy image for local test: {dummy_img_path}")

                # Test local image extraction
                try:
                    text_from_local_image = extract_text_from_file(dummy_img_path, "image/png")
                    logger.info(f"Text from local dummy image ('{dummy_img_path}'): '{text_from_local_image}'")
                except Exception as e:
                    logger.error(f"Error testing local image extraction: {e}")

         except Exception as e:
            logger.error(f"Could not create/run utils for test files: {e}")


    logger.info("OCR Processor Main test finished.")
