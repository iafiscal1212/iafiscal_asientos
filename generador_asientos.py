from reglas_clasificacion import obtener_reglas

def clasificar_concepto(concepto):
    reglas = obtener_reglas()
    concepto = concepto.lower()
    for regla in reglas:
        if any(palabra in concepto for palabra in regla["keywords"]):
            return regla
    return None

def generar_asiento(factura):
    regla = clasificar_concepto(factura["concepto"])
    if not regla:
        raise ValueError("No se pudo clasificar la factura")

    base = factura["importe"] / (1 + regla["iva"] / 100)
    iva = factura["importe"] - base
    asiento = []

    asiento.append({
        "fecha": factura["fecha"],
        "cuenta": regla["cuenta"],
        "concepto": factura["concepto"],
        "debe": round(base, 2),
        "haber": 0
    })

    asiento.append({
        "fecha": factura["fecha"],
        "cuenta": "472",
        "concepto": "IVA Soportado",
        "debe": round(iva, 2),
        "haber": 0
    })

    asiento.append({
        "fecha": factura["fecha"],
        "cuenta": "572",
        "concepto": "Pago banco",
        "debe": 0,
        "haber": round(factura["importe"], 2)
    })

    return asiento
