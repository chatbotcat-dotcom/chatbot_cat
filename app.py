from flask import Flask, render_template, request, jsonify, Response
import pg8000
import re
import os
import base64
from datetime import datetime
import urllib.parse as urlparse

# ========== NUEVO (XHTML2PDF) ==========
from xhtml2pdf import pisa
from io import BytesIO

app = Flask(__name__)

# ============================================================
#  CONEXIÓN A POSTGRES (pg8000)
# ============================================================
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
#  SESIONES
# ============================================================
sesiones = {}

def obtener_sesion(user_id):
    if user_id not in sesiones:
        sesiones[user_id] = {
            "estado": "inicio",
            "model": None,
            "serial3": None,
            "mant_maquina": None,
            "mant_intervalo": None,
            "mant_intervalos_lista": [],
            "reporte_codigos": [],
            "reporte_eventos": []
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
        return nums[-3], nums[-2], nums[-1]

    if len(nums) == 2:
        return None, nums[0], nums[1]

    return None, None, None

# ============================================================
#  PARSEO DE EVENTOS (NUEVO FORMATO ÚNICO)
# ============================================================
def extraer_evento(texto: str):
    """
    Formato único permitido: E + números + (nivel)
    Ejemplo: E1234(2)  con nivel 1, 2 o 3
    """
    t = texto.strip().upper()
    m = re.fullmatch(r"E(\d+)\(([123])\)", t)
    if not m:
        return None, None

    eid = f"E{m.group(1)}"   # E + números
    level = m.group(2)       # 1, 2 o 3
    return eid, level

# ============================================================
#  PLAN DE MANTENIMIENTO
# ============================================================
PLAN_MANTENIMIENTO = {
    # =======================================================
    # RODILLO
    # =======================================================
    "rodillo": {
        "nombre": "Rodillo",
        "link": "https://sis2.cat.com/#/detail?keyword=Maintenance+Interval+Schedule&infoType=13&serviceMediaNumber=M0165439&serviceIeSystemControlNumber=i09996110&tab=service",
        "intervalos": {
            "diario_10h": {
                "label": "Cada día / 10 horas de servicio",
                "bloques": {
                    "🛡️ Seguridad y alarmas": [
                        "Probar la alarma de retroceso",
                        "Inspeccionar el cinturón de seguridad"
                    ],
                    "🛢️ Motor y enfriamiento": [
                        "Revisar nivel de refrigerante del sistema de enfriamiento",
                        "Revisar nivel de aceite del motor"
                    ],
                    "⛽ Combustible": [
                        "Drenar separador de agua del sistema de combustible"
                    ]
                }
            },
            "50h": {
                "label": "50 horas de servicio",
                "bloques": {
                    "🛢️ Motor": [
                        "Cambiar aceite del motor y filtro según indicaciones"
                    ]
                }
            },
            "250h": {
                "label": "250 horas de servicio",
                "bloques": {
                    "🧮 Sistema hidráulico": [
                        "Obtener muestra de aceite del sistema hidráulico"
                    ]
                }
            },
            "500h": {
                "label": "500 horas de servicio",
                "bloques": {
                    "🧮 Sistema hidráulico": [
                        "Reemplazar filtro de aceite del sistema hidráulico"
                    ]
                }
            },
            "1000h": {
                "label": "1000 horas de servicio",
                "bloques": {
                    "🛞 Ejes y mandos finales": [
                        "Cambiar aceite de ejes y mandos finales según manual"
                    ]
                }
            },
            "2000h": {
                "label": "2000 horas de servicio",
                "bloques": {
                    "🧊 Sistema de enfriamiento": [
                        "Obtener muestra de refrigerante del sistema de enfriamiento"
                    ]
                }
            },
            "3000h": {
                "label": "3000 horas de servicio",
                "bloques": {
                    "🧮 Sistema hidráulico": [
                        "Reemplazar filtro de aceite del sistema hidráulico (retorno)"
                    ]
                }
            },
            "6000h": {
                "label": "6000 horas de servicio o cada 3 años",
                "bloques": {
                    "🧮 Sistema hidráulico": [
                        "Cambiar aceite del sistema hidráulico"
                    ],
                    "🧊 Sistema de enfriamiento": [
                        "Agregar prolongador de vida útil del refrigerante (ELC)"
                    ]
                }
            },
            "largo_plazo": {
                "label": "Intervalos largos (3 años, 5000 h, 10 000 h, 12 000 h y tareas condicionales)",
                "bloques": {
                    "🛡️ Seguridad": [
                        "Reemplazar cinturón de seguridad cada 3 años"
                    ],
                    "🧊 Sistema de enfriamiento": [
                        "Cambiar refrigerante ELC cada 12 000 horas o 6 años"
                    ],
                    "🔁 Tareas cuando sea necesario": [
                        "Inspeccionar filtro de aire de cabina",
                        "Revisar nivel de electrolito de baterías",
                        "Limpiar núcleos de enfriamiento"
                    ]
                }
            },
            "todo": {
                "label": "Resumen general del programa de mantenimiento",
                "bloques": {
                    "📋 Recordatorios generales": [
                        "Utilizar horas de servicio, consumo de combustible, kilometraje o tiempo de calendario (lo que ocurra primero) para definir los intervalos.",
                        "Antes de efectuar las tareas de un intervalo consecutivo, realizar también las tareas de los intervalos anteriores.",
                        "Seguir siempre las instrucciones de seguridad, advertencias y regulaciones de emisiones indicadas por el fabricante."
                    ]
                }
            }
        }
    },

    # =======================================================
    # CARGADOR
    # =======================================================
    "cargador": {
        "nombre": "Cargador de ruedas",
        "link": "https://sis2.cat.com/#/detail?keyword=Maintenance+Interval+Schedule&infoType=13&serviceMediaNumber=M0080860&serviceIeSystemControlNumber=i07103985&tab=service",
        "intervalos": {
            "diario_10h": {
                "label": "Cada día / 10 horas de servicio",
                "bloques": {
                    "🛢️ Motor y enfriamiento": [
                        "Revisar nivel de aceite del motor",
                        "Revisar nivel de refrigerante del sistema de enfriamiento"
                    ],
                    "🛞 Neumáticos y estructura": [
                        "Inspeccionar neumáticos",
                        "Revisar pasadores y puntos de articulación"
                    ]
                }
            },
            "50h": {
                "label": "50 horas de servicio",
                "bloques": {
                    "🧮 Sistema hidráulico": [
                        "Revisar nivel de aceite hidráulico"
                    ]
                }
            },
            "250h": {
                "label": "250 horas de servicio",
                "bloques": {
                    "🛢️ Motor": [
                        "Cambiar aceite y filtro del motor"
                    ]
                }
            },
            "500h": {
                "label": "500 horas de servicio",
                "bloques": {
                    "🛞 Ejes y mandos finales": [
                        "Obtener muestra de aceite de mandos finales y ejes"
                    ]
                }
            },
            "1000h": {
                "label": "1000 horas de servicio",
                "bloques": {
                    "🧮 Sistema hidráulico": [
                        "Reemplazar filtro de aceite del sistema hidráulico"
                    ]
                }
            },
            "2000h": {
                "label": "2000 horas de servicio",
                "bloques": {
                    "🧊 Sistema de enfriamiento": [
                        "Obtener muestra de refrigerante del sistema de enfriamiento"
                    ]
                }
            },
            "3000h": {
                "label": "3000 horas de servicio",
                "bloques": {
                    "🧊 Sistema de enfriamiento": [
                        "Reemplazar termostato del agua",
                        "Cambiar aceite de cajas y mandos finales según instrucciones"
                    ]
                }
            },
            "6000h": {
                "label": "6000 horas de servicio o cada 3 años",
                "bloques": {
                    "🧮 Sistema hidráulico": [
                        "Cambiar aceite del sistema hidráulico"
                    ],
                    "🧊 Sistema de enfriamiento": [
                        "Agregar prolongador de vida útil de refrigerante (ELC)"
                    ]
                }
            },
            "largo_plazo": {
                "label": "Intervalos largos (3 años, 5000 h, 10 000 h, 12 000 h y tareas condicionales)",
                "bloques": {
                    "🛡️ Seguridad": [
                        "Reemplazar cinturón de seguridad cada 3 años"
                    ],
                    "🧪 Sistema de emisiones y combustible": [
                        "Reemplazar filtro de fluido de escape diésel (cada 5 000 horas)",
                        "Reemplazar filtros del múltiple de DEF (cada 10 000 horas)"
                    ],
                    "🔁 Tareas cuando sea necesario": [
                        "Inspeccionar/reemplazar filtros de aire de cabina",
                        "Limpiar núcleos de enfriamiento",
                        "Llenar fluido de escape diésel"
                    ]
                }
            },
            "todo": {
                "label": "Resumen general del programa de mantenimiento",
                "bloques": {
                    "📋 Recordatorios generales": [
                        "Antes de efectuar las tareas de un intervalo consecutivo, realizar también las tareas de los intervalos anteriores.",
                        "Seguir siempre las instrucciones de seguridad, advertencias y regulaciones de emisiones indicadas por el fabricante."
                    ]
                }
            }
        }
    },

    # =======================================================
    # EXCAVADORA
    # =======================================================
    "excavadora": {
        "nombre": "Excavadora",
        "link": "https://sis2.cat.com/#/detail?keyword=Maintenance+Interval+Schedule&infoType=13&serviceMediaNumber=M0082496&serviceIeSystemControlNumber=i07103987&tab=service",
        "intervalos": {
            "diario_10h": {
                "label": "Cada día / 10 horas de servicio",
                "bloques": {
                    "🛢️ Motor y enfriamiento": [
                        "Revisar nivel de aceite del motor",
                        "Revisar nivel de refrigerante del sistema de enfriamiento"
                    ],
                    "⛽ Combustible": [
                        "Drenar separador de agua del sistema de combustible"
                    ],
                    "🧮 Sistema hidráulico": [
                        "Revisar nivel de aceite del sistema hidráulico"
                    ],
                    "🛡️ Seguridad": [
                        "Probar indicadores y medidores",
                        "Inspeccionar cinturón de seguridad"
                    ]
                }
            },
            "50h": {
                "label": "50 horas de servicio",
                "bloques": {
                    "🛞 Tren de rodaje": [
                        "Inspeccionar tensión de la cadena de orugas"
                    ]
                }
            },
            "250h": {
                "label": "250 horas de servicio",
                "bloques": {
                    "🛢️ Motor": [
                        "Cambiar aceite y filtro del motor"
                    ]
                }
            },
            "500h": {
                "label": "500 horas de servicio",
                "bloques": {
                    "🧮 Sistema hidráulico": [
                        "Obtener muestra de aceite del sistema hidráulico"
                    ]
                }
            },
            "1000h": {
                "label": "1000 horas de servicio",
                "bloques": {
                    "🧮 Sistema hidráulico": [
                        "Reemplazar filtro de aceite del sistema hidráulico"
                    ]
                }
            },
            "2000h": {
                "label": "2000 horas de servicio",
                "bloques": {
                    "🧊 Sistema de enfriamiento": [
                        "Obtener muestra de refrigerante del sistema de enfriamiento"
                    ]
                }
            },
            "2500h": {
                "label": "2500 horas de servicio",
                "bloques": {
                    "🛢️ Motor": [
                        "Revisar juego de válvulas del motor"
                    ]
                }
            },
            "3000h": {
                "label": "3000 horas de servicio",
                "bloques": {
                    "🧮 Sistema hidráulico": [
                        "Reemplazar filtro de aceite del sistema hidráulico (retorno)"
                    ]
                }
            },
            "6000h": {
                "label": "6000 horas de servicio o cada 3 años",
                "bloques": {
                    "🧊 Sistema de enfriamiento": [
                        "Agregar prolongador de vida útil del refrigerante (ELC)"
                    ]
                }
            },
            "largo_plazo": {
                "label": "Intervalos largos (10 000 h, 12 000 h y tareas anuales)",
                "bloques": {
                    "🧊 Sistema de enfriamiento y refrigerante": [
                        "Obtener muestra de refrigerante cada año",
                        "Cambiar refrigerante ELC cada 12 000 horas o 6 años"
                    ],
                    "🧪 Sistema de emisiones DEF": [
                        "Reemplazar filtros del múltiple de DEF cada 10 000 horas"
                    ],
                    "🔁 Tareas cuando sea necesario": [
                        "Limpiar/revisar batería",
                        "Reemplazar batería o cables si es necesario",
                        "Limpiar filtro de aire de la cabina"
                    ]
                }
            },
            "todo": {
                "label": "Resumen general del programa de mantenimiento",
                "bloques": {
                    "📋 Recordatorios generales": [
                        "Utilizar horas de servicio, combustible, kilometraje o tiempo para definir los intervalos.",
                        "Antes de efectuar las tareas de un intervalo consecutivo, realizar también las tareas de los intervalos anteriores.",
                        "Seguir siempre las instrucciones de seguridad, advertencias y regulaciones de emisiones indicadas por el fabricante."
                    ]
                }
            }
        }
    },

    # =======================================================
    # TRACTOR
    # =======================================================
    "tractor": {
        "nombre": "Tractor",
        "link": "https://sis2.cat.com/#/detail?keyword=Maintenance+Interval+Schedule&infoType=13&serviceMediaNumber=M0082498&serviceIeSystemControlNumber=i07103988&tab=service",
        "intervalos": {
            "diario_10h": {
                "label": "Cada día / 10 horas de servicio",
                "bloques": {
                    "🛢️ Motor y enfriamiento": [
                        "Revisar nivel de aceite del motor",
                        "Revisar nivel de refrigerante del sistema de enfriamiento"
                    ],
                    "🛡️ Seguridad": [
                        "Inspeccionar cinturón de seguridad",
                        "Verificar funcionamiento de alarmas"
                    ]
                }
            },
            "50h": {
                "label": "50 horas de servicio",
                "bloques": {
                    "🛞 Tren de rodaje": [
                        "Inspeccionar tensión de la cadena y rodillos"
                    ]
                }
            },
            "250h": {
                "label": "250 horas de servicio",
                "bloques": {
                    "🛢️ Motor": [
                        "Cambiar aceite y filtro del motor"
                    ]
                }
            },
            "500h": {
                "label": "500 horas de servicio",
                "bloques": {
                    "🧮 Sistema hidráulico": [
                        "Obtener muestra de aceite del sistema hidráulico"
                    ]
                }
            },
            "1000h": {
                "label": "1000 horas de servicio",
                "bloques": {
                    "🧮 Sistema hidráulico": [
                        "Reemplazar filtro de aceite del sistema hidráulico"
                    ]
                }
            },
            "2000h": {
                "label": "2000 horas de servicio",
                "bloques": {
                    "🧊 Sistema de enfriamiento": [
                        "Obtener muestra de refrigerante del sistema de enfriamiento"
                    ]
                }
            },
            "3000h": {
                "label": "3000 horas de servicio",
                "bloques": {
                    "🧮 Sistema hidráulico": [
                        "Reemplazar filtro de aceite del sistema hidráulico (retorno)"
                    ]
                }
            },
            "6000h": {
                "label": "6000 horas de servicio o cada 3 años",
                "bloques": {
                    "🧮 Sistema hidráulico": [
                        "Cambiar aceite del sistema hidráulico"
                    ],
                    "🧊 Sistema de enfriamiento": [
                        "Agregar prolongador de vida útil del refrigerante (ELC)"
                    ]
                }
            },
            "largo_plazo": {
                "label": "Intervalos largos (3 años, 5000 h, 10 000 h, 12 000 h y tareas condicionales)",
                "bloques": {
                    "🛡️ Seguridad": [
                        "Reemplazar cinturón de seguridad cada 3 años"
                    ],
                    "🧊 Sistema de enfriamiento": [
                        "Cambiar refrigerante ELC cada 12 000 horas o 6 años"
                    ],
                    "🔁 Tareas cuando sea necesario": [
                        "Revisar tren de rodaje",
                        "Inspeccionar Estructura de Protección en Caso de Vuelcos (ROPS)",
                        "Limpiar radiador, posenfriador y núcleos del enfriador de aceite"
                    ]
                }
            },
            "todo": {
                "label": "Resumen general del programa de mantenimiento",
                "bloques": {
                    "📋 Recordatorios generales": [
                        "Antes de efectuar las tareas de un intervalo consecutivo, realizar también las tareas de los intervalos anteriores.",
                        "Seguir siempre las instrucciones de seguridad, advertencias y regulaciones de emisiones indicadas por el fabricante."
                    ]
                }
            }
        }
    }
}

# ============================================================
#  QUERIES A BASE DE DATOS
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
    rows = [dict(zip([c[0] for c in cur.description], r)) for r in cur.fetchall()]
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
    rows = [dict(zip([c[0] for c in cur.description], r)) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows

# ============================================================
# CONTACTOS PARA PDF
# ============================================================
CONTACTOS_SOPORTE = [
    {"zona": "Piura", "correo": "servicios.piura@empresa.com", "telefono": "+51 999 111 111"},
    {"zona": "Trujillo", "correo": "servicios.trujillo@empresa.com", "telefono": "+51 999 222 222"},
    {"zona": "Lambayeque", "correo": "servicios.lambayeque@empresa.com", "telefono": "+51 999 333 333"},
    {"zona": "Chimbote", "correo": "servicios.chimbote@empresa.com", "telefono": "+51 999 444 444"},
    {"zona": "Huaraz", "correo": "servicios.huaraz@empresa.com", "telefono": "+51 999 555 555"},
    {"zona": "Cajamarca", "correo": "servicios.cajamarca@empresa.com", "telefono": "+51 999 666 666"},
]

# ============================================================
#  GENERAR PDF (XHTML2PDF)
# ============================================================
def generar_pdf(html_string):
    pdf_bytes = BytesIO()
    pisa.CreatePDF(html_string, dest=pdf_bytes)
    return pdf_bytes.getvalue()

# ============================================================
#  RUTA PRINCIPAL
# ============================================================
@app.route("/")
def home():
    return render_template("index.html")

# ============================================================
#  RUTA PDF DIRECTO
# ============================================================
@app.route("/generar_reporte", methods=["POST"])
def generar_reporte():
    data = request.get_json()

    html = render_template(
        "reporte_diagnostico.html",
        modelo=data.get("modelo"),
        serie=data.get("serie"),
        codigos=data.get("codigos", []),
        eventos=data.get("eventos", []),
        contactos=CONTACTOS_SOPORTE,
        now=datetime.now().strftime("%Y-%m-%d %H:%M")
    )

    pdf_bytes = generar_pdf(html)

    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": "attachment; filename=FerreyDoc_Reporte.pdf"}
    )

# ============================================================
#  CHATBOT PRINCIPAL
# ============================================================
@app.route("/enviar", methods=["POST"])
def enviar():

    data = request.get_json()
    mensaje = data.get("mensaje", "").strip()
    user_id = "usuario_unico"

    ses = obtener_sesion(user_id)
    estado = ses["estado"]

    # -------- Función responder() interna --------
    def responder(texto, extra=None):
        texto = f"<div style='max-width:100%; word-wrap:break-word;'>{texto}</div>"
        payload = {"respuesta": texto}
        if extra:
            payload.update(extra)
        return jsonify(payload)

    # ========= RESET GLOBAL CON "hola" =========
    if mensaje.lower() == "hola":
        resetear_sesion(user_id)
        ses = obtener_sesion(user_id)
        ses["estado"] = "esperando_consentimiento"
        return responder(
            "👋 ¡Hola, soy <b>FerreyDoc</b>, tu asistente técnico CAT.<br><br>"
            "Estoy diseñado para orientarte respecto a Códigos y Eventos<br>"
            "Además puedo brindarte consejos acerca del Mantenimiento de tu Equipo<br>"
            "Antes de comenzar necesitaré unos datos<br>"
            "¿Estás de acuerdo con brindar información sobre tu equipo CAT?<br>"
            "1️⃣ Sí<br>2️⃣ No"
        )

    # ===================== BIENVENIDA =====================
    if estado == "inicio":
        ses["estado"] = "esperando_consentimiento"
        return responder(
            "👋 ¡Hola, soy <b>FerreyDoc</b>, tu asistente técnico CAT.<br><br>"
            "Estoy diseñado para orientarte respecto a Códigos y Eventos<br>"
            "Además puedo brindarte consejos acerca del Mantenimiento de tu Equipo<br>"
            "Antes de comenzar necesitaré unos datos<br>"
            "¿Estás de acuerdo con brindar información sobre tu equipo CAT?<br>"
            "1️⃣ Sí<br>2️⃣ No"
        )

    # ================= CONSENTIMIENTO =====================
    if estado == "esperando_consentimiento":
        if mensaje == "1":
            ses["estado"] = "pidiendo_modelo"
            return responder("Perfecto 🙌<br>Ingresa el <b>MODELO</b> (ej: 950H, 320D).")

        if mensaje == "2":
            resetear_sesion(user_id)
            return responder("Ok 👍<br>Escribe <b>hola</b> si deseas volver.")

        return responder("Debes responder 1 o 2.")

    # ===================== MODELO =====================
    if estado == "pidiendo_modelo":
        ses["model"] = mensaje.upper()
        ses["estado"] = "pidiendo_serie"
        return responder(
            f"Modelo registrado: <b>{ses['model']}</b><br>"
            "Ahora ingresa los <b>primeros 3 dígitos</b> de la serie."
        )

    # ===================== SERIE ======================
    if estado == "pidiendo_serie":
        ses["serial3"] = mensaje[:3].upper()
        ses["estado"] = "menu_principal"
        return responder(
            f"✔ Modelo: <b>{ses['model']}</b><br>"
            f"✔ Serie: <b>{ses['serial3']}</b><br><br>"
            "A continuación, escribe el número de la consulta que deseas realizar:<br>"
            "1️⃣ Códigos<br>"
            "2️⃣ Eventos<br>"
            "3️⃣ Consejos de Mantenimiento Preventivo<br>"
            "4️⃣ ¿Cómo diferencio un Código de un Evento?<br>"
            "5️⃣ Cambiar máquina<br>"
            "6️⃣ Finalizar<br>"
        )

    # ==================== MENU PRINCIPAL ====================
    if estado == "menu_principal":

        if mensaje == "1":
            ses["estado"] = "pidiendo_codigos"
            return responder(
                "Por favor escribe el código CID/FMI del que necesitas información. "
                "Puedes ingresar hasta 5 códigos separados por coma.<br>"
                "Ej: 168-4"
            )

        if mensaje == "2":
            ses["estado"] = "pidiendo_eventos"
            return responder(
                "Por favor escribe el evento EID/Level del que necesitas información. "
                "Puedes ingresar hasta 5 eventos separados por coma.<br>"
                "Formato obligatorio: <b>E####(L)</b> con L = 1, 2 o 3.<br>"
                "Ej: E0117(2)"
            )

        if mensaje == "3":
            ses["estado"] = "mant_elegir_maquina"
            return responder(
                "Selecciona el tipo de maquinaria:<br>"
                "1️⃣ Rodillo<br>"
                "2️⃣ Cargador<br>"
                "3️⃣ Excavadora<br>"
                "4️⃣ Tractor<br>"
                "9️⃣ Volver"
            )

        if mensaje == "4":
            ses["estado"] = "explicando_cod_evento"
            return responder(
                "<b>¿Cuál es la diferencia entre un Código y un Evento?</b><br><br>"
                "<b>🔧 Código (CID/FMI):</b><br>"
                "• Formato: <b>XXXX-Y</b>.<br>"
                "• Ejemplo: <b>4651-9</b>.<br>"
                "• Describe una <u>falla mecánica o eléctrica puntual</u>.<br><br>"
                "<b>📘 Evento (EID/Level):</b><br>"
                "• Formato: <b>E#####(L)</b>.<br>"
                "• Ejemplo: <b>E60104(2)</b>.<br>"
                "• Describe una <u>condición operativa o mal uso detectado</u>.<br><br>"
                "Aquí tienes un ejemplo real sobre cómo aparece en pantalla:<br><br>"
                "Escribe <b>1</b> para volver al menú principal.",
                extra={"imagen": "/static/ejemplos/codigos_eventos.jpeg"}
            )

        if mensaje == "5":
            resetear_sesion(user_id)
            return responder("Ingresa el nuevo <b>MODELO</b>.")

        if mensaje == "6":
            resetear_sesion(user_id)
            return responder("Gracias por usar FerreyDoc 🤝")

        # ============= GENERAR PDF =============
        if mensaje == "7":

            html = render_template(
                "reporte_diagnostico.html",
                modelo=ses.get("model") or "N/D",
                serie=ses.get("serial3") or "N/D",
                codigos=ses.get("reporte_codigos", []),
                eventos=ses.get("reporte_eventos", []),
                contactos=CONTACTOS_SOPORTE,
                now=datetime.now().strftime("%Y-%m-%d %H:%M")
            )

            pdf_bytes = generar_pdf(html)
            pdf_b64 = base64.b64encode(pdf_bytes).decode("utf-8")

            # Resetear historial tras generar reporte
            ses["reporte_codigos"] = []
            ses["reporte_eventos"] = []

            return responder(
                "📄 Tu reporte PDF está listo para descargar.",
                {"pdf_base64": pdf_b64, "filename": "FerreyDoc_Reporte.pdf"}
            )

        return responder("Elige una opción válida (1–7).")

    # ========== EXPLICACIÓN CÓDIGO vs EVENTO ==========
    if estado == "explicando_cod_evento":
        if mensaje == "1":
            ses["estado"] = "menu_principal"
            return responder(
                "¿Qué deseas hacer?<br>"
                "1️⃣ Códigos<br>"
                "2️⃣ Eventos<br>"
                "3️⃣ Consejos de Mantenimiento Preventivo<br>"
                "4️⃣ ¿Cómo diferencio un Código de un Evento?<br>"
                "5️⃣ Cambiar máquina<br>"
                "6️⃣ Finalizar<br>"
                "7️⃣ Generar reporte PDF<br>"
            )
        return responder(
            "Si ya revisaste el ejemplo, escribe <b>1</b> para volver al menú principal."
        )

    # ==================== MANTENIMIENTO — ELEGIR MÁQUINA ====================
    if estado == "mant_elegir_maquina":

        if mensaje == "1":
            ses["mant_maquina"] = "rodillo"

        elif mensaje == "2":
            ses["mant_maquina"] = "cargador"

        elif mensaje == "3":
            ses["mant_maquina"] = "excavadora"

        elif mensaje == "4":
            ses["mant_maquina"] = "tractor"

        elif mensaje == "9":
            ses["estado"] = "menu_principal"
            return responder(
                "¿Qué deseas hacer?<br>"
                "1️⃣ Códigos<br>"
                "2️⃣ Eventos<br>"
                "3️⃣ Consejos de Mantenimiento Preventivo<br>"
                "4️⃣ ¿Cómo diferencio un Código de un Evento?<br>"
                "5️⃣ Cambiar máquina<br>"
                "6️⃣ Finalizar<br>"
                "7️⃣ Generar reporte PDF<br>"
            )

        else:
            return responder("Selecciona una opción válida (1–4 o 9).")

        # Si eligió máquina válida
        ses["estado"] = "mant_elegir_intervalo"
        maquina = ses["mant_maquina"]
        info = PLAN_MANTENIMIENTO.get(maquina)

        if not info:
            return responder("❌ No existe plan de mantenimiento para esa máquina.")

        # Construcción dinámica del menú de intervalos
        lista = ""
        claves = list(info["intervalos"].keys())
        ses["mant_intervalos_lista"] = claves  # guardamos orden real

        i = 1
        for clave in claves:
            etiqueta = info["intervalos"][clave]["label"]
            lista += f"{i}️⃣ {etiqueta}<br>"
            i += 1

        total = len(claves)
        return responder(
            f"📘 <b>Plan de mantenimiento — {info['nombre']}</b><br><br>"
            f"Selecciona el intervalo:<br><br>{lista}<br>"
            f"0️⃣ Volver al menú de máquinas"
        )

    # ==================== MANTENIMIENTO — ELEGIR INTERVALO ====================
    if estado == "mant_elegir_intervalo":
        intervalos = ses.get("mant_intervalos_lista") or []
        maquina = ses.get("mant_maquina")

        # Si se rompió el contexto, devolvemos al menú principal
        if not intervalos or not maquina:
            ses["estado"] = "menu_principal"
            return responder(
                "Hubo un problema leyendo los intervalos de mantenimiento. "
                "Te regreso al menú principal.<br><br>"
                "1️⃣ Códigos<br>"
                "2️⃣ Eventos<br>"
                "3️⃣ Mantenimiento<br>"
                "4️⃣ Dif. código vs evento<br>"
                "5️⃣ Cambiar máquina<br>"
                "6️⃣ Finalizar<br>"
                "7️⃣ Generar PDF"
            )

        # Volver al menú de selección de máquina
        if mensaje == "0":
            ses["estado"] = "mant_elegir_maquina"
            return responder(
                "Selecciona el tipo de maquinaria:<br>"
                "1️⃣ Rodillo<br>"
                "2️⃣ Cargador<br>"
                "3️⃣ Excavadora<br>"
                "4️⃣ Tractor<br>"
                "9️⃣ Volver"
            )

        # Validar input numérico
        if not mensaje.isdigit():
            total = len(intervalos)
            return responder(f"Selecciona una opción válida (1–{total} o 0).")

        opcion = int(mensaje)
        total = len(intervalos)

        if opcion < 1 or opcion > total:
            return responder(f"Selecciona una opción válida (1–{total} o 0).")

        clave_intervalo = intervalos[opcion - 1]
        ses["mant_intervalo"] = clave_intervalo

        info = PLAN_MANTENIMIENTO.get(maquina)
        if not info:
            ses["estado"] = "menu_principal"
            return responder("❌ No existe plan de mantenimiento para esa máquina.")

        data_intervalo = info["intervalos"].get(clave_intervalo)
        if not data_intervalo:
            ses["estado"] = "menu_principal"
            return responder("❌ No encontré el intervalo seleccionado.")

        bloques = data_intervalo.get("bloques", {})

        texto_resp = (
            f"📘 <b>Plan de mantenimiento — {info['nombre']}</b><br><br>"
            f"<b>Intervalo:</b> {data_intervalo['label']}<br><br>"
        )

        for titulo, tareas in bloques.items():
            texto_resp += f"{titulo}:<br>"
            for t in tareas:
                texto_resp += f"• {t}<br>"
            texto_resp += "<br>"

        link_manual = info.get("link")
        if link_manual:
            texto_resp += (
                "<b>Consulta más detalles en el manual oficial:</b><br>"
                f"<a href=\"{link_manual}\" target=\"_blank\">{link_manual}</a><br><br>"
            )

        # Permitir seguir consultando más intervalos
        ses["estado"] = "mant_elegir_intervalo"
        texto_resp += (
            f"Selecciona otro intervalo (1–{total}) o 0️⃣ Volver al menú de máquinas."
        )

        return responder(texto_resp)

    # ================= CÓDIGOS =================
    if estado == "pidiendo_codigos":

        model = ses["model"]
        serial3 = ses["serial3"]
        codigos_raw = mensaje.split(",")
        respuestas = []

        ses["reporte_codigos"] = []

        for raw in codigos_raw:

            raw = raw.strip()
            mid, cid, fmi = extraer_codigo(raw)

            if not cid or not fmi:
                respuestas.append(f"❌ No pude interpretar {raw}")
                continue

            filas = query_codigo(model, serial3, cid, fmi)
            if not filas:
                respuestas.append(f"❌ No encontré datos para {raw}")
                continue

            fila = filas[0]
            desc = fila["description"] or "Sin descripción."
            causas = fila["causes"] or "Sin causas."
            url = fila["url"] or ""

            url_html = f'<a href="{url}" target="_blank">{url}</a>' if url else "—"

            ses["reporte_codigos"].append({
                "raw": raw,
                "cid": cid,
                "fmi": fmi,
                "descripcion": desc,
                "causas": causas,
                "url": url
            })

            respuestas.append(
                f"🔧 <b>Código:</b> {raw}<br><br>"
                f"<b>Descripción:</b> {desc}<br><br>"
                f"<b>Causas:</b> {causas}<br><br>"
                f"<b>Más información:</b> {url_html}"
            )

        ses["estado"] = "menu_principal"

        return responder(
            "<br><br>".join(respuestas) +
            "<br><br>¿Qué deseas hacer?<br>"
            "1️⃣ Más códigos<br>"
            "2️⃣ Eventos<br>"
            "3️⃣ Mantenimiento<br>"
            "7️⃣ Generar PDF<br>"
            "6️⃣ Finalizar"
        )

    # ================= EVENTOS =================
    if estado == "pidiendo_eventos":

        model = ses["model"]
        serial3 = ses["serial3"]
        eventos_raw = mensaje.split(",")
        respuestas = []

        ses["reporte_eventos"] = []

        for raw in eventos_raw:
            raw = raw.strip()

            eid, level = extraer_evento(raw)

            # Validación estricta del formato único
            if not eid or not level:
                respuestas.append(
                    f"❌ Formato inválido para {raw}. "
                    f"Usa el formato <b>E####(L)</b> con L = 1, 2 o 3. Ej: E0117(2)"
                )
                continue

            filas = query_evento(model, serial3, eid, level)

            if not filas:
                respuestas.append(f"❌ No encontré datos para {raw}")
                continue

            fila = filas[0]
            desc = fila["warning_description"] or "Sin descripción."
            url = fila["url_main"] or ""
            url_html = f'<a href="{url}" target="_blank">{url}</a>' if url else "—"

            ses["reporte_eventos"].append({
                "raw": raw,
                "eid": eid,
                "level": level,
                "descripcion": desc,
                "url": url
            })

            respuestas.append(
                f"📘 <b>Evento:</b> {raw}<br><br>"
                f"<b>Descripción:</b> {desc}<br><br>"
                f"<b>Más información:</b> {url_html}"
            )

        ses["estado"] = "menu_principal"

        return responder(
            "<br><br>".join(respuestas) +
            "<br><br>¿Qué deseas hacer?<br>"
            "1️⃣ Códigos<br>"
            "2️⃣ Más eventos<br>"
            "3️⃣ Mantenimiento<br>"
            "7️⃣ Generar PDF<br>"
            "6️⃣ Finalizar"
        )

    return responder("No entendí 😅<br>Escribe <b>hola</b> para reiniciar.")

# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
