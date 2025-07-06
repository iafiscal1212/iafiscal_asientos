# IAFiscal OCR Excel API

Este proyecto es una API basada en Flask que permite:

* Recibir facturas en formato imagen (PNG).
* Aplicar OCR para extraer texto.
* Generar un Excel con los datos contables estructurados.
* Pensado para desplegar directamente en Google Cloud Run.

## 🚀 Cómo desplegar en Cloud Run

### 1. Dockerfile

Crea un archivo `Dockerfile` en el mismo directorio:

```Dockerfile
FROM python:3.10-slim

WORKDIR /app

COPY . /app

RUN pip install --no-cache-dir flask pytesseract pandas pillow openpyxl

RUN apt-get update && apt-get install -y tesseract-ocr && apt-get clean

EXPOSE 8080

ENV PORT 8080

CMD ["python", "ocr_excel_api.py"]
```

### 2. Build y despliegue

```bash
gcloud builds submit --tag gcr.io/TU_PROYECTO/ocr-excel-api
gcloud run deploy ocr-excel-api \
  --image gcr.io/TU_PROYECTO/ocr-excel-api \
  --platform managed \
  --region europe-west1 \
  --allow-unauthenticated
```

Reemplaza `TU_PROYECTO` por tu ID de proyecto de GCP.

## 📥 Uso de la API

### Endpoint:

`POST /subir_factura`

### Ejemplo con `curl`

```bash
curl -X POST https://ocr-excel-api-xxxx.a.run.app/subir_factura \
  -F "file=@tu_factura.png" \
  --output salida.xlsx
```

## 🧠 Futuras integraciones IA

* Integración con modelos como Mistral (via API o local).
* Extracción semántica de datos fiscales con NLP.
* Entrenamiento supervisado basado en ejemplos contables.

## 📝 Columnas del Excel generado

* Cuenta
* Título de la cuenta
* Saldo
* Tipo de identificación fiscal
* Número de identificación fiscal
* Tipo de impuesto (1=IVA, 2=IGIC)
* Nombre comercial
* Dirección (tipo, nombre, número, ciudad, provincia, país)
* Teléfono, móvil, fax

---

Este proyecto forma parte de la iniciativa **IA Fiscal** para automatizar la contabilidad con IA.
