# This file makes Python treat the `reglas_clasificacion` directory as a package.

# Expose key functions for easier import by other modules
from .main import classify_text_content, ClassifiedTransaction
from .utils import load_rules # Might be useful for diagnostics or direct rule inspection

__version__ = "0.1.0"

print("reglas_clasificacion package loaded") # Optional: for debugging imports
