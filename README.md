# IAFiscal Asientos - Jules Full

Bot que lee facturas en PDF, JPG o Excel, extrae los datos, aplica reglas contables del PGC español embebidas,
genera asientos contables completos y los exporta en CSV para importación en Contasol.

## Descripción del Proyecto

Este proyecto tiene como objetivo automatizar la generación de asientos contables a partir de facturas. Utiliza un conjunto de reglas predefinidas para clasificar los conceptos de las facturas y generar los apuntes contables correspondientes según el Plan General Contable español. La salida es un archivo CSV formateado para su importación directa en el software Contasol.

## Estructura del Proyecto

- `app.py`: Aplicación principal Flask que gestiona las rutas y la lógica de la API.
- `reglas_clasificacion.py`: Contiene las reglas para clasificar los conceptos de las facturas.
- `generador_asientos.py`: Lógica para generar los asientos contables basados en las reglas.
- `exportador.py`: Funcionalidad para exportar los asientos a formato CSV compatible con Contasol.
- `requirements.txt`: Lista de dependencias de Python.
- `Dockerfile`: Archivo para construir la imagen Docker de la aplicación.
- `uploads/`: Directorio temporal para archivos (creado en tiempo de ejecución si es necesario, actualmente gestionado por `tempfile`).

## Características

- **Entrada**: Datos de facturas (actualmente mediante JSON, planeado para PDF/JPG/Excel).
- **Salida**: Hoja CSV con el formato `[fecha; diario; cuenta; concepto; debe; haber]`.
- **Reglas Embebidas**: Las reglas de clasificación contable están definidas en el código.
- **Framework**: Flask.
- **Lenguaje**: Python.

## Cómo Empezar

### Prerrequisitos

- Python 3.8 o superior
- pip (gestor de paquetes de Python)
- Docker (opcional, para ejecución en contenedor)

### Instalación

1.  **Clona el repositorio (o crea los archivos según las instrucciones):**
    ```bash
    # git clone <URL_DEL_REPOSITORIO>
    # cd iafiscal-asientos-contasol
    ```
    (Reemplaza `<URL_DEL_REPOSITORIO>` con la URL real una vez subido a GitHub)

2.  **Crea un entorno virtual (recomendado):**
    ```bash
    python -m venv venv
    source venv/bin/activate  # En Windows: venv\Scripts\activate
    ```

3.  **Instala las dependencias:**
    ```bash
    pip install -r requirements.txt
    ```

### Ejecución

1.  **Inicia la aplicación Flask:**
    ```bash
    python iafiscal_asientos_google/app.py
    ```
    La aplicación estará disponible en `http://127.0.0.1:5000`.

2.  **Probar los endpoints (usando una herramienta como `curl` o Postman):**

    *   **Generar un asiento:**
        Envía una petición POST a `http://127.0.0.1:5000/generar_asiento` con el siguiente JSON en el cuerpo:
        ```json
        {
            "fecha": "2023-10-27",
            "concepto": "Servicios de asesoría fiscal",
            "importe": 242.00
        }
        ```
        Respuesta esperada (JSON con el asiento):
        ```json
        [
            {
                "concepto": "Servicios de asesoría fiscal",
                "cuenta": "622",
                "debe": 200.0,
                "fecha": "2023-10-27",
                "haber": 0
            },
            {
                "concepto": "IVA Soportado",
                "cuenta": "472",
                "debe": 42.0,
                "fecha": "2023-10-27",
                "haber": 0
            },
            {
                "concepto": "Pago banco",
                "cuenta": "572",
                "debe": 0,
                "fecha": "2023-10-27",
                "haber": 242.0
            }
        ]
        ```

    *   **Exportar asientos a CSV:**
        Envía una petición POST a `http://127.0.0.1:5000/exportar_asientos` con el siguiente JSON en el cuerpo (usa la salida del paso anterior):
        ```json
        [
            [
                {
                    "concepto": "Servicios de asesoría fiscal",
                    "cuenta": "622",
                    "debe": 200.0,
                    "fecha": "2023-10-27",
                    "haber": 0
                },
                {
                    "concepto": "IVA Soportado",
                    "cuenta": "472",
                    "debe": 42.0,
                    "fecha": "2023-10-27",
                    "haber": 0
                },
                {
                    "concepto": "Pago banco",
                    "cuenta": "572",
                    "debe": 0,
                    "fecha": "2023-10-27",
                    "haber": 242.0
                }
            ]
        ]
        ```
        Esto descargará un archivo `export_contasol.csv`.

### Ejecución con Docker (Opcional)

1.  **Construye la imagen Docker:**
    ```bash
    docker build -t iafiscal-asientos .
    ```

2.  **Ejecuta el contenedor:**
    ```bash
    docker run -p 5000:5000 iafiscal-asientos
    ```
    La aplicación estará accesible en `http://localhost:5000`.

## Próximos Pasos y Mejoras

-   **Lectura de Archivos**: Implementar la funcionalidad para leer datos de facturas desde archivos PDF, JPG y Excel. Esto requerirá librerías como `PyPDF2` (o `pdfplumber`), `Pillow` (PIL), y `openpyxl` (o `pandas`).
-   **Interfaz de Usuario**: Desarrollar una interfaz web simple (usando Flask templates) para la carga de archivos y visualización de resultados.
-   **Mejora de Reglas**: Permitir la gestión de reglas de forma más dinámica (ej. desde un archivo de configuración o una base de datos).
-   **Manejo de Errores Avanzado**: Mejorar el feedback al usuario en caso de errores en la clasificación o procesamiento.
-   **Pruebas Unitarias**: Añadir pruebas para asegurar la fiabilidad de los módulos.

## Repositorio GitHub

-   **Usuario**: iafiscal1212
-   **Nombre del Repositorio**: iafiscal-asientos-contasol
-   **Privado**: Sí

(Este README se actualizará con la URL del repositorio una vez creado y subido el código.)
