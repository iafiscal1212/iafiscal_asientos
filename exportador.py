import csv

def exportar_asientos(asientos, archivo_salida="export_contasol.csv"):
    with open(archivo_salida, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(["fecha", "diario", "cuenta", "concepto", "debe", "haber"])
        for asiento_contable in asientos: # Cambiado 'linea' a 'asiento_contable' para claridad
            for linea_asiento in asiento_contable: # Iterar sobre las líneas dentro de un asiento
                writer.writerow([
                    linea_asiento["fecha"],
                    1, # Diario por defecto es 1
                    linea_asiento["cuenta"],
                    linea_asiento["concepto"],
                    linea_asiento["debe"],
                    linea_asiento["haber"]
                ])
