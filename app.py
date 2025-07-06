from flask import Flask, request, jsonify, send_file
import generador_asientos
import exportador
import os
import tempfile

app = Flask(__name__)

# Directorio temporal para almacenar archivos subidos y generados
UPLOAD_FOLDER = tempfile.mkdtemp()
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

@app.route('/', methods=['GET'])
def index():
    return """
    <h1>IAFiscal Asientos - Jules Full</h1>
    <p>Bot que lee facturas, extrae datos, aplica reglas contables y genera asientos para Contasol.</p>
    <h2>Uso (Ejemplo con datos dummy):</h2>
    <p>Para generar un asiento de ejemplo y exportarlo:</p>
    <ol>
        <li>Simule una factura (esto eventualmente será una carga de archivo):</li>
        <pre>
factura_ejemplo = {
    "fecha": "2023-10-26",
    "concepto": "Compra de publicidad en Google",
    "importe": 121.00
}
        </pre>
        <li>Genere el asiento:</li>
        <p><code>POST /generar_asiento</code> con JSON similar a <code>factura_ejemplo</code>.</p>
        <li>Exporte el asiento:</li>
        <p><code>POST /exportar_asientos</code> con JSON que contenga los asientos generados. Devuelve un CSV.</p>
    </ol>
    <p><strong>Nota:</strong> La carga de archivos PDF/JPG/Excel y la extracción de datos aún no están implementadas.</p>
    """

@app.route('/generar_asiento', methods=['POST'])
def generar_asiento_endpoint():
    try:
        datos_factura = request.json
        if not datos_factura or "concepto" not in datos_factura or "importe" not in datos_factura or "fecha" not in datos_factura:
            return jsonify({"error": "Datos de factura incompletos. Se requiere 'fecha', 'concepto', e 'importe'."}), 400

        asiento_generado = generador_asientos.generar_asiento(datos_factura)
        return jsonify(asiento_generado), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"Error inesperado: {str(e)}"}), 500

@app.route('/exportar_asientos', methods=['POST'])
def exportar_asientos_endpoint():
    try:
        asientos_data = request.json
        if not asientos_data:
            return jsonify({"error": "No se proporcionaron asientos para exportar."}), 400

        # Crear un archivo CSV temporal
        temp_csv_path = os.path.join(app.config['UPLOAD_FOLDER'], "export_contasol_temp.csv")

        exportador.exportar_asientos(asientos_data, temp_csv_path)

        return send_file(temp_csv_path, as_attachment=True, download_name="export_contasol.csv", mimetype='text/csv')
    except Exception as e:
        return jsonify({"error": f"Error durante la exportación: {str(e)}"}), 500

if __name__ == '__main__':
    # Limpiar archivos temporales al inicio (si existieran de una ejecución anterior)
    for f in os.listdir(UPLOAD_FOLDER):
        os.remove(os.path.join(UPLOAD_FOLDER, f))
    app.run(debug=True)
