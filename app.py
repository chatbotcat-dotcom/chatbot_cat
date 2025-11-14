from flask import Flask, render_template, request, jsonify
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json
import os
import re

app = Flask(__name__)

# ------------------------------------------------------
#  CARGA DE CREDENCIALES (LOCAL vs RENDER)
# ------------------------------------------------------

def get_google_credentials():
    """
    Si estamos en Render → GOOGLE_CREDENTIALS (env variable)
    Si estamos en local → credenciales.json (archivo)
    """
    if "GOOGLE_CREDENTIALS" in os.environ:
        print("Usando credenciales desde variable de entorno (Render).")
        credentials_json = json.loads(os.environ["GOOGLE_CREDENTIALS"])
    else:
        print("Usando credenciales desde archivo local.")
        with open("credenciales.json") as f:
            credentials_json = json.load(f)

    creds = ServiceAccountCredentials.from_json_keyfile_dict(credentials_json, [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ])
    return gspread.authorize(creds)

client = get_google_credentials()

# ------------------------------------------------------
# LEER HOJAS DE GOOGLE SHEETS
# ------------------------------------------------------

cid_sheet = client.open("Codigos_de_Error_CAT_2").worksheet("CID")
fmi_sheet = client.open("Codigos_de_Error_CAT_2").worksheet("FMI")

cid_data = cid_sheet.get_all_records()
fmi_data = fmi_sheet.get_all_records()


# ------------------------------------------------------
# EXTRACCIÓN DE CÓDIGOS (FMI + CID)
# ------------------------------------------------------

def extraer_codigos(texto):
    texto = texto.upper().replace("-", " ").replace(".", " ")

    # Buscar FMI
    fmi = None
    match_fmi = re.search(r"FMI\s*(\d{1,2})", texto)
    if match_fmi:
        fmi = match_fmi.group(1)
    else:
        match_fmi_simple = re.search(r"\b(\d{1,2})\b", texto)
        if match_fmi_simple:
            fmi = match_fmi_simple.group(1)

    # Buscar CID
    cid = None
    match_cid = re.search(r"CID\s*(\d{1,4})", texto)
    if match_cid:
        cid = match_cid.group(1)
    else:
        match_cid_simple = re.findall(r"\b(\d{3,4})\b", texto)
        if match_cid_simple:
            cid = match_cid_simple[-1]

    return fmi, cid


# ------------------------------------------------------
# BUSCAR CID Y FMI
# ------------------------------------------------------

def buscar_cid(cid):
    for fila in cid_data:
        if str(fila["CDI"]).zfill(3) == str(cid).zfill(3):
            return fila
    return None

def buscar_fmi(fmi):
    for fila in fmi_data:
        if str(fila["FMI No."]).zfill(2) == str(fmi).zfill(2):
            return fila
    return None


# ------------------------------------------------------
# RESPUESTA TÉCNICA FORMATEADA (ESTILO CAT)
# ------------------------------------------------------

def generar_respuesta(fmi, cid):

    if not fmi and not cid:
        return "❌ No pude detectar FMI ni CID. Intenta algo como: 04 168"

    if fmi and not cid:
        return f"🔍 Detecté FMI {fmi}, pero falta el CID. Ejemplo: 04 168"

    if cid and not fmi:
        return f"🔍 Detecté CID {cid}, pero falta el FMI. Ejemplo: 04 168"

    info_cid = buscar_cid(cid)
    info_fmi = buscar_fmi(fmi)

    if not info_cid:
        return f"❌ CID {cid} no encontrado en la base de datos."
    if not info_fmi:
        return f"❌ FMI {fmi} no encontrado en la base de datos."

    # Datos del CID
    cid_desc = info_cid["Description"]
    mid = info_cid["MID"]
    mid_desc = info_cid["Description MID"]

    # Datos del FMI
    fmi_desc = info_fmi["Descripción de la falla"]
    causas = info_fmi["Posibles causas"]

    respuesta = f"""
🔧 <b>CÓDIGO DETECTADO</b><br>
• <b>FMI {str(fmi).zfill(2)}</b> — {fmi_desc}<br>
• <b>CID {str(cid).zfill(3)}</b> — {cid_desc}<br>
• <b>MID {mid}</b> — {mid_desc}<br><br>

📌 <b>DESCRIPCIÓN TÉCNICA</b><br>
El módulo <b>{mid_desc}</b> reporta que el componente <b>{cid_desc}</b> presenta:<br>
👉 <i>{fmi_desc}</i><br><br>

🛠 <b>POSIBLES CAUSAS</b><br>
{causas}<br><br>

¿Quieres explicación <b>simple</b>, <b>técnica</b> o <b>diagnóstico</b>?
"""
    return respuesta


# ------------------------------------------------------
# RUTAS FLASK
# ------------------------------------------------------

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/enviar", methods=["POST"])
def enviar():
    data = request.get_json()
    mensaje_usuario = data["mensaje"]

    fmi, cid = extraer_codigos(mensaje_usuario)
    respuesta = generar_respuesta(fmi, cid)

    return jsonify({"respuesta": respuesta})


# ------------------------------------------------------
# EJECUCIÓN LOCAL
# ------------------------------------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
