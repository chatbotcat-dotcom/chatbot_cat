# actualizado 2025-11-27

from flask import Flask, render_template, request, jsonify
import psycopg2
from psycopg2.extras import RealDictCursor
import re
import os

app = Flask(__name__)

# ============================================================
#  CONEXIÓN A POSTGRES (psycopg2, sin async)
# ============================================================

def get_conn():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL no está configurado.")
    return psycopg2.connect(db_url, sslmode="require")

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
            "enviar_segunda_bienvenida": True   # para dividir mensaje de bienvenida
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

    # Buscar número de evento: 3 o 4 dígitos, con o sin 'E'
    match_evento = re.search(r"(?:E)?(\d{3,4})", t)
    if not match_evento:
        return None, None
    eid = f"E{match_evento.group(1)}"

    # Buscar nivel: entre paréntesis o como "nivel X"
    match_nivel = re.search(r"\((\d{1,2})\)", t)
    if match_nivel:
        level = match_nivel.group(1)
    else:
        match_nivel2 = re.search(r"NIVEL\s*(\d{1,2})", t)
        level = match_nivel2.group(1) if match_nivel2 else None

    return eid, level


# ============================================================
#  QUERIES A BD
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
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(sql, (model, serial3, cid, fmi))
    rows = cur.fetchall()
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
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(sql, (model, serial3, eid, level))
    rows = cur.fetchall()
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
    mensaje_lower = mensaje.lower()

    # ========================================================
    # 1) MENSAJE DE BIENVENIDA (DOS PARTES)
    # ========================================================
    if estado == "inicio":
        respuesta1 = (
            "👋 Hola, soy <b>FerreyDoc</b>, tu asistente técnico CAT.\n\n"
            "Puedo ayudarte a interpretar <b>códigos de falla</b> (CID/FMI) "
            "y <b>eventos</b> (EID/Level) utilizando la base de datos técnica."
        )

        respuesta2 = (
            "Antes de continuar, ¿Está de acuerdo en compartir infomración sobre su equipo?:\n\n"
            "1️⃣ Sí, acepto compartir modelo y serie\n"
            "2️⃣ No, deseo cancelar"
        )

        ses["estado"] = "esperando_consentimiento"
        return jsonify({"respuesta": respuesta1 + "\n\n" + respuesta2})

    # ========================================================
    # 2) CONSENTIMIENTO — OPCIONES 1 / 2
    # ========================================================
    if estado == "esperando_consentimiento":

        if mensaje == "1":
            ses["estado"] = "pidiendo_modelo"
            return jsonify({
                "respuesta":
                "Perfecto 🙌.\n\n"
                "Por favor indícame el <b>MODELO</b> de la máquina.\n"
                "Ejemplo: <b>950H</b>, <b>320D</b>, <b>777G</b>."
            })

        if mensaje == "2":
            resetear_sesion(user_id)
            return jsonify({
                "respuesta": "Entendido 👍. Si deseas retomar luego, solo escribe <b>hola</b>."
            })

        return jsonify({"respuesta": "Por favor, responde <b>1</b> o <b>2</b> 😊."})

    # ========================================================
    # 3) PIDIENDO MODELO
    # ========================================================
    if estado == "pidiendo_modelo":
        ses["model"] = mensaje.upper()
        ses["estado"] = "pidiendo_serie"

        return jsonify({
            "respuesta": (
                f"Modelo registrado: <b>{ses['model']}</b> ✅\n\n"
                "Ahora ingresa los <b>primeros 3 dígitos de la serie</b>.\n"
                "Ejemplo: <b>4YS</b>, <b>C7R</b>, <b>KJG</b>."
            )
        })

    # ========================================================
    # 4) PIDIENDO SERIE
    # ========================================================
    if estado == "pidiendo_serie":
        ses["serial3"] = mensaje[:3].upper()
        ses["estado"] = "menu_principal"

        return jsonify({
            "respuesta": (
                "✔️ Datos registrados:\n"
                f"• Modelo: <b>{ses['model']}</b>\n"
                f"• Serie: <b>{ses['serial3']}</b>\n\n"
                "¿Qué deseas hacer ahora?\n\n"
                "1️⃣ Interpretar códigos de falla\n"
                "2️⃣ Interpretar eventos\n"
                "3️⃣ Diferencia entre código y evento\n"
                "4️⃣ Recomendaciones de inspección diaria\n"
                "5️⃣ Cambiar de máquina\n"
                "6️⃣ Finalizar conversación"
            )
        })

    # ========================================================
    # 5) MENÚ PRINCIPAL
    # ========================================================
    if estado == "menu_principal":

        if mensaje == "1":
            ses["estado"] = "pidiendo_codigos"
            return jsonify({
                "respuesta": (
                    "🔧 Ingresa los <b>códigos de falla</b>.\n\n"
                    "Formatos permitidos:\n"
                    "• <code>168 04</code>\n"
                    "• <code>28 168 04</code>\n"
                    "• <code>168-04</code>\n\n"
                    "Puedes ingresar varios separados por coma."
                )
            })

        if mensaje == "2":
            ses["estado"] = "pidiendo_eventos"
            return jsonify({
                "respuesta": (
                    "📘 Ingresa los <b>eventos</b>.\n\n"
                    "Formatos permitidos:\n"
                    "• <code>E0117</code>\n"
                    "• <code>0117 (2)</code>\n"
                    "• <code>E0117 nivel 2</code>\n\n"
                    "Puedes ingresar varios separados por coma."
                )
            })

        if mensaje == "3":
            return jsonify({
                "respuesta": (
                    "🟡 Te explico:\n\n"
                    "🔧 <b>Código de falla (CID/FMI)</b>\n"
                    "→ Indica una condición anómala en un <b>sensor o actuador</b>.\n\n"
                    "📘 <b>Evento (EID/Level)</b>\n"
                    "→ Registra una <b>condición de operación</b> que afecta al sistema.\n\n"
                    "¿Qué deseas hacer ahora?\n"
                    "1️⃣ Códigos de falla\n"
                    "2️⃣ Eventos\n"
                    "6️⃣ Finalizar"
                )
            })

        if mensaje == "4":
            return jsonify({
                "respuesta": (
                    "🛠️ <b>Inspección diaria recomendada</b>\n"
                    "• Revisar niveles de fluidos\n"
                    "• Buscar fugas visibles\n"
                    "• Verificar funcionamiento eléctrico\n"
                    "• Revisar estado estructural\n\n"
                    "¿Qué deseas hacer?\n"
                    "1️⃣ Códigos de falla\n"
                    "2️⃣ Eventos\n"
                    "6️⃣ Finalizar"
                )
            })

        if mensaje == "5":
            ses["estado"] = "pidiendo_modelo"
            ses["model"] = None
            ses["serial3"] = None
            return jsonify({"respuesta": "Por favor ingresa el <b>nuevo MODELO</b>."})

        if mensaje == "6":
            resetear_sesion(user_id)
            return jsonify({"respuesta": "Gracias por usar FerreyDoc 🤝. ¡Vuelve cuando quieras!"})

        return jsonify({"respuesta": "Elige una opción del <b>1</b> al <b>6</b>."})

    # ========================================================
    # 6) PROCESAR CÓDIGOS
    # ========================================================
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
                    f"❌ No encontré resultados para CID {cid} / FMI {fmi} "
                    f"(<code>{raw}</code>)."
                )
                continue

            fila = filas[0]

            desc = fila["description"] or "Sin descripción."
            causas = fila["causes"] or "Sin causas registradas."
            url = fila["url"] or "Sin URL disponible."

            respuestas.append(
                f"🔧 <b>Código analizado:</b> <code>{raw}</code>\n\n"
                f"<b>Descripción:</b>\n{desc}\n\n"
                f"<b>Causas posibles:</b>\n{causas}\n\n"
                f"<b>Para más información o para realizar Test de descarte de causas menores ingresar por favor a:</b>\n<a href='{url}' target='_blank'>{url}</a>\n"

            )

        ses["estado"] = "menu_principal"

        respuestas.append(
            "¿Qué deseas hacer ahora?\n"
            "1️⃣ Más códigos\n"
            "2️⃣ Eventos\n"
            "5️⃣ Cambiar máquina\n"
            "6️⃣ Finalizar"
        )

        return jsonify({"respuesta": "\n\n".join(respuestas)})

    # ========================================================
    # 7) PROCESAR EVENTOS
    # ========================================================
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
                    f"❌ No encontré información para <b>{eid}</b> nivel <b>{level}</b> "
                    f"(<code>{raw}</code>)."
                )
                continue

            fila = filas[0]

            desc = fila["warning_description"] or "Sin descripción registrada."
            url = fila["url_main"] or "Sin URL disponible."

            respuestas.append(
                f"📘 <b>Evento analizado:</b> <code>{raw}</code>\n\n"
                f"<b>Descripción:</b>\n{desc}\n\n"
                f"<b>Para más información por favor consultar a:</b> <a href='{url}' target='_blank'>{url}</a>\n"

            )

        ses["estado"] = "menu_principal"

        respuestas.append(
            "¿Qué deseas hacer ahora?\n"
            "1️⃣ Códigos de falla\n"
            "2️⃣ Más eventos\n"
            "5️⃣ Cambiar máquina\n"
            "6️⃣ Finalizar"
        )

        return jsonify({"respuesta": "\n\n".join(respuestas)})

    # ========================================================
    # 8) FALLBACK
    # ========================================================
    return jsonify({"respuesta": "No entendí 😅. Escribe <b>hola</b> para reiniciar."})


# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
