import logging
from decimal import Decimal
from typing import Optional, List, Dict, Any

# Project-specific imports
from reglas_clasificacion.main import ClassifiedTransaction # Input object
from .information_extractor import extract_invoice_details # To get amounts, dates etc.
from .asiento_utils import (
    calculate_iva_details,
    calculate_irpf_details,
    format_concepto,
    STANDARD_ACCOUNTS, # May need some default accounts
    TWO_PLACES
)

logger = logging.getLogger(__name__)

# Structure for an accounting entry line (apunte)
class ApunteContable:
    def __init__(self, cuenta: str, concepto: str, debe: Decimal, haber: Decimal):
        self.cuenta: str = cuenta
        self.concepto: str = concepto # Concept for this specific line, can differ from asiento concept
        self.debe: Decimal = debe.quantize(TWO_PLACES)
        self.haber: Decimal = haber.quantize(TWO_PLACES)

    def __str__(self):
        return f"Cuenta: {self.cuenta}, Concepto: '{self.concepto}', Debe: {self.debe}, Haber: {self.haber}"

# Structure for a full accounting entry (asiento)
class AsientoContable:
    def __init__(self, fecha: str, diario_code: str = "1"): # diario_code '1' for general/compras
        self.fecha: str = fecha # YYYY-MM-DD
        self.diario_code: str = diario_code # Contasol uses diario codes
        self.apuntes: List[ApunteContable] = []
        self.concepto_general: Optional[str] = None # Overall concept for the asiento
        # Metadata
        self.document_id: Optional[str] = None # e.g. Drive file ID
        self.document_link: Optional[str] = None # Link to view document
        self.needs_manual_review: bool = False
        self.review_reason: Optional[str] = None

    def add_apunte(self, cuenta: str, concepto: str, debe: Decimal = Decimal("0.00"), haber: Decimal = Decimal("0.00")):
        self.apuntes.append(ApunteContable(cuenta, concepto, debe, haber))

    def is_cuadrado(self) -> bool:
        """Checks if the sum of debits equals the sum of credits."""
        total_debe = sum(ap.debe for ap in self.apuntes).quantize(TWO_PLACES)
        total_haber = sum(ap.haber for ap in self.apuntes).quantize(TWO_PLACES)
        return total_debe == total_haber

    def get_totals(self) -> Tuple[Decimal, Decimal]:
        total_debe = sum(ap.debe for ap in self.apuntes).quantize(TWO_PLACES)
        total_haber = sum(ap.haber for ap in self.apuntes).quantize(TWO_PLACES)
        return total_debe, total_haber

    def __str__(self):
        s = f"Asiento Contable (Fecha: {self.fecha}, Diario: {self.diario_code}, Concepto General: '{self.concepto_general}')\n"
        if self.needs_manual_review:
            s += f"  **NEEDS MANUAL REVIEW**: {self.review_reason}\n"
        for apunte in self.apuntes:
            s += f"  - {apunte}\n"
        total_d, total_h = self.get_totals()
        s += f"  Totals: Debe={total_d}, Haber={total_h}, Cuadrado: {self.is_cuadrado()}"
        return s


def generate_asiento(classified_transaction: ClassifiedTransaction,
                       original_document_id: Optional[str] = None, # e.g. Drive File ID
                       document_link: Optional[str] = None
                       ) -> Optional[AsientoContable]:
    """
    Generates an accounting entry (AsientoContable) from a ClassifiedTransaction.
    This involves:
    1. Extracting detailed information (amounts, dates, NIFs) from the original text.
    2. Calculating IVA, IRPF if applicable.
    3. Constructing debit and credit lines (ApunteContable).
    4. Handling special cases like "IVA 0% (exento)" or "IRPF".
    """
    if not classified_transaction or not classified_transaction.is_valid_for_asiento:
        logger.error("Cannot generate asiento: ClassifiedTransaction is invalid or missing key rule details.")
        return None

    logger.info(f"Generating asiento for TipoOperacion: {classified_transaction.tipo_operacion}, Account: {classified_transaction.account}")

    # 1. Extract detailed information from the original text
    # The `original_text` is stored in `classified_transaction.original_text`
    # The `extracted_info` in `classified_transaction` is a placeholder; we populate it now.
    extracted_details = extract_invoice_details(classified_transaction.original_text)
    classified_transaction.extracted_info.update(extracted_details) # Update the transaction object

    # Get key values, converting amounts to Decimal
    fecha_factura = extracted_details.get("fecha_factura") # Expected YYYY-MM-DD
    if not fecha_factura:
        logger.error("Cannot generate asiento: Fecha de factura not found in document.")
        # Create a placeholder asiento marked for review
        asiento = AsientoContable(fecha="YYYY-MM-DD") # Placeholder date
        asiento.needs_manual_review = True
        asiento.review_reason = "Fecha de factura no encontrada."
        asiento.document_id = original_document_id
        asiento.document_link = document_link
        asiento.concepto_general = "Error: Fecha no encontrada"
        return asiento # Return asiento for review

    asiento = AsientoContable(fecha=fecha_factura)
    asiento.document_id = original_document_id
    asiento.document_link = document_link

    # Format the general concept for the asiento
    asiento.concepto_general = format_concepto(
        classified_transaction.concepto_patron,
        classified_transaction.extracted_info
    )

    # Convert extracted amounts to Decimal, defaulting to 0 if None
    base_imponible = Decimal(str(extracted_details.get("base_imponible", "0.00")))
    cuota_iva_ext = Decimal(str(extracted_details.get("cuota_iva", "0.00"))) if extracted_details.get("cuota_iva") is not None else None
    retencion_irpf_ext = Decimal(str(extracted_details.get("retencion_irpf", "0.00"))) if extracted_details.get("retencion_irpf") is not None else None
    total_factura_ext = Decimal(str(extracted_details.get("total_factura", "0.00")))

    if base_imponible == Decimal("0.00") and total_factura_ext == Decimal("0.00"):
        # If it's a zero-value invoice, it might be informational or need special handling.
        # For now, if no base, assume it might be problematic unless explicitly exento/no sujeto.
        if not (classified_transaction.iva_type in ["Exento", "No Sujeto"] or "0%" in classified_transaction.iva_type):
             logger.warning("Base imponible is zero and total is zero. Review if this is correct.")
             asiento.needs_manual_review = True
             asiento.review_reason = "Base imponible y total son cero. Verificar."
             # Still proceed to generate what we can.

    # 2. Calculate IVA
    # The tipo_operacion from the rule helps determine if it's IVA Soportado or Repercutido
    calculated_iva, iva_account, _ = calculate_iva_details(
        base_imponible,
        classified_transaction.iva_type,
        cuota_iva_ext,
        classified_transaction.tipo_operacion
    )
    # If rule specified "IVA 0%" or similar, mark as exento if not already
    if "0%" in classified_transaction.iva_type and not asiento.needs_manual_review :
        if not (classified_transaction.special_treatment and "exento" in classified_transaction.special_treatment.lower()):
            asiento.needs_manual_review = True # As per spec: "si hay IVA 0% → marcar como exento"
            asiento.review_reason = "IVA 0% detectado. Confirmar si es Exento y tratamiento contable."
            logger.info("IVA 0% detected from rule. Marked for review to confirm 'exento' status.")


    # 3. Calculate IRPF (if applicable from rule's SpecialTreatment)
    calculated_irpf, irpf_account, _ = calculate_irpf_details(
        base_imponible,
        classified_transaction.special_treatment,
        retencion_irpf_ext
    )
    # As per spec: "si hay IRPF → añadir 4751"
    # The irpf_account from calculate_irpf_details should already be a 4751.xx type.
    # We just need to ensure it's used if calculated_irpf is not None and > 0.

    # 4. Construct Apuntes Contables
    # This logic depends heavily on classified_transaction.tipo_operacion and the accounts from rule.
    # Example for a Gasto/Compra:
    # Debe: Gasto_Account (Base Imponible), IVA_Soportado_Account (Cuota IVA)
    # Haber: Proveedor_Account/Banco_Account (Total Factura), IRPF_Retenido_Account (Cuota IRPF)

    main_account = classified_transaction.account # e.g., 6xx for Gasto, 7xx for Ingreso
    contrapartida_account = classified_transaction.contrapartida # e.g., 400 Proveedor, 430 Cliente, 572 Banco

    # Refine contrapartida if it's generic (e.g. "400") using NIF/Name if available
    # This is a placeholder for more advanced sub-account creation/lookup.
    if contrapartida_account == STANDARD_ACCOUNTS["PROVEEDORES_GENERAL"] and extracted_details.get("proveedor_nif"):
        # Example: contrapartida_account = f"400{extracted_details['proveedor_nif'][:6]}" # Simple example
        # A real system would look up or create a specific provider sub-account.
        logger.info(f"Generic provider account {STANDARD_ACCOUNTS['PROVEEDORES_GENERAL']} used. Consider specific sub-account for {extracted_details.get('proveedor_nombre')}.")
    elif contrapartida_account == STANDARD_ACCOUNTS["CLIENTES_GENERAL"] and extracted_details.get("cliente_nif"):
        logger.info(f"Generic client account {STANDARD_ACCOUNTS['CLIENTES_GENERAL']} used. Consider specific sub-account for {extracted_details.get('cliente_nombre')}.")


    # Determine total amount for contrapartida (usually total_factura_ext)
    # However, it's better to calculate it from components for consistency if possible
    total_haber_calculated = base_imponible + (calculated_iva if calculated_iva else Decimal("0.00"))
    total_debe_calculated = base_imponible + (calculated_iva if calculated_iva else Decimal("0.00"))

    if calculated_irpf and calculated_irpf > Decimal("0.00"):
        total_haber_calculated -= calculated_irpf # IRPF reduces amount paid to provider

    # Check consistency of calculated total for contrapartida vs extracted total_factura
    if total_factura_ext is not None and abs(total_haber_calculated - total_factura_ext) > Decimal("0.05"):
        logger.warning(f"Calculated total for contrapartida ({total_haber_calculated}) "
                       f"differs from extracted total_factura ({total_factura_ext}). Using calculated total for asiento balancing.")
        asiento.needs_manual_review = True
        asiento.review_reason = asiento.review_reason + " Discrepancia entre total calculado y extraído." if asiento.review_reason else "Discrepancia total calculado vs extraído."


    op_type_lower = classified_transaction.tipo_operacion.lower()
    line_concepto = asiento.concepto_general # Use general concept for all lines, or make specific

    if "gasto" in op_type_lower or "compra" in op_type_lower:
        # Linea de Gasto/Compra (Debe)
        asiento.add_apunte(main_account, line_concepto, debe=base_imponible)

        # Linea de IVA Soportado (Debe)
        if calculated_iva and calculated_iva > Decimal("0.00") and iva_account:
            asiento.add_apunte(iva_account, line_concepto, debe=calculated_iva)
        elif classified_transaction.iva_type == "ISP" and iva_account and calculated_iva is not None: # ISP case
            # Soportado (Debe)
            asiento.add_apunte(iva_account, f"IVA Soportado ISP - {line_concepto}", debe=calculated_iva)
            # Repercutido (Haber) - needs the corresponding 477 account
            # This assumes iva_account from calculate_iva_details was the 472.xx for ISP.
            # We need a robust way to get the pair. For now, derive from iva_account.
            iva_repercutido_isp_account = iva_account.replace("472", "477") # Hacky, improve this
            asiento.add_apunte(iva_repercutido_isp_account, f"IVA Repercutido ISP - {line_concepto}", haber=calculated_iva)


        # Linea de IRPF Retenido (Haber - it's a liability for us)
        if calculated_irpf and calculated_irpf > Decimal("0.00") and irpf_account:
            asiento.add_apunte(irpf_account, line_concepto, haber=calculated_irpf)

        # Linea de Contrapartida (Proveedor/Banco) (Haber)
        # Amount is Base + IVA - IRPF
        monto_contrapartida = base_imponible \
                            + (calculated_iva if (calculated_iva and classified_transaction.iva_type != "ISP") else Decimal("0.00")) \
                            - (calculated_irpf if calculated_irpf else Decimal("0.00"))
        asiento.add_apunte(contrapartida_account, line_concepto, haber=monto_contrapartida.quantize(TWO_PLACES))

    elif "ingreso" in op_type_lower or "venta" in op_type_lower:
        # Linea de Ingreso/Venta (Haber)
        asiento.add_apunte(main_account, line_concepto, haber=base_imponible)

        # Linea de IVA Repercutido (Haber)
        if calculated_iva and calculated_iva > Decimal("0.00") and iva_account:
            asiento.add_apunte(iva_account, line_concepto, haber=calculated_iva)
        # Note: ISP on sales side is different (customer handles it), usually "no sujeto" or "exento" for supplier.
        # The rule's IVAType should reflect this.

        # Linea de IRPF (if client withholds from us - less common for typical sales, more for professional services income)
        # This would be a DEBIT to a 473 (HP Retenciones y Pagos a Cuenta)
        if calculated_irpf and calculated_irpf > Decimal("0.00") and irpf_account:
            # If it's an income and we are subject to retention by client:
            retencion_soportada_cuenta = irpf_account.replace("4751", "473") # e.g. 473.01 HP Retenciones Soportadas
            asiento.add_apunte(retencion_soportada_cuenta, line_concepto, debe=calculated_irpf)

        # Linea de Contrapartida (Cliente/Banco) (Debe)
        # Amount is Base + IVA - IRPF_soportado_por_nosotros
        monto_contrapartida = base_imponible \
                            + (calculated_iva if calculated_iva else Decimal("0.00")) \
                            - (calculated_irpf if calculated_irpf else Decimal("0.00")) # If client retained IRPF from us
        asiento.add_apunte(contrapartida_account, line_concepto, debe=monto_contrapartida.quantize(TWO_PLACES))

    else:
        logger.error(f"TipoOperacion '{classified_transaction.tipo_operacion}' no implementado para generación de asiento.")
        asiento.needs_manual_review = True
        asiento.review_reason = f"Tipo de operación no soportado: {classified_transaction.tipo_operacion}"
        # Add a dummy balancing line if possible, or just return for review
        asiento.add_apunte("000REVIEW", "Error tipo operacion", debe=base_imponible)
        asiento.add_apunte("000REVIEW", "Error tipo operacion", haber=base_imponible)


    # Final check: Ensure asiento is cuadrado
    if not asiento.is_cuadrado():
        logger.error(f"Asiento no está cuadrado! Debe: {asiento.get_totals()[0]}, Haber: {asiento.get_totals()[1]}. Marcando para revisión.")
        asiento.needs_manual_review = True
        asiento.review_reason = (asiento.review_reason + " Asiento descuadrado." if asiento.review_reason
                                 else "Asiento descuadrado.")

    if asiento.needs_manual_review:
        logger.warning(f"Asiento generado pero necesita revisión: {asiento.review_reason}")
    else:
        logger.info(f"Asiento generado correctamente: {asiento.concepto_general}")

    return asiento


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # Sample ClassifiedTransaction objects for testing
    # (Mimicking what `reglas_clasificacion` would produce)

    # Test 1: Gasto con IVA y Retencion IRPF (Alquiler)
    rule_alquiler = {
        "Keywords": "alquiler local", "Priority": 10, "Account": "621", "Contrapartida": "410PROPALQ",
        "TipoOperacion": "Gasto Alquiler", "IVAType": "General (21%)",
        "SpecialTreatment": "Retencion Alquiler (19%)",
        "ConceptoPatron": "Alquiler local {mes}/{ano} C/{calle}"
    }
    text_alquiler = """
    Recibo de Alquiler - Mes: Noviembre/2023
    Arrendador: PROPIETARIO GUAY SL - NIF B12345678
    Local: Calle Luna, 23
    Base Imponible: 1000.00 EUR
    IVA (21%): 210.00 EUR
    Retención IRPF (19%): -190.00 EUR
    Total Recibo: 1020.00 EUR
    Fecha Factura: 01/11/2023, Factura n.º REC-11-2023
    """
    ct_alquiler = ClassifiedTransaction(rule_alquiler, text_alquiler)
    # Manually add some extracted info that information_extractor would find (for this test)
    ct_alquiler.extracted_info.update({
        "fecha_factura": "2023-11-01", "numero_factura": "REC-11-2023",
        "proveedor_nombre": "PROPIETARIO GUAY SL", "proveedor_nif": "B12345678",
        "base_imponible": Decimal("1000.00"), "cuota_iva": Decimal("210.00"),
        "retencion_irpf": Decimal("190.00"), "total_factura": Decimal("1020.00"),
        "mes": "Noviembre", "ano": "2023", "calle": "Calle Luna, 23" # For concepto
    })

    logger.info("\n--- Test Asiento Alquiler (Gasto con IVA y Retención) ---")
    asiento_alquiler = generate_asiento(ct_alquiler, "doc_alquiler_id", "http://example.com/doc_alquiler")
    if asiento_alquiler:
        print(asiento_alquiler)
        assert asiento_alquiler.is_cuadrado()
        assert any(ap.cuenta == STANDARD_ACCOUNTS["IRPF_RETENCIONES_ALQUILERES"] for ap in asiento_alquiler.apuntes)


    # Test 2: Ingreso con IVA (Venta de servicios)
    rule_venta_servicios = {
        "Keywords": "servicio consultoria, diseno web", "Priority": 10, "Account": "705", "Contrapartida": "430CLIENTE",
        "TipoOperacion": "Ingreso Prestacion Servicios", "IVAType": "General (21%)",
        "SpecialTreatment": "", "ConceptoPatron": "Factura SW {cliente_nombre} Proy {proyecto}"
    }
    text_venta = """
    Factura No. F2023-001
    Fecha: 2023-10-20
    Cliente: MI GRAN CLIENTE SL (NIF B98765432)
    Proyecto: Desarrollo Web Corporativa
    Concepto: Diseño y desarrollo portal web.
    Base Imponible: 2500.00
    IVA 21%: 525.00
    Total Factura: 3025.00
    """
    ct_venta = ClassifiedTransaction(rule_venta_servicios, text_venta)
    ct_venta.extracted_info.update({
        "fecha_factura": "2023-10-20", "numero_factura": "F2023-001",
        "cliente_nombre": "MI GRAN CLIENTE SL", "cliente_nif": "B98765432",
        "base_imponible": Decimal("2500.00"), "cuota_iva": Decimal("525.00"),
        "total_factura": Decimal("3025.00"), "proyecto": "Web Corporativa"
    })
    logger.info("\n--- Test Asiento Venta Servicios (Ingreso con IVA) ---")
    asiento_venta = generate_asiento(ct_venta, "doc_venta_id")
    if asiento_venta:
        print(asiento_venta)
        assert asiento_venta.is_cuadrado()


    # Test 3: Compra con ISP (Inversión Sujeto Pasivo)
    rule_compra_isp = {
        "Keywords": "chatarra, desperdicios", "Priority": 10, "Account": "600", "Contrapartida": "400PROVCHAT",
        "TipoOperacion": "Compra con ISP", "IVAType": "ISP", # Assume 21% for ISP calculation in asiento_utils
        "SpecialTreatment": "Inversion Sujeto Pasivo",
        "ConceptoPatron": "Compra chatarra segun factura {numero_factura}"
    }
    text_compra_isp = """
    Factura de ProveedorChatarra S.A. NIF A00000001
    Número de Factura: ISP-2023-50
    Fecha: 15/11/2023
    Operación con Inversión del Sujeto Pasivo art. 84.Uno.2º LIVA
    Base Imponible: 500.00 EUR
    Total Factura: 500.00 EUR (IVA no incluido por ISP)
    """
    ct_compra_isp = ClassifiedTransaction(rule_compra_isp, text_compra_isp)
    ct_compra_isp.extracted_info.update({
        "fecha_factura": "2023-11-15", "numero_factura": "ISP-2023-50",
        "proveedor_nombre": "ProveedorChatarra S.A.", "proveedor_nif": "A00000001",
        "base_imponible": Decimal("500.00"), "cuota_iva": Decimal("0.00"), # Extracted cuota is 0
        "total_factura": Decimal("500.00")
    })
    # For ISP, we need to tell calculate_iva_details the rate that *would* apply.
    # Let's assume the rule implies 21% for ISP if not specified otherwise.
    # So, IVAType "ISP" in rule, asiento_utils.calculate_iva_details uses hardcoded 21% for ISP if not specific rate found.
    # Or, rule could be "ISP (21%)". Let's make it "ISP (21%)" in rule for clarity.
    ct_compra_isp.rule_details["IVAType"] = "ISP (21%)" # Modify rule for test

    logger.info("\n--- Test Asiento Compra con ISP ---")
    asiento_compra_isp = generate_asiento(ct_compra_isp, "doc_isp_id")
    if asiento_compra_isp:
        print(asiento_compra_isp)
        assert asiento_compra_isp.is_cuadrado()
        # Check for both 472 and 477 lines for ISP
        has_472 = any(ap.cuenta.startswith("472") for ap in asiento_compra_isp.apuntes)
        has_477 = any(ap.cuenta.startswith("477") for ap in asiento_compra_isp.apuntes)
        assert has_472 and has_477

    # Test 4: Gasto Exento de IVA
    rule_gasto_exento = {
        "Keywords": "seguro medico, formacion exenta", "Priority": 10, "Account": "629", "Contrapartida": "410ASEGURA",
        "TipoOperacion": "Gasto Exento", "IVAType": "Exento",
        "SpecialTreatment": "", "ConceptoPatron": "Seguro de salud poliza {numero_poliza}"
    }
    text_gasto_exento = """
    Recibo Seguro Salud - Poliza P98765
    Aseguradora Sanitas - NIF A22222222
    Fecha: 01/12/2023, Factura No. SEG-12-23
    Importe: 80.00 EUR (Exento de IVA art. 20 LIVA)
    """
    ct_gasto_exento = ClassifiedTransaction(rule_gasto_exento, text_gasto_exento)
    ct_gasto_exento.extracted_info.update({
        "fecha_factura": "2023-12-01", "numero_factura": "SEG-12-23",
        "proveedor_nombre": "Sanitas", "proveedor_nif": "A22222222",
        "base_imponible": Decimal("80.00"), "cuota_iva": Decimal("0.00"),
        "total_factura": Decimal("80.00"), "numero_poliza": "P98765"
    })
    logger.info("\n--- Test Asiento Gasto Exento ---")
    asiento_gasto_exento = generate_asiento(ct_gasto_exento, "doc_exento_id")
    if asiento_gasto_exento:
        print(asiento_gasto_exento)
        assert asiento_gasto_exento.is_cuadrado()
        # Ensure no IVA account line is present
        assert not any(ap.cuenta.startswith("472") or ap.cuenta.startswith("477") for ap in asiento_gasto_exento.apuntes)


    # Test 5: Documento sin fecha (debería marcarse para revisión)
    rule_sin_fecha = {
        "Keywords": "nota simple", "Priority": 1, "Account": "629", "Contrapartida": "410NOTAS",
        "TipoOperacion": "Gasto Varios", "IVAType": "General (21%)",
        "SpecialTreatment": "", "ConceptoPatron": "Nota simple ref {referencia}"
    }
    text_sin_fecha = "Concepto: Nota Simple Ref. XYZ123. Importe: 10 EUR + IVA. Proveedor: Registradores Online."
    ct_sin_fecha = ClassifiedTransaction(rule_sin_fecha, text_sin_fecha)
    # Intentionally do not provide 'fecha_factura' in extracted_info
    ct_sin_fecha.extracted_info.update({
        "base_imponible": Decimal("10.00"), "referencia": "XYZ123"
    })
    logger.info("\n--- Test Asiento Sin Fecha ---")
    asiento_sin_fecha = generate_asiento(ct_sin_fecha, "doc_sin_fecha_id")
    if asiento_sin_fecha:
        print(asiento_sin_fecha)
        assert asiento_sin_fecha.needs_manual_review
        assert "Fecha de factura no encontrada" in asiento_sin_fecha.review_reason

    logger.info("\nGenerador Asientos tests finished.")
