import logging
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Dict, Any, List, Tuple

logger = logging.getLogger(__name__)

# Define standard IVA rates (as Decimals for precision)
# These could also come from config or a dedicated IVA table/rules if they change frequently
IVA_RATES = {
    "General (21%)": Decimal("0.21"),
    "Reducido (10%)": Decimal("0.10"),
    "Superreducido (4%)": Decimal("0.04"),
    "Exento": Decimal("0.00"), # For operations that are exempt from IVA
    "No Sujeto": Decimal("0.00"), # For operations not subject to IVA
    "ISP": Decimal("0.00"), # Inversión del Sujeto Pasivo (Reverse Charge VAT) - handled differently
    # Add other rates or special IVA types as needed
}

# Standard account numbers (PGC Español - examples, expand as needed)
# These are just common ones, the rules file will provide most accounts.
# This dict is more for default/fallback/system accounts.
STANDARD_ACCOUNTS = {
    "IVA_SOPORTADO_GENERAL": "472.21", # Default for 21% deductible VAT
    "IVA_SOPORTADO_REDUCIDO": "472.10",
    "IVA_SOPORTADO_SUPERREDUCIDO": "472.04",
    "IVA_REPERCUTIDO_GENERAL": "477.21", # Default for 21% output VAT
    "IVA_REPERCUTIDO_REDUCIDO": "477.10",
    "IVA_REPERCUTIDO_SUPERREDUCIDO": "477.04",
    "HACIENDA_PUBLICA_DEUDORA_IVA": "4700", # When IVA soportado > IVA repercutido
    "HACIENDA_PUBLICA_ACREEDORA_IVA": "4750", # When IVA repercutido > IVA soportado (to pay)
    "IRPF_RETENCIONES_PROFESIONALES": "4751.01", # Retenciones IRPF a profesionales (15% usual)
    "IRPF_RETENCIONES_ALQUILERES": "4751.02", # Retenciones IRPF alquileres (19% usual)
    "BANCOS": "572", # Default bank account (needs specific subaccount)
    "CAJA": "570",
    "PROVEEDORES_GENERAL": "400", # Base for general suppliers
    "CLIENTES_GENERAL": "430", # Base for general customers
    "COMPRAS_MERCADERIAS": "600",
    "VENTAS_MERCADERIAS": "700",
    "GASTOS_SUMINISTROS": "628", # Electricity, water, gas
    "GASTOS_ALQUILER": "621",
    "GASTOS_PERSONAL": "640",
    "VARIACION_EXISTENCIAS": "610", # For purchases if using stock variation method
}

# Precision for rounding currency values (2 decimal places)
TWO_PLACES = Decimal("0.01")


def calculate_iva_details(base_imponible: Optional[Decimal],
                          iva_type_str: Optional[str],
                          cuota_iva_extracted: Optional[Decimal] = None,
                          tipo_operacion: Optional[str] = None) -> Tuple[Optional[Decimal], Optional[str], Optional[Decimal]]:
    """
    Calculates IVA amount and determines the IVA account based on base_imponible and iva_type.
    Compares with extracted cuota_iva if available.

    Args:
        base_imponible (Optional[Decimal]): Taxable base amount.
        iva_type_str (Optional[str]): String describing the IVA type (e.g., "General (21%)", "Exento").
        cuota_iva_extracted (Optional[Decimal]): IVA amount extracted from the document, for comparison.
        tipo_operacion (Optional[str]): Type of operation (e.g., 'Gasto', 'Ingreso') to choose soportado/repercutido account.

    Returns:
        Tuple[Optional[Decimal], Optional[str], Optional[Decimal]]:
            - Calculated IVA amount (Decimal).
            - IVA account number (str).
            - Difference between calculated and extracted IVA (if extracted was provided).
              None if base_imponible or iva_type_str is missing.
    """
    if base_imponible is None or not iva_type_str:
        logger.warning("Cannot calculate IVA: base_imponible or iva_type_str is missing.")
        return None, None, None

    iva_rate = IVA_RATES.get(iva_type_str)
    if iva_rate is None:
        # Attempt to parse rate from string like "XX%" if not in IVA_RATES
        match_percent = re.match(r'(\d{1,2}(?:[.,]\d{1,2})?)\s*%', iva_type_str)
        if match_percent:
            try:
                rate_val_str = match_percent.group(1).replace(',', '.')
                iva_rate = Decimal(rate_val_str) / Decimal("100")
                logger.info(f"Parsed IVA rate {iva_rate*100}% from string '{iva_type_str}'.")
            except Exception:
                logger.warning(f"Could not parse numeric IVA rate from '{iva_type_str}'.")
                return None, None, None # Cannot determine rate
        else:
            logger.warning(f"Unknown IVA type: '{iva_type_str}'. Cannot determine IVA rate.")
            # If it's something like "IVA 0%" or "Exento de IVA", treat as 0 rate
            if "0%" in iva_type_str.lower() or "exento" in iva_type_str.lower():
                iva_rate = Decimal("0.00")
            else:
                return None, None, None # Cannot determine rate

    calculated_cuota_iva = (base_imponible * iva_rate).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)

    iva_account = None
    # Determine IVA account (soportado for gastos/compras, repercutido for ingresos/ventas)
    # This is a simplification; complex scenarios exist.
    if tipo_operacion:
        op_type_lower = tipo_operacion.lower()
        if "gasto" in op_type_lower or "compra" in op_type_lower:
            if iva_rate == Decimal("0.21"): iva_account = STANDARD_ACCOUNTS["IVA_SOPORTADO_GENERAL"]
            elif iva_rate == Decimal("0.10"): iva_account = STANDARD_ACCOUNTS["IVA_SOPORTADO_REDUCIDO"]
            elif iva_rate == Decimal("0.04"): iva_account = STANDARD_ACCOUNTS["IVA_SOPORTADO_SUPERREDUCIDO"]
            # For Exento or No Sujeto, iva_account might be None or a specific control account if needed.
            # If iva_rate is 0, cuota_iva will be 0, so no IVA account line needed unless for ISP.
        elif "ingreso" in op_type_lower or "venta" in op_type_lower:
            if iva_rate == Decimal("0.21"): iva_account = STANDARD_ACCOUNTS["IVA_REPERCUTIDO_GENERAL"]
            elif iva_rate == Decimal("0.10"): iva_account = STANDARD_ACCOUNTS["IVA_REPERCUTIDO_REDUCIDO"]
            elif iva_rate == Decimal("0.04"): iva_account = STANDARD_ACCOUNTS["IVA_REPERCUTIDO_SUPERREDUCIDO"]

    # Handle ISP (Inversión del Sujeto Pasivo / Reverse Charge)
    # Both soportado and repercutido IVA accounts are used, effectively cancelling out for net IVA.
    # The amounts are the same.
    if iva_type_str == "ISP":
        # For ISP, we need both a "repercutido" and "soportado" IVA account for the same amount.
        # The actual account numbers might be specific for ISP operations.
        # For simplicity, using general ones but they should be distinct if possible.
        # This will result in two lines in the asiento for IVA.
        # The `iva_account` returned here would be one part, the generator needs to add the other.
        # Let's assume the `iva_account` returned is the 'soportado' part for now.
        if iva_rate == Decimal("0.21"): iva_account = STANDARD_ACCOUNTS["IVA_SOPORTADO_GENERAL"] # And 477.21 for repercutido
        # Similar for other rates if ISP applies.
        logger.info("ISP detected. Asiento will include both soportado and repercutido IVA for the same amount.")
        # The main generator logic will need to handle adding the corresponding 477 line.


    difference = None
    if cuota_iva_extracted is not None:
        difference = (calculated_cuota_iva - cuota_iva_extracted).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        if abs(difference) > Decimal("0.05"): # Tolerance for rounding differences
            logger.warning(f"Calculated IVA ({calculated_cuota_iva}) differs from extracted IVA ({cuota_iva_extracted}) by {difference}. "
                           f"Using calculated IVA. Base: {base_imponible}, Rate from Type: '{iva_type_str}' ({iva_rate*100}%).")
            # Decision: Use calculated or extracted? Usually calculated is more reliable if base and rate are certain.
            # For now, this function returns the calculated one. The caller can decide.

    # If IVA rate is 0 (Exento, No Sujeto), the calculated_cuota_iva will be 0.
    # In this case, no IVA account line is typically needed unless specific tracking is required.
    # So, iva_account could remain None.
    if iva_rate == Decimal("0.00") and iva_type_str != "ISP": # ISP at 0% is rare but if it happens, still need both lines.
        iva_account = None
        calculated_cuota_iva = Decimal("0.00") # Ensure it's exactly zero

    return calculated_cuota_iva, iva_account, difference


def calculate_irpf_details(base_imponible: Optional[Decimal],
                           special_treatment_str: Optional[str], # e.g., "IRPF 15%", "Retencion Alquiler 19%"
                           retencion_irpf_extracted: Optional[Decimal] = None
                           ) -> Tuple[Optional[Decimal], Optional[str], Optional[Decimal]]:
    """
    Calculates IRPF retention amount and determines the IRPF account.

    Args:
        base_imponible (Optional[Decimal]): Base amount for IRPF calculation.
        special_treatment_str (Optional[str]): String describing the special treatment, expected to contain IRPF rate.
        retencion_irpf_extracted (Optional[Decimal]): Extracted IRPF amount for comparison.

    Returns:
        Tuple[Optional[Decimal], Optional[str], Optional[Decimal]]:
            - Calculated IRPF amount (Decimal).
            - IRPF account number (str).
            - Difference between calculated and extracted IRPF.
              None if base or rate cannot be determined.
    """
    if base_imponible is None or not special_treatment_str:
        return None, None, None

    irpf_rate = None
    irpf_account = None

    # Try to parse rate from special_treatment_str
    # Example: "IRPF (15%)", "Retencion Alquiler (19%)"
    match = re.search(r'IRPF\s*(?:\(\s*|s/)?(\d{1,2}(?:[.,]\d{1,2})?)\s*%?', special_treatment_str, re.IGNORECASE)
    if match:
        try:
            rate_val_str = match.group(1).replace(',', '.')
            irpf_rate = Decimal(rate_val_str) / Decimal("100")
            # Determine account based on context (e.g., if "alquiler" is in special_treatment_str)
            if "alquiler" in special_treatment_str.lower():
                irpf_account = STANDARD_ACCOUNTS["IRPF_RETENCIONES_ALQUILERES"]
            else: # Default to professional services retention
                irpf_account = STANDARD_ACCOUNTS["IRPF_RETENCIONES_PROFESIONALES"]
            logger.info(f"Parsed IRPF rate {irpf_rate*100}% from '{special_treatment_str}'. Account: {irpf_account}")
        except Exception as e:
            logger.warning(f"Could not parse IRPF rate from '{special_treatment_str}': {e}")
            return None, None, None
    else:
        logger.debug(f"No IRPF percentage found in special treatment string: '{special_treatment_str}'.")
        return None, None, None # No IRPF rate found

    calculated_irpf = (base_imponible * irpf_rate).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)

    difference = None
    if retencion_irpf_extracted is not None:
        difference = (calculated_irpf - retencion_irpf_extracted).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        if abs(difference) > Decimal("0.05"):
            logger.warning(f"Calculated IRPF ({calculated_irpf}) differs from extracted IRPF ({retencion_irpf_extracted}) by {difference}. Using calculated.")

    return calculated_irpf, irpf_account, difference


def format_concepto(concepto_patron: Optional[str], extracted_info: Dict[str, Any]) -> str:
    """
    Formats the accounting entry concept using a pattern and extracted invoice details.
    Example pattern: "Factura {proveedor_nombre} N. {numero_factura}"

    Args:
        concepto_patron (str): The pattern string with placeholders like {field_name}.
        extracted_info (Dict[str, Any]): Dictionary of details extracted from the invoice.
                                         (e.g., from information_extractor.py)
    Returns:
        str: The formatted concept string.
    """
    if not concepto_patron: # If no pattern from rule, create a generic one
        concepto_patron = "Op. s/doc N. {numero_factura} de {fecha_factura}"
        if extracted_info.get("proveedor_nombre"):
            concepto_patron = "F/{proveedor_nombre_short} N.{numero_factura} F.{fecha_factura_short}"
        elif extracted_info.get("cliente_nombre"):
             concepto_patron = "F/{cliente_nombre_short} N.{numero_factura} F.{fecha_factura_short}"


    # Prepare some short versions for conciseness in concepts
    data_for_format = extracted_info.copy()
    if extracted_info.get("proveedor_nombre"):
        data_for_format["proveedor_nombre_short"] = extracted_info["proveedor_nombre"][:20] # Max 20 chars
    if extracted_info.get("cliente_nombre"):
        data_for_format["cliente_nombre_short"] = extracted_info["cliente_nombre"][:20]
    if extracted_info.get("fecha_factura"): # Expects YYYY-MM-DD
        try:
            dt_obj = datetime.strptime(extracted_info["fecha_factura"], "%Y-%m-%d")
            data_for_format["fecha_factura_short"] = dt_obj.strftime("%d/%m/%y")
        except (ValueError, TypeError):
            data_for_format["fecha_factura_short"] = extracted_info["fecha_factura"] # fallback to original if not parsable

    # Fill placeholders
    # Use a try-except for str.format in case some placeholders are not in data_for_format
    # or have problematic values (e.g. None, which format handles, but good practice)
    try:
        # Replace missing placeholders with a default string like "[n/a]" or empty string
        # This requires iterating through placeholders in pattern.
        # A simpler way: ensure all keys in `data_for_format` are strings or format handles them.
        # Convert None values in data_for_format to empty strings for formatting
        safe_data_for_format = {k: (v if v is not None else "") for k, v in data_for_format.items()}

        # Find all placeholders in the pattern
        placeholders = re.findall(r'\{([^}]+)\}', concepto_patron)
        for ph in placeholders:
            if ph not in safe_data_for_format:
                safe_data_for_format[ph] = "[n/d]" # Not available / no disponible

        formatted_concepto = concepto_patron.format(**safe_data_for_format)
    except KeyError as e:
        logger.warning(f"Missing key {e} in extracted_info for concepto pattern: '{concepto_patron}'. Using fallback.")
        # Fallback concept if formatting fails
        num_fact = extracted_info.get("numero_factura", "[s/n]")
        fecha_fact = extracted_info.get("fecha_factura", "[s/f]")
        formatted_concepto = f"Operación según documento {num_fact} de {fecha_fact}"

    # Ensure concept is not overly long (Contasol might have limits, e.g. 38 or 40 chars for some fields)
    # This limit should be configurable.
    MAX_CONCEPTO_LENGTH = 38
    if len(formatted_concepto) > MAX_CONCEPTO_LENGTH:
        formatted_concepto = formatted_concepto[:MAX_CONCEPTO_LENGTH-3] + "..."

    return formatted_concepto.strip()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)

    # Test IVA Calculation
    logger.info("\n--- Testing IVA Calculation ---")
    base = Decimal("100.00")
    iva_calc, acc, diff = calculate_iva_details(base, "General (21%)", Decimal("21.00"), "Gasto")
    logger.info(f"IVA Gasto General: Amount={iva_calc}, Account={acc}, Diff={diff}")
    assert iva_calc == Decimal("21.00") and acc == "472.21"

    iva_calc, acc, diff = calculate_iva_details(base, "Reducido (10%)", Decimal("10.00"), "Ingreso")
    logger.info(f"IVA Ingreso Reducido: Amount={iva_calc}, Account={acc}, Diff={diff}")
    assert iva_calc == Decimal("10.00") and acc == "477.10"

    iva_calc, acc, diff = calculate_iva_details(base, "Exento", Decimal("0.00"), "Gasto")
    logger.info(f"IVA Gasto Exento: Amount={iva_calc}, Account={acc}, Diff={diff}")
    assert iva_calc == Decimal("0.00") and acc is None

    iva_calc, acc, diff = calculate_iva_details(base, "ISP", Decimal("21.00"), "Compra") # Assuming 21% ISP rate
    logger.info(f"IVA Compra ISP (21% assumed): Amount={iva_calc}, Account={acc}, Diff={diff}")
    # For ISP, the returned account is one part (e.g. soportado), generator adds the other (repercutido)
    # This needs to be handled by the main asiento generator. Here we test it gets a valid rate and one account part.
    assert iva_calc == Decimal("21.00") # Assuming 21% for ISP for this test
    # The account would be 472.21, and 477.21 would be added by generator.

    iva_calc, acc, diff = calculate_iva_details(Decimal("123.45"), "IVA 10%", Decimal("12.30"), "Gasto") # Test parsing rate from string
    logger.info(f"IVA Gasto 10% (from string): Amount={iva_calc}, Account={acc}, Diff={diff if diff else 'N/A'}")
    assert acc == "472.10" and abs(iva_calc - Decimal("12.35")) < Decimal("0.01") # 123.45 * 0.10 = 12.345 -> 12.35

    # Test IRPF Calculation
    logger.info("\n--- Testing IRPF Calculation ---")
    irpf_calc, acc_irpf, diff_irpf = calculate_irpf_details(base, "IRPF (15%)", Decimal("15.00"))
    logger.info(f"IRPF Profesional: Amount={irpf_calc}, Account={acc_irpf}, Diff={diff_irpf}")
    assert irpf_calc == Decimal("15.00") and acc_irpf == "4751.01"

    irpf_calc, acc_irpf, diff_irpf = calculate_irpf_details(Decimal("1000.00"), "Retencion Alquiler (19%)", Decimal("190.00"))
    logger.info(f"IRPF Alquiler: Amount={irpf_calc}, Account={acc_irpf}, Diff={diff_irpf}")
    assert irpf_calc == Decimal("190.00") and acc_irpf == "4751.02"

    # Test Concepto Formatting
    logger.info("\n--- Testing Concepto Formatting ---")
    info = {
        "proveedor_nombre": "Proveedor Muy Largo S.L. Unipersonal",
        "numero_factura": "F2023/XYZ/12345",
        "fecha_factura": "2023-10-26",
        "total_factura": Decimal("121.00")
    }
    patron = "F/{proveedor_nombre_short} N.{numero_factura} F.{fecha_factura_short} Total:{total_factura}"
    concepto = format_concepto(patron, info)
    logger.info(f"Concepto: '{concepto}' (Length: {len(concepto)})")
    # Expected: "F/Proveedor Muy Largo S N.F2023/XYZ/12345 F.26/10/23 Total:121.00" (check length)
    # Max length 38. "F/Proveedor Muy Largo S N.F2023/XYZ/1..."
    assert len(concepto) <= 38

    patron_missing = "Operacion con {campo_inexistente}"
    concepto_missing = format_concepto(patron_missing, info)
    logger.info(f"Concepto (missing placeholder): '{concepto_missing}'")
    assert "[n/d]" in concepto_missing

    concepto_default = format_concepto(None, info) # Test default pattern
    logger.info(f"Concepto (default pattern): '{concepto_default}'")
    assert "F/Proveedor Muy Largo S" in concepto_default and "F2023/XYZ/12345" in concepto_default

    logger.info("Asiento Utils tests finished.")
import re # For calculate_iva_details if parsing rate from string like "XX%"
