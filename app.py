from flask import Flask, render_template, request, jsonify, session, url_for
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json
import os
import re
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from datetime import datetime

app = Flask(__name__)
app.secret_key = "cat_chatbot_super_secreto_123"


# ------------------------------------------------------
#  CARGA DE CREDENCIALES (LOCAL vs RENDER)
# ------------------------------------------------------

def get_google_credentials():
    if "GOOGLE_CREDENTIALS" in os.environ:
        credentials_json = json.loads(os.environ["GOOGLE_CREDENTIALS"])
    else:
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
# EXTRAER FMI + CID
# ------------------------------------------------------

def extraer_codigos(texto):
    texto = texto.upper().replace("-", " ").replace(".", " ")

    fmi = None
    cid = None

    match_fmi = re.search(r"FMI\s*(\d{1,2})", texto)
    if match_fmi:
        fmi = match_fmi.group(1)
    else:
        m = re.findall(r"\b(\d{1,2})\b", texto)
        if m:
            fmi = m[-1]

    match_cid = re.search(r"CID\s*(\d{3,4})", texto)
    if match_cid:
        cid = match_cid.group(1)
    else:
        m = re.findall(r"\b(\d{3,4})\b", texto)
        if m:
            cid = m[0]

    return fmi, cid


# ------------------------------------------------------
# BUSCAR CID + FMI
# ------------------------------------------------------

def buscar_cid(cid):
    if not cid:
        return None
    for fila in cid_data:
        if str(fila["CDI"]).zfill(3) == str(cid).zfill(3):
            return fila
    return None


def buscar_fmi(fmi):
    if not fmi:
        return None
    for fila in fmi_data:
        if str(fila["FMI"]).zfill(2) == str(fmi).zfill(2):
            return fila
    return None


# ------------------------------------------------------
# RESPUESTA AL CÓDIGO
# ------------------------------------------------------

def generar_respuesta(fmi, cid):

    if not fmi or not cid:
        return "❌ No detecté un código válido. Ejemplo: <b>04 168</b>"

    info_cid = buscar_cid(cid)
    info_fmi = buscar_fmi(fmi)

    if not info_cid:
        return f"❌ CID <b>{cid}</b> no encontrado."
    if not info_fmi:
        return f"❌ FMI <b>{fmi}</b> no encontrado."

    cid_desc = info_cid["Description"]
    mid = info_cid["MID"]
    mid_desc = info_cid["Description MID"]

    fmi_desc = info_fmi["Description"]
    causas = info_fmi["Causes"]

    return f"""
🔧 <b>CÓDIGO DETECTADO</b><br>
• <b>FMI {fmi}</b> — {fmi_desc}<br>
• <b>CID {cid}</b> — {cid_desc}<br>
• <b>MID {mid}</b> — {mid_desc}<br><br>

📌 <b>DESCRIPCIÓN TÉCNICA</b><br>
<i>{fmi_desc}</i><br><br>

🛠 <b>POSIBLES CAUSAS</b><br>
{causas}
"""


# ------------------------------------------------------
# GENERAR PDF
# ------------------------------------------------------

def generar_pdf():
    modelo = session.get("modelo")
    serie = session.get("serie")
    codigos = session.get("codigos", [])

    reports_dir = os.path.join(app.static_folder, "reportes")
    os.makedirs(reports_dir, exist_ok=True)

    filename = f"Reporte_{serie}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    filepath = os.path.join(reports_dir, filename)

    c = canvas.Canvas(filepath, pagesize=letter)
    w, h = letter
    y = h - 50

    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, y, "REPORTE DE CÓDIGOS DE FALLA - CAT")
    y -= 40

    c.setFont("Helvetica", 12)
    c.drawString(50, y, f"Modelo: {modelo}")
    y -= 20
    c.drawString(50, y, f"Serie:  {serie}")
    y -= 40

    for idx, code in enumerate(codigos, start=1):

        if y < 80:
            c.showPage()
            c.setFont("Helvetica", 12)
            y = h - 50

        entrada = code["entrada"]
        fmi = code["fmi"]
        cid = code["cid"]
        fmi_desc = code.get("fmi_desc", "")
        cid_desc = code.get("cid_desc", "")
        mid = code.get("mid", "")
        mid_desc = code.get("mid_desc", "")
        causas = code.get("causas", "")

        c.setFont("Helvetica-Bold", 12)
        c.drawString(50, y, f"Código {idx}: {entrada}")
        y -= 18

        c.setFont("Helvetica", 11)
        c.drawString(60, y, f"FMI {fmi}: {fmi_desc}")
        y -= 14
        c.drawString(60, y, f"CID {cid}: {cid_desc}")
        y -= 14
        c.drawString(60, y, f"MID {mid}: {mid_desc}")
        y -= 14

        from textwrap import wrap
        for linea in wrap("Causas: " + causas, 90):
            c.drawString(60, y, linea)
            y -= 14

        y -= 20

    c.save()
    return url_for("static", filename=f"reportes/{filename}", _external=True)


# ------------------------------------------------------
# RUTA PRINCIPAL
# ------------------------------------------------------

@app.route("/")
def home():
    return render_template("index.html")


# ------------------------------------------------------
# MANEJO DEL CHAT
# ------------------------------------------------------

@app.route("/enviar", methods=["POST"])
def enviar():
    msg = request.get_json()["mensaje"].strip().lower()
    state = session.get("state")

    # Inicio solo con "hola"
    if not state:
        if msg not in ["hola", "hi", "hello", "buenas"]:
            return jsonify({
                "respuesta": "👋 Para iniciar escribe <b>hola</b>."
            })
        session["state"] = "modelo"
        return jsonify({
            "respuesta": "Perfecto. Dime el <b>MODELO</b> de la máquina."
        })

    # MODELO
    if state == "modelo":
        session["modelo"] = msg.upper()
        session["state"] = "serie"
        return jsonify({
            "respuesta": "Anotado. Ahora dime la <b>SERIE</b> de la máquina."
        })

    # SERIE
    if state == "serie":
        session["serie"] = msg.upper()
        session["state"] = "cantidad"
        return jsonify({
            "respuesta": "Perfecto. ¿Cuántos <b>códigos de falla</b> quieres analizar?"
        })

    # CANTIDAD
    if state == "cantidad":
        try:
            n = int(msg)
            if n <= 0:
                raise ValueError
        except:
            return jsonify({"respuesta": "Debes indicar un número válido."})

        session["cantidad"] = n
        session["codigos"] = []
        session["actual"] = 1
        session["state"] = "codigo"
        return jsonify({
            "respuesta": f"Envíame el <b>código 1</b> de {n} (Ej: 04 168)"
        })

    # CÓDIGOS UNO A UNO
    if state == "codigo":
        actual = session["actual"]
        total = session["cantidad"]

        fmi, cid = extraer_codigos(msg)
        detalle = generar_respuesta(fmi, cid)

        info = {
            "entrada": msg,
            "fmi": fmi,
            "cid": cid
        }

        c1 = buscar_cid(cid)
        c2 = buscar_fmi(fmi)

        if c1:
            info["cid_desc"] = c1["Description"]
            info["mid"] = c1["MID"]
            info["mid_desc"] = c1["Description MID"]

        if c2:
            info["fmi_desc"] = c2["Descripción de la falla"]
            info["causas"] = c2["Posibles causas"]

        codigos = session["codigos"]
        codigos.append(info)
        session["codigos"] = codigos

        if actual < total:
            session["actual"] += 1
            return jsonify({
                "respuesta":
                    detalle +
                    f"<br><br>Envíame el <b>código {actual + 1}</b> de {total}."
            })
        else:
            session["state"] = "pdf"
            return jsonify({
                "respuesta":
                    detalle +
                    "<br><br>¿Deseas generar un <b>PDF</b>? (sí/no)"
            })

    # PDF
    if state == "pdf":
        if msg in ["si", "sí", "yes", "y", "s"]:
            url_pdf = generar_pdf()
            session.clear()
            return jsonify({
                "respuesta": f"📄 Aquí está tu reporte:<br><a href='{url_pdf}' target='_blank'>Descargar PDF</a>"
            })
        else:
            session.clear()
            return jsonify({
                "respuesta": "Perfecto. Si necesitas analizar otra máquina, escribe <b>hola</b>."
            })

    # Reinicio seguro
    session.clear()
    return jsonify({"respuesta": "Reiniciemos la conversación. Escribe <b>hola</b>."})


# ------------------------------------------------------
# EJECUCIÓN LOCAL
# ------------------------------------------------------

if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=5000)
