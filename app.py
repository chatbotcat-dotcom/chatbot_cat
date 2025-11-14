from flask import Flask, render_template, request, jsonify
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import re

app = Flask(__name__)

# -----------------------------------------
#        CONFIGURACIÓN GOOGLE SHEETS
# -----------------------------------------
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

creds = ServiceAccountCredentials.from_json_keyfile_name("credenciales.json", scope)
client = gspread.authorize(creds)

# Abrir las dos hojas correctas
cid_sheet = client.open("Codigos_de_Error_CAT_2").worksheet("CID")
fmi_sheet = client.open("Codigos_de_Error_CAT_2").worksheet("FMI")

# Convertir en listas de diccionarios
cid_data = cid_sheet.get_all_records()
fmi_data = fmi_sheet.get_all_records()


# -----------------------------------------
#     FUNCIÓN PARA EXTRAER FMI + CID
# -----------------------------------------
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


# -----------------------------------------
#     BUSCAR EN LA HOJA CID
# -----------------------------------------
def buscar_cid(cid):
    for fila in cid_data:
        if str(fila["CDI"]).zfill(3) == str(cid).zfill(3):
            return fila
    return None


# -----------------------------------------
#     BUSCAR EN LA HOJA FMI
# -----------------------------------------
def buscar_fmi(fmi):
    for fila in fmi_data:
        if str(fila["FMI"]).zfill(2) == str(fmi).zfill(2):
            return fila
    return None


# -----------------------------------------
#     GENERAR RESPUESTA PROFESIONAL CAT
# -----------------------------------------
def generar_respuesta(fmi, cid):

    # Validaciones
    if not fmi and not cid:
        return "❌ No pude detectar ningún FMI ni CID. Intenta algo como: 04 168"

    if fmi and not cid:
        return "🔎 Detecté el FMI **{}**, pero falta el CID (componente). Escríbeme algo como: 04 168".format(fmi)

    if cid and not fmi:
        return "🔎 Detecté el CID **{}**, pero falta el FMI (modo de falla). Escríbeme algo como: 04 168".format(cid)

    # Buscar datos
    info_cid = buscar_cid(cid)
    info_fmi = buscar_fmi(fmi)

    if not info_cid:
        return f"❌ El CID {cid} no existe en la base de datos."

    if not info_fmi:
        return f"❌ El FMI {fmi} no existe en la base de datos."

    # Extraer datos
    cid_desc = info_cid["Description"]
    mid = info_cid["MID"]
    mid_desc = info_cid["Description MID"]

    fmi_desc = info_fmi["Description"]
    causas = info_fmi["Causes"]

    # ------------------------------
    #      RESPUESTA FORMADA
    # ------------------------------
    respuesta = f"""
🔧 <b>CÓDIGO DETECTADO</b><br>
• <b>FMI {str(fmi).zfill(2)}</b> — {fmi_desc}<br>
• <b>CID {str(cid).zfill(3)}</b> — {cid_desc}<br>
• <b>MID {mid}</b> — {mid_desc}<br><br>

📌 <b>DESCRIPCIÓN TÉCNICA</b><br>
El módulo <b>{mid_desc}</b> reporta que el componente <b>{cid_desc}</b> presenta: <br>
👉 <i>{fmi_desc}</i><br><br>

🛠 <b>POSIBLES CAUSAS</b><br>
{causas}<br><br>

¿Deseas una explicación <b>simple</b>, <b>técnica</b> o los <b>pasos de diagnóstico</b>?
"""

    return respuesta


# -----------------------------------------
#      RUTA PRINCIPAL
# -----------------------------------------
@app.route("/")
def home():
    return render_template("index.html")


# -----------------------------------------
#      PROCESAR MENSAJE DEL CHAT
# -----------------------------------------
@app.route("/enviar", methods=["POST"])
def enviar():
    data = request.get_json()
    msg = data["mensaje"]

    fmi, cid = extraer_codigos(msg)
    respuesta = generar_respuesta(fmi, cid)

    return jsonify({"respuesta": respuesta})


# -----------------------------------------
#      EJECUCIÓN LOCAL
# -----------------------------------------
if __name__ == "__main__":
    app.run(port=5000, debug=True)
