FROM python:3.11-slim

# Instalar dependencias de wkhtmltopdf
RUN apt-get update && \
    apt-get install -y \
        wkhtmltopdf \
        xvfb \
        xfonts-base \
        xfonts-75dpi \
        libxrender1 \
        libxext6 \
        libfontconfig1 \
        libjpeg62-turbo \
        libpng16-16 \
        libssl3 \
        libx11-6 \
        libxcb1 \
        libxrandr2 \
        libxinerama1 \
        libfreetype6 \
        libstdc++6 \
        libgcc-s1 \
        && apt-get clean

# Directorio
WORKDIR /app
COPY . .

# Instalar dependencias Python
RUN pip install --no-cache-dir -r requirements.txt

# Variables necesarias
ENV XDG_RUNTIME_DIR=/tmp/runtime
RUN mkdir -p /tmp/runtime && chmod 777 /tmp/runtime

# Exponer puerto
EXPOSE 5000

CMD ["python", "app.py"]

