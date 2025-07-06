import re
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)

# Basic regex patterns for common invoice fields. These are examples and will need refinement
# based on the variability of invoice formats.
# Consider using more robust NLP libraries (spaCy, NLTK) or specialized invoice parsing services
# for higher accuracy on diverse documents if simple regex proves insufficient.

# Updated regex patterns:
PATTERNS = {
    "fecha_factura": r"(?:fecha factura|factura de fecha|date of invoice|invoice date)[:\s]*([\d]{1,2}[-/.\s][\d]{1,2}[-/.\s][\d]{2,4}|[\d]{2,4}[-/.\s][\d]{1,2}[-/.\s][\d]{1,2})",
    "numero_factura": r"(?:factura n[ºo\.\s:]*|invoice no\.?|n[ºo\.\s:]*factura|f[ra]\s?n[ºo\.\s:]*)([A-Z0-9/\s-]+[A-Z0-9])", # More flexible for prefixes/suffixes
    "proveedor_nif": r"(?:NIF|CIF|VAT ID|VAT No)[:\s]*([A-Z][\s-]?\d{7,8}[\s-]?[A-Z\d]|[A-Z]{2}[\s-]?\d{9}|[A-Z\d]{8,10}[A-Z])", # Common Spanish NIF/CIF formats and some general VAT
    "cliente_nif": r"(?:NIF cliente|CIF cliente|VAT ID cliente|NIF\s\(destinatario\))[:\s]*([A-Z][\s-]?\d{7,8}[\s-]?[A-Z\d]|[A-Z]{2}[\s-]?\d{9}|[A-Z\d]{8,10}[A-Z])", # Similar for client

    # Amounts: These are tricky due to currency symbols, decimal/thousand separators.
    # This regex tries to capture common formats (e.g., 1.234,56 or 1,234.56 or 1234.56)
    # It's often better to find keywords and then parse nearby numbers.
    "base_imponible": r"(?:base imponible|subtotal|net amount|taxable amount|importe base|base gravable)[:\s€$£]*\s*([-+]?\d{1,3}(?:[.,\s]\d{3})*[.,]\d{2}|-?\d+[.,]\d{2})",
    "cuota_iva": r"(?:total iva|iva \([\d\s.,%]+\)|vat amount|cuota de iva|i\.v\.a\.|iva repercutido)[:\s€$£]*\s*([-+]?\d{1,3}(?:[.,\s]\d{3})*[.,]\d{2}|-?\d+[.,]\d{2})",
    "total_factura": r"(?:total factura|total a pagar|importe total|total amount|invoice total|gran total)[:\s€$£]*\s*([-+]?\d{1,3}(?:[.,\s]\d{3})*[.,]\d{2}|-?\d+[.,]\d{2})",
    "retencion_irpf": r"(?:retenci[oó]n IRPF|IRPF retenido|retenci[oó]n s/IRPF|withholding tax|ret\.irpf)[:\s€$£%]*\s*([-+]?\d{1,3}(?:[.,\s]\d{3})*[.,]\d{2}|-?\d+[.,]\d{2})",

    # IVA Percentages (to corroborate 'IVAType' from rule or find if not specified)
    "iva_percentage": r"(?:IVA|VAT|Impuesto sobre el Valor A[ñn]adido)\s*\(?(\d{1,2}(?:[.,]\d{1,2})?)\s*%?\)?",

    # Provider name: Very hard with regex alone. Often near NIF or "Proveedor:"
    # This is a placeholder idea - might need proximity search to NIF or keywords.
    "proveedor_nombre": r"(?:proveedor|supplier|vendedor|de|emisor|issued by)[:\s\n]*([A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑ\s.,&'-]+(?:S\.?L\.?U?\.?|S\.?A\.?U?\.?|S\.?C\.?P\.?|,?\sInc\.?|,?\sLtd\.?)?)",
    "cliente_nombre": r"(?:cliente|customer|comprador|para|destinatario|billed to)[:\s\n]*([A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑ\s.,&'-]+(?:S\.?L\.?U?\.?|S\.?A\.?U?\.?|S\.?C\.?P\.?|,?\sInc\.?|,?\sLtd\.?)?)"
}

# Order of extraction can matter, e.g., extract total before subtotal if regexes are too greedy.
# For amounts, it's also good to look for multiple occurrences and use context.
EXTRACTION_ORDER = [
    "fecha_factura", "numero_factura", "proveedor_nif", "cliente_nif",
    "proveedor_nombre", "cliente_nombre", # Try to get names after NIFs as NIFs are more unique
    "base_imponible", "iva_percentage", "cuota_iva", "retencion_irpf", "total_factura" # Amounts last, total often most prominent
]


def parse_date(date_str: str) -> Optional[str]:
    """
    Parses a date string into 'YYYY-MM-DD' format.
    Handles common separators like '/', '-', '.' and also DD/MM/YY, DD/MM/YYYY, YYYY/MM/DD.
    """
    if not date_str:
        return None
    date_str = date_str.strip()
    # Normalize separators
    date_str = re.sub(r'[/\s]', '-', date_str) # Replace common separators with hyphen
    date_str = date_str.replace('.', '-') # Replace dot if used as separator

    formats_to_try = [
        "%d-%m-%Y", "%d-%m-%y",  # DD-MM-YYYY, DD-MM-YY
        "%Y-%m-%d",             # YYYY-MM-DD
        "%m-%d-%Y", "%m-%d-%y"   # MM-DD-YYYY, MM-DD-YY (less common in Spain but good to have)
    ]

    parsed_date = None
    for fmt in formats_to_try:
        try:
            dt_obj = datetime.strptime(date_str, fmt)
            # Handle two-digit year: assume current century or previous if it implies future date significantly
            if fmt.endswith("%y"):
                if dt_obj.year > datetime.now().year + 10 : # If YY implies a far future date, assume previous century
                    dt_obj = dt_obj.replace(year=dt_obj.year - 100)
                elif dt_obj.year < 100 and dt_obj.year > (datetime.now().year % 100 + 10) : # Heuristic for very small YY e.g. 01,02 when current year is 23
                     # This case is tricky, but strptime often makes 69-99 -> 19xx and 00-68 -> 20xx
                     pass # Python's strptime usually handles this well.

            parsed_date = dt_obj.strftime("%Y-%m-%d")
            break # Successfully parsed
        except ValueError:
            continue # Try next format

    if not parsed_date:
        logger.warning(f"Could not parse date string: '{date_str}' with known formats.")
    return parsed_date


def parse_amount(amount_str: str) -> Optional[float]:
    """
    Parses an amount string (potentially with thousand/decimal separators) into a float.
    Handles formats like "1.234,56" (European) and "1,234.56" (US/UK).
    Also handles simple "1234.56".
    """
    if not amount_str:
        return None

    s = amount_str.strip()
    # Remove currency symbols if any (though regex might not capture them)
    s = re.sub(r'[€$£\s]', '', s)

    # Determine if comma or dot is the decimal separator
    # A common heuristic: if a dot is present and a comma is to its right, dot is thousands sep.
    # If a comma is present and a dot is to its right, comma is thousands sep.
    # If only one is present, it's likely the decimal separator if it's followed by 2 digits.

    has_dot = '.' in s
    has_comma = ',' in s

    parsed_val = None

    if has_dot and has_comma:
        dot_pos = s.rfind('.')
        comma_pos = s.rfind(',')
        if dot_pos > comma_pos: # e.g., 1,234.56 (dot is decimal)
            s = s.replace(',', '')
        else: # e.g., 1.234,56 (comma is decimal)
            s = s.replace('.', '').replace(',', '.')
    elif has_dot: # Only dot is present
        # If dot is followed by 3 digits and then end of string or another non-digit, it might be thousands
        # e.g. "1.234". But "12.345" could be amount. This is ambiguous.
        # If only one dot and it's separating two digits at the end, assume it's decimal.
        if s.count('.') == 1 and len(s.split('.')[1]) == 2: # e.g. 1234.56
            pass # s is already in good format for float()
        elif s.count('.') > 1 : # Multiple dots usually means they are thousand separators e.g. 1.234.567 (no decimal part)
             s = s.replace('.', '') # Treat as integer or assume no decimals
        # else: # Single dot, but not with 2 decimal places (e.g. "1.234" or "12.3") - ambiguous
        #    pass # Let float() try, might be fine

    elif has_comma: # Only comma is present
        # If comma is followed by 2 digits at the end, assume it's decimal
        if s.count(',') == 1 and len(s.split(',')[1]) == 2: # e.g. 1234,56
            s = s.replace(',', '.')
        elif s.count(',') > 1: # Multiple commas usually mean they are thousand separators
            s = s.replace(',', '') # Treat as integer or assume no decimals
        # else: # Single comma, not with 2 decimal places (e.g. "1,234" or "12,3") - ambiguous
        #    s = s.replace(',', '.') # Tentatively treat as decimal for float()

    try:
        # Remove any remaining non-numeric characters except sign and decimal point (already handled)
        # s = re.sub(r'[^\d\.\-]', '', s) # This might be too aggressive
        parsed_val = float(s)
    except ValueError:
        logger.warning(f"Could not parse amount string: '{amount_str}' to float after normalization to '{s}'.")
        return None

    return parsed_val


def extract_invoice_details(text_content: str) -> Dict[str, Any]:
    """
    Extracts key information from invoice text using regex.
    This is a simplified extractor. For production, a more robust solution
    (e.g., ML-based, or a specialized library/service) would be needed.

    Args:
        text_content (str): The full text content of the invoice.

    Returns:
        Dict[str, Any]: A dictionary with extracted fields.
                        Fields not found will have a value of None.
    """
    if not text_content:
        return {key: None for key in PATTERNS}

    extracted_data: Dict[str, Any] = {key: None for key in PATTERNS}

    # Pre-process text: replace multiple newlines/spaces to simplify regex matching
    # text_content_norm = re.sub(r'\s+', ' ', text_content.replace('\n', ' ')) # Flatten text
    # However, sometimes line breaks are important context. Let's try with original text first.

    logger.debug(f"Starting extraction from text: \n{text_content[:500]}...")

    for field_key in EXTRACTION_ORDER: # Use defined order
        pattern = PATTERNS[field_key]
        try:
            # Search for all matches, then try to pick the best one (e.g. first, last, or based on context)
            # For now, taking the first match found.
            # Using re.IGNORECASE for most text matching.
            # Some fields like NIF might be case-sensitive in parts, but regex handles specific [A-Z]
            matches = re.finditer(pattern, text_content, re.IGNORECASE | re.MULTILINE)

            found_values = []
            for match in matches:
                if match.groups(): # Ensure the capturing group matched
                    val = match.group(1).strip()
                    if val:
                        found_values.append(val)

            if not found_values:
                logger.debug(f"No match for field '{field_key}' using pattern: {pattern}")
                continue

            # Heuristic: For some fields, the last occurrence might be more relevant (e.g., total amounts)
            # For others, the first (e.g., invoice number at the top).
            # This needs refinement. For now, let's take the first non-empty found value.
            # TODO: Add better logic to choose among multiple matches (e.g. proximity to keywords, longest match)
            value_to_process = found_values[0] # Default to first match

            if field_key.startswith("fecha"):
                extracted_data[field_key] = parse_date(value_to_process)
            elif field_key in ["base_imponible", "cuota_iva", "total_factura", "retencion_irpf", "iva_percentage"]:
                parsed_amount = parse_amount(value_to_process)
                # Store only if successfully parsed, otherwise keep as None
                if parsed_amount is not None:
                    extracted_data[field_key] = parsed_amount
            elif field_key.endswith("_nif"):
                # NIFs often have spaces/hyphens, standardize by removing them for storage/comparison
                extracted_data[field_key] = re.sub(r'[\s-]', '', value_to_process).upper()
            elif field_key.endswith("_nombre"):
                # Clean up names: remove excessive whitespace
                name_cleaned = re.sub(r'\s+', ' ', value_to_process).strip(".,:")
                # Avoid overly long matches if regex is too greedy
                if len(name_cleaned) < 100: # Arbitrary limit
                    extracted_data[field_key] = name_cleaned
                else:
                    logger.debug(f"Skipping long name match for {field_key}: '{name_cleaned[:100]}...'")

            else: # For fields like numero_factura
                extracted_data[field_key] = value_to_process.strip()

            if extracted_data[field_key] is not None:
                 logger.info(f"Extracted '{field_key}': {extracted_data[field_key]} (from raw: '{value_to_process}')")
            else: # Parsing failed for date/amount or name was too long
                 logger.warning(f"Parsing/Validation failed for field '{field_key}', raw value was '{value_to_process}'. Kept as None.")


        except re.error as re_err:
            logger.error(f"Regex error for field {field_key} with pattern {pattern}: {re_err}")
        except Exception as e:
            logger.error(f"Unexpected error extracting field {field_key}: {e}", exc_info=True)

    # Post-processing and validation (examples)
    if extracted_data.get("base_imponible") is not None and \
       extracted_data.get("cuota_iva") is not None and \
       extracted_data.get("total_factura") is not None:
        calculated_total = round(extracted_data["base_imponible"] + extracted_data["cuota_iva"], 2)
        # Account for potential retentions if present
        if extracted_data.get("retencion_irpf") is not None:
            calculated_total -= round(extracted_data["retencion_irpf"], 2) # Assuming retencion is positive value

        if abs(calculated_total - extracted_data["total_factura"]) > 0.05: # Tolerance for rounding
            logger.warning(f"Consistency check failed: Base ({extracted_data['base_imponible']}) + "
                           f"IVA ({extracted_data['cuota_iva']}) "
                           f"(- IRPF {extracted_data.get('retencion_irpf', 0)}) = {calculated_total} "
                           f"does not match Total ({extracted_data['total_factura']}).")
            # This could be a flag: extracted_data['consistency_check_passed'] = False

    # If IVAType from rule is e.g. "General (21%)" and iva_percentage found is different, log warning
    # This requires passing `classified_transaction.iva_type` to this function or doing this check later.

    logger.info(f"Final extracted data: {extracted_data}")
    return extracted_data


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    sample_invoice_text_energia = """
    FACTURA ELECTRÓNICA
    Número de factura: FE2023/00815-A
    Fecha factura: 25-10-2023
    Vencimiento: 10/11/2023

    Datos del emisor:
    ELECTRA ENERGIA S.A.U.
    Avda. de la Luz, 123, Madrid
    NIF: A-12345678

    Datos del cliente:
    MI EMPRESA S.L.
    Calle Sol, 45, Valencia
    NIF Cliente: B-87654321

    Conceptos:
    - Consumo energético Octubre 2023: 150,00 €
    - Alquiler contador: 5,50 €

    Base Imponible: 155,50 EUR
    IVA (21%): 32,66 EUR
    Total Factura: 188,16 EUR
    Forma de pago: Domiciliación
    """

    sample_invoice_text_servicios_con_retencion = """
    FACTURA PROFORMA (luego será definitiva)
    FREELANCER AUTONOMO
    NIF: 12345678Z
    Calle Luna, 1, Sevilla

    Factura Nº: FRA-2023-10-005
    Fecha de la factura: October 28, 2023

    Cliente:
    SERVICIOS PROFESIONALES INTEGRALES S.L.U.
    N.I.F.: B98765000
    Gran Vía, 100, Barcelona

    Descripción                                     Precio      Cantidad    Total
    --------------------------------------------------------------------------------
    Servicios de consultoría estratégica proyecto X   1000.00      1        1000.00

    Subtotal: 1.000,00
    IVA (21%): 210,00
    Retención IRPF (15%): -150,00
    TOTAL A PAGAR: 1.060,00 €
    """

    logger.info("--- Testing Energia Invoice ---")
    details_energia = extract_invoice_details(sample_invoice_text_energia)
    # print(details_energia)
    for k,v in details_energia.items(): print(f"{k}: {v}")


    logger.info("\n--- Testing Servicios con Retencion Invoice ---")
    details_servicios = extract_invoice_details(sample_invoice_text_servicios_con_retencion)
    # print(details_servicios)
    for k,v in details_servicios.items(): print(f"{k}: {v}")

    # Test date parsing
    logger.info("\n--- Testing Date Parsing ---")
    dates_to_test = ["25/10/2023", "25-10-2023", "25.10.2023", "2023-10-25", "10-25-2023", "25/10/23", "23-10-25"]
    for d_str in dates_to_test:
        logger.info(f"Parsing '{d_str}': {parse_date(d_str)}")

    # Test amount parsing
    logger.info("\n--- Testing Amount Parsing ---")
    amounts_to_test = ["1.234,56", "1,234.56", "1234.56", "1234,56", "1500", "1.500", "1,500", "1.234.567,89", "1,234,567.89", "-50,25", "-50.25"]
    for a_str in amounts_to_test:
        logger.info(f"Parsing '{a_str}': {parse_amount(a_str)}")

    # Test a more complex NIF/Factura No
    complex_text = """
    Factura n.º: F2023/A-001 REX
    NIF A12345678
    Factura de fecha 01.01.2024
    Base: 100.00 , Cuota IVA: 21.00 , Total: 121.00
    """
    logger.info("\n--- Testing Complex Invoice Snippet ---")
    details_complex = extract_invoice_details(complex_text)
    for k,v in details_complex.items(): print(f"{k}: {v}")

    empty_text_details = extract_invoice_details("")
    assert all(v is None for v in empty_text_details.values())
    logger.info("\n--- Test with empty text completed ---")

    # Test with only a NIF
    nif_only_text = "Proveedor NIF ESB12345678"
    logger.info("\n--- Testing NIF only ---")
    details_nif_only = extract_invoice_details(nif_only_text)
    for k,v in details_nif_only.items(): print(f"{k}: {v}")
    assert details_nif_only.get("proveedor_nif") == "ESB12345678"

    logger.info("Information Extractor tests finished.")
