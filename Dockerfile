# ------------------------------
# Imagen base de Python
# ------------------------------
FROM python:3.10-slim

# ------------------------------
# Instalar wkhtmltopdf + dependencias necesarias
# ------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    wkhtmltopdf \
    libxrender1 \
    libfontconfig1 \
    libxext6 \
    libfreetype6 \
    libjpeg62-turbo \
    libpng16-16 \
    libssl3 \
    fontconfig \
    xfonts-75dpi \
    xfonts-base \
    && rm -rf /var/lib/apt/lists/*

# ------------------------------
# Crear directorio de trabajo
# ------------------------------
WORKDIR /app

# ------------------------------
# Copiar proyecto a contenedor
# ------------------------------
COPY . .

# ------------------------------
# Instalar dependencias Python
# ------------------------------
RUN pip install --no-cache-dir -r requirements.txt

# ------------------------------
# Comando final para Render
# ------------------------------
CMD ["gunicorn", "--bind=0.0.0.0:10000", "app:app"]
