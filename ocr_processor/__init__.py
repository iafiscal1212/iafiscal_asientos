# This file makes Python treat the `ocr_processor` directory as a package.

# Expose key functions for easier import by other modules (like the listener or app)
from .main import process_document_from_drive, extract_text_from_file
from .utils import extract_text_from_image, extract_text_from_pdf, extract_data_from_excel

# You can also define a version for this package
__version__ = "0.1.0"

print("ocr_processor package loaded") # Optional: for debugging imports
