#!/usr/bin/env bash
set -o errexit

echo "[Render Build] Actualizando paquetes..."
apt-get update

echo "[Render Build] Instalando wkhtmltopdf..."
apt-get install -y wkhtmltopdf
