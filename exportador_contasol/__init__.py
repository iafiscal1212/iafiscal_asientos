# This file makes Python treat the `exportador_contasol` directory as a package.

# Expose key functions for easier import by other modules (e.g., Flask app, CLI script)
from .main import export_data_to_contasol_csv
from .utils import (
    generate_contasol_csv_rows,
    write_contasol_csv_file,
    CONTASOL_CSV_HEADER,
    CONTASOL_DATE_FORMAT
)

__version__ = "0.1.0"

print("exportador_contasol package loaded") # Optional: for debugging imports
