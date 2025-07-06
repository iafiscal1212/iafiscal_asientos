import logging
from typing import Optional, Dict, Any

from .utils import load_rules, match_rule

logger = logging.getLogger(__name__)

# This structure will hold the result of classification
# It's simplified for now. The generador_asientos module will need more details.
# For example, it will need amounts, dates, IVA details, provider info etc.
# The classification step primarily identifies accounts and treatment based on text.
class ClassifiedTransaction:
    def __init__(self, matched_rule: Dict[str, Any], original_text: str):
        self.rule_details: Dict[str, Any] = matched_rule
        self.original_text: str = original_text # Keep a reference to the text that was classified

        # Extract common fields from the rule for easier access
        # These names must match the columns in your rules Excel file
        self.account: Optional[str] = matched_rule.get("Account")
        self.contrapartida: Optional[str] = matched_rule.get("Contrapartida")
        self.tipo_operacion: Optional[str] = matched_rule.get("TipoOperacion")
        self.iva_type: Optional[str] = matched_rule.get("IVAType")
        self.special_treatment: Optional[str] = matched_rule.get("SpecialTreatment")
        self.concepto_patron: Optional[str] = matched_rule.get("ConceptoPatron")

        # Placeholder for data to be extracted by a later stage (e.g. information extraction)
        # For now, these would be populated by a hypothetical "extract_invoice_details" function
        self.extracted_info: Dict[str, Any] = {
            "fecha_factura": None,
            "numero_factura": None,
            "proveedor_nombre": None,
            "proveedor_nif": None,
            "cliente_nombre": None, # if applicable
            "cliente_nif": None, # if applicable
            "base_imponible": None,
            "cuota_iva": None,
            "total_factura": None,
            "retencion_irpf": None, # if applicable
            "otros_impuestos": None,
            # ... any other relevant fields from the invoice text
        }
        self.is_valid_for_asiento: bool = bool(self.account and self.tipo_operacion) # Basic check

    def __str__(self):
        return (f"ClassifiedTransaction:\n"
                f"  Account: {self.account}\n"
                f"  Contrapartida: {self.contrapartida}\n"
                f"  TipoOperacion: {self.tipo_operacion}\n"
                f"  IVAType: {self.iva_type}\n"
                f"  SpecialTreatment: {self.special_treatment}\n"
                f"  ConceptoPatron: {self.concepto_patron}\n"
                f"  Matched on Keywords: {self.rule_details.get('Keywords')}\n"
                f"  Original Text Snippet: '{self.original_text[:100]}...'")


def classify_text_content(text_content: str, force_rules_reload: bool = False) -> Optional[ClassifiedTransaction]:
    """
    Classifies the given text content based on pre-defined rules.

    Args:
        text_content (str): The text extracted from a document (e.g., by OCR).
        force_rules_reload (bool): Whether to force a reload of the rules from the source file.

    Returns:
        Optional[ClassifiedTransaction]: An object containing the classification details
                                         if a rule matches, otherwise None.
                                         Returns None also if rules cannot be loaded.
    """
    if not text_content:
        logger.warning("Cannot classify empty text content.")
        return None

    logger.info(f"Attempting to classify text content (length: {len(text_content)} chars).")

    rules_df = load_rules(force_reload=force_rules_reload)
    if rules_df is None or rules_df.empty:
        logger.error("Rules for classification could not be loaded or are empty. Classification aborted.")
        # This might be a critical error, consider raising an exception or specific status
        return None

    matched_rule_dict = match_rule(text_content, rules_df)

    if matched_rule_dict:
        logger.info(f"Successfully classified text. Matched rule for keywords: '{matched_rule_dict.get('Keywords')}'.")
        transaction = ClassifiedTransaction(matched_rule_dict, text_content)

        # Here, you would ideally call another function to parse `text_content`
        # based on the type of document suggested by `transaction.tipo_operacion`
        # or specific keywords, to fill `transaction.extracted_info`.
        # e.g., extracted_details = information_extractor.extract_details(text_content, transaction.tipo_operacion)
        # transaction.extracted_info.update(extracted_details)
        logger.info("Placeholder for detailed information extraction from text (amounts, dates, etc.).")

        return transaction
    else:
        logger.info("Text content did not match any classification rules.")
        # According to project spec: "si no se encuentra concepto → marcar para revisión"
        # This "marcar para revisión" should happen in the calling module (e.g. listener or main pipeline)
        # by setting a specific status in the database for the processed file.
        # This function's role is just to return None or a classification.
        return None


if __name__ == '__main__':
    # Example Usage & Testing
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # Ensure .env is loaded for rule loading (especially if rules are from Drive or path is in .env)
    import os
    env_path_proj = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '.env')
    if os.path.exists(env_path_proj):
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=env_path_proj, override=True)
        logger.info(f"Loaded .env from {env_path_proj} for testing reglas_clasificacion.main.")
    else:
        logger.warning(f".env file not found at {env_path_proj}. Rule loading might use defaults or fail if not configured.")


    # Test with some sample OCR outputs
    sample_ocr_invoice_energia = """
    FACTURA
    Cliente: EMPRESA XYZ SL NIF B12345678
    Número de factura: F2023/00123
    Fecha de factura: 15/10/2023
    Fecha de vencimiento: 30/10/2023

    Concepto                                     Base Imp.    %IVA    Cuota IVA    Total
    --------------------------------------------------------------------------------------
    Suministro energía eléctrica período          100.00      21%      21.00      121.00
    Octubre 2023. Contrato 987654.
    Peajes y costes regulados                     20.00      21%       4.20       24.20
    --------------------------------------------------------------------------------------
    TOTAL                                        120.00                25.20      145.20

    Forma de pago: Domiciliación bancaria ESXX XXXX XXXX XXXX XXXX
    Proveedor: ENERGÉTICA GLOBAL SA, NIF A98765432
    """

    sample_ocr_alquiler = """
    RECIBO ALQUILER LOCAL
    Fecha: 01/11/2023
    Arrendador: Inmuebles Urbanos SL (B99887766)
    Arrendatario: EMPRESA XYZ SL (B12345678)
    Concepto: Alquiler local comercial Calle Mayor 1, Madrid, mes Noviembre 2023.
    Base Imponible: 1000.00 EUR
    IVA (21%): 210.00 EUR
    Retención IRPF (19%): -190.00 EUR
    Total a pagar: 1020.00 EUR
    """

    sample_ocr_unknown = """
    Informe de reunión de seguimiento del proyecto Alpha.
    Asistentes: John Doe, Jane Smith.
    Fecha: 20/10/2023
    Próximos pasos: Revisar hitos y presupuesto.
    """

    test_contents = {
        "Energia Electrica": sample_ocr_invoice_energia,
        "Alquiler Local": sample_ocr_alquiler,
        "Documento Desconocido": sample_ocr_unknown
    }

    # Ensure rules are available (dummy rules might be created by utils.py if run before)
    # Running load_rules once here can help ensure they are cached or issues are seen.
    logger.info("Pre-loading rules for the test...")
    initial_rules = load_rules(force_reload=True) # Use force_reload if you changed the rules file
    if initial_rules is None or initial_rules.empty:
        logger.error("Failed to load rules for testing main.py. Ensure 'reglas_contables_IAFiscal.xlsx' is correctly set up and accessible.")
        logger.error("You might need to run reglas_clasificacion/utils.py first if it creates a dummy rules file.")
    else:
        logger.info(f"Successfully pre-loaded {len(initial_rules)} rules for the test.")

        for name, content in test_contents.items():
            logger.info(f"\n--- Classifying content for: '{name}' ---")
            classified_result = classify_text_content(content) # Don't force reload here to test caching

            if classified_result:
                logger.info(f"Classification Result for '{name}':")
                logger.info(str(classified_result))
                if not classified_result.is_valid_for_asiento:
                    logger.warning("The matched rule might be incomplete for generating a full accounting entry (missing Account or TipoOperacion).")
            else:
                logger.info(f"No classification rule matched for '{name}'. This item should be marked for manual review.")

    logger.info("\n--- `reglas_clasificacion.main` test finished ---")
