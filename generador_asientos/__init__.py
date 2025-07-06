# This file makes Python treat the `generador_asientos` directory as a package.

# Expose key functions and classes for easier import by other modules
from .main import generate_asiento, AsientoContable, ApunteContable
from .information_extractor import extract_invoice_details # Might be useful for pre-processing or diagnostics
from .asiento_utils import ( # Expose some utils if they are generally useful
    calculate_iva_details,
    calculate_irpf_details,
    format_concepto
)

__version__ = "0.1.0"

print("generador_asientos package loaded") # Optional: for debugging imports
