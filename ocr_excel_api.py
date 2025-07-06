from flask import Flask, request, send_file, jsonify
import os
import tempfile
import pytesseract
from PIL import Image
import pandas as pd
from werkzeug.utils import secure_filename

app = Flask(__name__)
UPLOAD_FOLDER = tempfile.mkdtemp()
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Columnas del Excel personalizado
EXCEL_COLUMNS = [
    "Cuenta", "Título de la cuenta", "Saldo", "Tipo de identificación fiscal",
    "Número de identificación fiscal", "Tipo de impuesto (1=IVA, 2=IGIC)", "Nombre comercial",
    "Domicilio, Tipo de vía", "Domicilio, Nombre vía", "Domicilio, Número",
    "C.Postal", "Población", "Provincia", "Código de país (España=724)",
    "Teléfono", "Móvil", "Fax"
]

@app.route("/subir_factura", methods=["POST"])
def subir_factura():
    if 'file' not in request.files:
        return jsonify({"error": "No se ha enviado archivo."}), 400

    file = request.files['file']
    filename = secure_filename(file.filename)
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(file_path)

    try:
        # Leer imagen con PIL
        image = Image.open(file_path)
        text = pytesseract.image_to_string(image)

        # Lógica para usar modelo IA entrenable como Mistral podría ir aquí
        # Se podría usar una API o localmente si el modelo está disponible (placeholder)

        # Simulamos extracción de datos clave del OCR
        sample_data = [[
            "430000", "Clientes nacionales", "1520.35", "NIF", "B12345678", 1, "Tech S.L.",
            "Calle", "Mayor", "12", "28013", "Madrid", "Madrid", "724", "913456789", "600123456", "913456780"
        ]]
        df = pd.DataFrame(sample_data, columns=EXCEL_COLUMNS)

        output_excel = os.path.join(app.config['UPLOAD_FOLDER'], f"salida_{filename}.xlsx")
        df.to_excel(output_excel, index=False)

        return send_file(output_excel, as_attachment=True)

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 8080))
    app.run(debug=False, host="0.0.0.0", port=port)
