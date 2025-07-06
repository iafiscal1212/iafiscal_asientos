import os
import pytesseract
from PIL import Image, UnidentifiedImageError
import fitz # PyMuPDF for handling PDFs
import pandas as pd # For Excel file processing
import logging

from config.settings import current_config

logger = logging.getLogger(__name__)

# Configure Tesseract path if specified in config
if current_config.TESSERACT_CMD:
    pytesseract.pytesseract.tesseract_cmd = current_config.TESSERACT_CMD

def extract_text_from_image(image_path: str) -> str:
    """
    Extracts text from an image file using Pytesseract.
    Supported image types are those that PIL.Image can open (JPG, PNG, etc.).
    """
    try:
        logger.info(f"Attempting OCR on image: {image_path}")
        text = pytesseract.image_to_string(Image.open(image_path), lang='spa') # Specify Spanish language
        logger.info(f"Successfully extracted text from {image_path} using OCR.")
        return text.strip()
    except UnidentifiedImageError:
        logger.error(f"Cannot identify image file: {image_path}. It might be corrupted or not a valid image.")
        raise
    except pytesseract.TesseractNotFoundError:
        logger.error("Tesseract is not installed or not found in your PATH. "
                     "Please install Tesseract and/or set TESSERACT_CMD in your .env file.")
        raise
    except Exception as e:
        logger.error(f"An error occurred during OCR processing for {image_path}: {e}")
        raise
    return ""

def extract_text_from_pdf(pdf_path: str) -> str:
    """
    Extracts text from a PDF file.
    It first tries to extract text directly (if it's a text-based PDF).
    If that yields little or no text, it falls back to OCRing the PDF pages as images.
    """
    text = ""
    try:
        logger.info(f"Opening PDF for text extraction: {pdf_path}")
        doc = fitz.open(pdf_path)
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            text += page.get_text("text")
        doc.close()

        text = text.strip()
        logger.info(f"Direct text extraction from PDF {pdf_path} yielded {len(text)} characters.")

        # If direct text extraction is insufficient (e.g., scanned PDF), try OCR
        # Heuristic: if less than 100 chars for a multi-page PDF or very few chars per page.
        # This threshold might need adjustment.
        if len(text) < 100 * len(doc) and len(text) < 500 : # Arbitrary threshold, adjust as needed
            logger.info(f"Direct text extraction from {pdf_path} seems insufficient. Attempting OCR fallback.")
            text_ocr = ""
            doc_ocr = fitz.open(pdf_path) # Re-open for image rendering
            for page_num in range(len(doc_ocr)):
                page = doc_ocr.load_page(page_num)
                # Render page to an image (pixmap)
                # Higher DPI can improve OCR quality but increases processing time
                pix = page.get_pixmap(dpi=300)
                img_bytes = pix.tobytes("png") # Get image bytes in PNG format

                # Use PIL to open image from bytes, then Pytesseract
                try:
                    pil_image = Image.open(io.BytesIO(img_bytes))
                    text_ocr += pytesseract.image_to_string(pil_image, lang='spa')
                except Exception as img_e:
                    logger.error(f"Error processing page {page_num+1} of {pdf_path} with OCR: {img_e}")
                    continue # Try next page
            doc_ocr.close()
            text_ocr = text_ocr.strip()
            logger.info(f"OCR fallback for PDF {pdf_path} yielded {len(text_ocr)} characters.")
            # Decide if OCR text is better (e.g. if it's significantly longer)
            if len(text_ocr) > len(text) + 100: # Add a buffer to prefer direct extraction if similar
                logger.info("Using OCR text for PDF as it's significantly more substantial.")
                text = text_ocr
            else:
                logger.info("Sticking with initially extracted direct text for PDF.")

        return text

    except pytesseract.TesseractNotFoundError:
        logger.error("Tesseract is not installed or not found in your PATH. "
                     "Needed for OCR fallback on PDF. Please install Tesseract or set TESSERACT_CMD.")
        # If Tesseract isn't found but we got some direct text, we might return that.
        # However, if the PDF was scanned, this text might be empty or gibberish.
        if text:
             logger.warning("Returning only directly extracted text as Tesseract is unavailable for OCR fallback.")
             return text
        raise # Re-raise if no text and tesseract missing for scanned PDF
    except Exception as e:
        logger.error(f"An error occurred during PDF text extraction for {pdf_path}: {e}")
        # If we have some text from direct extraction before OCR attempt, return it.
        if text:
            logger.warning(f"Returning partially extracted text due to error: {e}")
            return text
        raise
    return "" # Should be unreachable if exceptions are raised correctly

def extract_data_from_excel(excel_path: str) -> dict:
    """
    Extracts data from an Excel file (XLSX or XLS).
    The project description implies OCR for invoices, but Excel files might contain structured data.
    This function should be adapted based on the expected structure of Excel "invoices".
    For now, it will read all sheets and concatenate them, then return as a dictionary
    or a list of dictionaries (one per row). This is a generic approach.
    Specific parsing logic (e.g., finding "Concepto", "Total") would be needed for invoices.

    Returns:
        A dictionary where keys are sheet names and values are lists of row data (as dicts),
        or a more structured format if specific Excel layouts are known.
        For now, returns a list of strings, where each string is a concatenation of row values.
        This makes it somewhat similar to OCR text output for downstream processing.
    """
    try:
        logger.info(f"Processing Excel file: {excel_path}")
        xls = pd.ExcelFile(excel_path)
        all_text_parts = []
        for sheet_name in xls.sheet_names:
            df = xls.parse(sheet_name)
            # Convert entire sheet to string representations
            # This is a naive way to get "text" from Excel.
            # A more sophisticated approach would identify relevant columns/cells.
            df_str = df.to_string(index=False, header=True)
            all_text_parts.append(f"--- Sheet: {sheet_name} ---\n{df_str}")

            # Alternative: iterate rows and cells to build a text block
            # for index, row in df.iterrows():
            #     row_text = " ".join([str(cell) for cell in row if pd.notna(cell)])
            #     if row_text:
            #         all_text_parts.append(row_text)

        logger.info(f"Successfully extracted data from Excel sheets in {excel_path}.")
        # Return a single string block, similar to OCR, for now.
        # Downstream rule classification will need to parse this.
        return "\n\n".join(all_text_parts).strip()

    except FileNotFoundError:
        logger.error(f"Excel file not found: {excel_path}")
        raise
    except Exception as e:
        logger.error(f"An error occurred during Excel file processing for {excel_path}: {e}")
        raise
    return ""


if __name__ == '__main__':
    # Example Usage (requires test files and Tesseract installed)
    # Create dummy files for testing if they don't exist

    # Setup basic logging for testing this script directly
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    test_files_dir = "temp_test_files_ocr"
    os.makedirs(test_files_dir, exist_ok=True)

    # Dummy text file (not processed by these functions but for path testing)
    # dummy_txt_path = os.path.join(test_files_dir, "dummy.txt")
    # with open(dummy_txt_path, "w") as f:
    #     f.write("This is a test.")

    # Dummy image (Pillow will create a simple one if not available)
    dummy_img_path = os.path.join(test_files_dir, "dummy_image.png")
    try:
        img = Image.new('RGB', (600, 150), color = 'white')
        # Create a draw object
        from PIL import ImageDraw, ImageFont
        draw = ImageDraw.Draw(img)
        # Use a default font (Pillow may need a path to a .ttf file on some systems)
        try:
            font = ImageFont.truetype("arial.ttf", 40) # Try common font
        except IOError:
            font = ImageFont.load_default()
        draw.text((50, 50), "Hola, esto es una factura de prueba.", fill='black', font=font)
        img.save(dummy_img_path)
        logger.info(f"Created dummy image: {dummy_img_path}")
        text_from_image = extract_text_from_image(dummy_img_path)
        logger.info(f"Text from dummy image: '{text_from_image}'")
    except ImportError:
        logger.warning("Pillow is not fully installed with FreeType support, cannot create complex dummy image. Skipping image text extraction test.")
    except pytesseract.TesseractNotFoundError:
        logger.error("Tesseract not found. Skipping image text extraction test.")
    except Exception as e:
        logger.error(f"Error in image test: {e}")


    # Dummy PDF (PyMuPDF can create a simple one)
    dummy_pdf_path = os.path.join(test_files_dir, "dummy_pdf.pdf")
    try:
        doc = fitz.open() # New PDF
        page = doc.new_page()
        page.insert_text(fitz.Point(50, 72), "Concepto: Servicio de consultoría\nTotal: 100 EUR")
        doc.save(dummy_pdf_path)
        doc.close()
        logger.info(f"Created dummy PDF: {dummy_pdf_path}")
        text_from_pdf = extract_text_from_pdf(dummy_pdf_path)
        logger.info(f"Text from dummy PDF: '{text_from_pdf}'")
    except Exception as e:
        logger.error(f"Error in PDF test: {e}")


    # Dummy Excel (Pandas can create one)
    dummy_excel_path = os.path.join(test_files_dir, "dummy_excel.xlsx")
    try:
        df_test = pd.DataFrame({
            'Factura N': [101, 102],
            'Concepto': ['Producto A', 'Servicio B'],
            'Base': [100, 200],
            'IVA (21%)': [21, 42],
            'Total': [121, 242]
        })
        writer = pd.ExcelWriter(dummy_excel_path, engine='openpyxl')
        df_test.to_excel(writer, sheet_name='FacturasRecibidas', index=False)
        writer.close() # Replaces writer.save() for newer pandas versions
        logger.info(f"Created dummy Excel: {dummy_excel_path}")
        data_from_excel = extract_data_from_excel(dummy_excel_path)
        logger.info(f"Data from dummy Excel:\n{data_from_excel}")
    except ImportError:
        logger.warning("openpyxl not installed. Skipping Excel test.")
    except Exception as e:
        logger.error(f"Error in Excel test: {e}")

    # Clean up dummy files (optional)
    # import shutil
    # shutil.rmtree(test_files_dir)
    # logger.info(f"Cleaned up test directory: {test_files_dir}")
import io # Required for BytesIO in PDF OCR fallback
