from flask import Flask, render_template, request, jsonify
import pg8000
import re
import os

app = Flask(__name__)

# ============================================================
#  CONEXIÓN A POSTGRES (pg8000)
# ============================================================
import urllib.parse as urlparse

def get_conn():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL no está configurado.")

    url = urlparse.urlparse(db_url)

    return pg8000.connect(
        user=url.username,
        password=url.password,
        host=url.hostname,
        port=url.port,
        database=url.path.lstrip('/'),
        ssl_context=True
    )

# ============================================================
#  SESIONES DEL CHAT
# ============================================================
sesiones = {}

def obtener_sesion(user_id):
    if user_id not in sesiones:
        sesiones[user_id] = {
            "estado": "inicio",
            "model": None,
            "serial3": None,
            "enviar_segunda_bienvenida": True
        }
    return sesiones[user_id]

def resetear_sesion(user_id):
    if user_id in sesiones:
        del sesiones[user_id]

# ============================================================
#  PARSEO DE CÓDIGOS
# ============================================================
def extraer_codigo(texto: str):
    t = texto.upper().replace("-", " ").replace(".", " ")
    nums = re.findall(r"\d+", t)

    if len(nums) >= 3:
        mid, cid, fmi = nums[-3], nums[-2], nums[-1]
        return mid, cid, fmi

    if len(nums) == 2:
        cid, fmi = nums
        return None, cid, fmi

    return None, None, None

# ============================================================
#  PARSEO DE EVENTOS
# ============================================================
def extraer_evento(texto: str):
    t = texto.upper().replace("-", " ")
    match_evento = re.search(r"(?:E)?(\d{3,4})", t)
    if not match_evento:
        return None, None
    eid = f"E{match_evento.group(1)}"

    match_nivel = re.search(r"\((\d{1,2})\)", t)
    if match_nivel:
        level = match_nivel.group(1)
    else:
        match_nivel2 = re.search(r"NIVEL\s*(\d{1,2})", t)
        level = match_nivel2.group(1) if match_nivel2 else None

    return eid, level

# ============================================================
#  QUERIES
# ============================================================
def query_codigo(model, serial3, cid, fmi):
    sql = """
        SELECT description, causes, url
        FROM codigos_falla
        WHERE model = %s
          AND LEFT(serial, 3) = %s
          AND cid = %s
          AND fmi = %s
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(sql, (model, serial3, cid, fmi))

    cols = [col[0] for col in cur.description]
    rows = [dict(zip(cols, row)) for row in cur.fetchall()]

    cur.close()
    conn.close()
    return rows

def query_evento(model, serial3, eid, level):
    sql = """
        SELECT warning_description, url_main
        FROM eventos
        WHERE model = %s
          AND LEFT(serial, 3) = %s
          AND eid = %s
          AND level = %s
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(sql, (model, serial3, eid, level))

    cols = [col[0] for col in cur.description]
    rows = [dict(zip(cols, row)) for row in cur.fetchall()]

    cur.close()
    conn.close()
    return rows

# ============================================================
#  RUTA PRINCIPAL
# ============================================================
@app.route("/")
def home():
    return render_template("index.html")

# ============================================================
#  CHATBOT
# ============================================================
@app.route("/enviar", methods=["POST"])
def enviar():
    data = request.get_json()
    mensaje = data.get("mensaje", "").strip()
    user_id = "usuario_unico"

    ses = obtener_sesion(user_id)
    estado = ses["estado"]

    # =======================================================
    # FUNCIÓN QUE SOLUCIONA TU PROBLEMA
    # =======================================================
    def responder(texto):
        """Convierte saltos de línea a <br> para mostrar bien las listas."""
        return jsonify({"respuesta": texto.replace("\n", "<br>")})

    # =======================================================
    # 1) BIENVENIDA
    # =======================================================
    if estado == "inicio":
        respuesta1 = (
            "👋 Hola, soy <b>FerreyDoc</b>, tu asistente técnico CAT.\n\n"
            "Puedo ayudarte a interpretar <b>códigos de falla</b> (CID/FMI) "
            "y <b>eventos</b> (EID/Level) usando la base de datos técnica."
        )

        respuesta2 = (
            "Antes de continuar, ¿está de acuerdo en compartir información del equipo?:\n\n"
            "1️⃣ Sí, acepto compartir modelo y serie\n"
            "2️⃣ No, deseo cancelar"
        )

        ses["estado"] = "esperando_consentimiento"
        return responder(respuesta1 + "\n\n" + respuesta2)

    # =======================================================
    # 2) CONSENTIMIENTO
    # =======================================================
    if estado == "esperando_consentimiento":

        if mensaje == "1":
            ses["estado"] = "pidiendo_modelo"
            return responder(
                "Perfecto 🙌.\n\n"
                "Ingresa el <b>MODELO</b> de la máquina.\nEj: <b>950H</b>, <b>320D</b>."
            )

        if mensaje == "2":
            resetear_sesion(user_id)
            return responder("Entendido 👍. Si deseas retomar, escribe <b>hola</b>.")

        return responder("Por favor responde <b>1</b> o <b>2</b> 😊.")

    # =======================================================
    # 3) PIDIENDO MODELO
    # =======================================================
    if estado == "pidiendo_modelo":
        ses["model"] = mensaje.upper()
        ses["estado"] = "pidiendo_serie"

        return responder(
            f"Modelo registrado: <b>{ses['model']}</b> ✅\n\n"
            "Ahora ingresa los <b>primeros 3 dígitos de la serie</b>.\nEj: <b>4YS</b>"
        )

    # =======================================================
    # 4) PIDIENDO SERIE
    # =======================================================
    if estado == "pidiendo_serie":
        ses["serial3"] = mensaje[:3].upper()
        ses["estado"] = "menu_principal"

        return responder(
            "✔️ Datos registrados:\n"
            f"• Modelo: <b>{ses['model']}</b>\n"
            f"• Serie: <b>{ses['serial3']}</b>\n\n"
            "¿Qué deseas hacer?\n"
            "1️⃣ Códigos de falla\n"
            "2️⃣ Eventos\n"
            "3️⃣ Diferencia entre código y evento\n"
            "4️⃣ Inspección diaria\n"
            "5️⃣ Cambiar máquina\n"
            "6️⃣ Finalizar"
        )

    # =======================================================
    # 5) MENÚ PRINCIPAL
    # =======================================================
    if estado == "menu_principal":

        if mensaje == "1":
            ses["estado"] = "pidiendo_codigos"
            return responder(
                "🔧 Ingresa los <b>códigos de falla</b>.\n\n"
                "Formatos:\n"
                "• 168 04\n• 28 168 04\n• 168-04\n\n"
                "Puedes enviar varios separados por coma."
            )

        if mensaje == "2":
            ses["estado"] = "pidiendo_eventos"
            return responder(
                "📘 Ingresa los <b>eventos</b>.\n\n"
                "Formatos:\n"
                "• E0117\n• 0117 (2)\n• E0117 nivel 2\n\n"
                "Puedes enviar varios separados por coma."
            )

        if mensaje == "3":
            return responder(
                "🟡 Diferencias:\n\n"
                "🔧 <b>Código de falla (CID/FMI)</b> → Problema en sensor/actuador.\n\n"
                "📘 <b>Evento (EID/Level)</b> → Condición del sistema registrada.\n\n"
                "¿Qué deseas hacer ahora?\n1️⃣ Códigos\n2️⃣ Eventos\n6️⃣ Finalizar"
            )

        if mensaje == "4":
            return responder(
                "🛠️ <b>Inspección diaria</b>:\n"
                "• Revisar fluidos\n"
                "• Buscar fugas\n"
                "• Verificar parte eléctrica\n"
                "• Revisar estructura\n\n"
                "¿Qué deseas hacer?\n1️⃣ Códigos\n2️⃣ Eventos\n6️⃣ Finalizar"
            )

        if mensaje == "5":
            ses["estado"] = "pidiendo_modelo"
            ses["model"] = None
            ses["serial3"] = None
            return responder("Ingresa el <b>nuevo MODELO</b>.")

        if mensaje == "6":
            resetear_sesion(user_id)
            return responder("Gracias por usar FerreyDoc 🤝. Vuelve cuando quieras.")

        return responder("Elige una opción del <b>1</b> al <b>6</b>.")

    # =======================================================
    # 6) PROCESAR CÓDIGOS
    # =======================================================
    if estado == "pidiendo_codigos":
        model = ses["model"]
        serial3 = ses["serial3"]
        codigos = mensaje.split(",")
        respuestas = []

        for raw in codigos:
            raw = raw.strip()
            if not raw:
                continue

            mid, cid, fmi = extraer_codigo(raw)

            if not cid or not fmi:
                respuestas.append(f"❌ No pude interpretar <code>{raw}</code>.")
                continue

            filas = query_codigo(model, serial3, cid, fmi)

            if not filas:
                respuestas.append(
                    f"❌ No encontré resultados para CID {cid} / FMI {fmi} (<code>{raw}</code>)."
                )
                continue

            fila = filas[0]

            desc = fila["description"] or "Sin descripción."
            causas = fila["causes"] or "Sin causas registradas."
            url = fila["url"] or "Sin URL disponible."

            respuestas.append(
                f"🔧 <b>Código:</b> <code>{raw}</code>\n\n"
                f"<b>Descripción:</b>\n{desc}\n\n"
                f"<b>Causas:</b>\n{causas}\n\n"
                f"<b>Más información:</b>\n<a href='{url}' target='_blank'>{url}</a>\n"
            )

        ses["estado"] = "menu_principal"

        respuestas.append(
            "¿Qué deseas hacer?\n1️⃣ Más códigos\n2️⃣ Eventos\n5️⃣ Cambiar máquina\n6️⃣ Finalizar"
        )

        return responder("\n\n".join(respuestas))

    # =======================================================
    # 7) PROCESAR EVENTOS
    # =======================================================
    if estado == "pidiendo_eventos":
        model = ses["model"]
        serial3 = ses["serial3"]
        eventos = mensaje.split(",")
        respuestas = []

        for raw in eventos:
            raw = raw.strip()
            if not raw:
                continue

            eid, level = extraer_evento(raw)
            level = level or "2"

            filas = query_evento(model, serial3, eid, level)

            if not filas:
                respuestas.append(
                    f"❌ No encontré información para <b>{eid}</b> nivel <b>{level}</b> (<code>{raw}</code>)."
                )
                continue

            fila = filas[0]

            desc = fila["warning_description"] or "Sin descripción."
            url = fila["url_main"] or "Sin URL."

            respuestas.append(
                f"📘 <b>Evento:</b> <code>{raw}</code>\n\n"
                f"<b>Descripción:</b>\n{desc}\n\n"
                f"<b>Más información:</b> <a href='{url}' target='_blank'>{url}</a>\n"
            )

        ses["estado"] = "menu_principal"

        respuestas.append(
            "¿Qué deseas hacer?\n1️⃣ Códigos\n2️⃣ Más eventos\n5️⃣ Cambiar máquina\n6️⃣ Finalizar"
        )

        return responder("\n\n".join(respuestas))

    # =======================================================
    # 8) FALLBACK
    # =======================================================
    return responder("No entendí 😅. Escribe <b>hola</b> para reiniciar.")

# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
