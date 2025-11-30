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
#  PARSEO DE EVENTOS
# ============================================================
def extraer_evento(texto: str):
    t = texto.upper().replace("-", " ")
    match_evento = re.search(r"(?:E)?(\d{3,4})", t)
    if not match_evento:
        return None, None
    eid = f"E{match_evento.group(1)}"

    level = None
    m = re.search(r"\((\d{1,2})\)", t)
    if m:
        level = m.group(1)
    else:
        m2 = re.search(r"NIVEL\s*(\d{1,2})", t)
        if m2:
            level = m2.group(1)

    return eid, level or "2"

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
                        "Inspeccionar el separador de agua del sistema de combustible"
                    ],
                    "🧮 Sistema hidráulico": [
                        "Revisar el nivel de aceite del sistema hidráulico"
                    ]
                }
            },
            "50h": {
                "label": "50 horas de servicio",
                "bloques": {
                    "⛽ Combustible": [
                        "Drenar agua y sedimento en el tanque de combustible"
                    ],
                    "⚙️ Componentes estructurales / hoja": [
                        "Lubricar la hoja niveladora",
                        "Lubricar extremos del cilindro de la dirección"
                    ],
                    "🛞 Neumáticos": [
                        "Revisar inflado de los neumáticos"
                    ]
                }
            },
            "250h": {
                "label": "Primeras 250 h y cada 250 h",
                "bloques": {
                    "🛞 Ejes y mandos finales": [
                        "Cambiar aceite del eje trasero (primeras 250 horas)",
                        "Cambiar aceite del planetario del mando final (eje)",
                        "Cambiar aceite del planetario del mando final (tambor)",
                        "Cambiar aceite del soporte vibratorio",
                        "Revisar nivel de aceite del eje trasero (cada 250 horas)",
                        "Revisar nivel de aceite del planetario del mando final (eje)",
                        "Revisar nivel de aceite del planetario del mando final (tambor)",
                        "Revisar nivel de aceite del soporte vibratorio"
                    ],
                    "🧪 Muestreo de fluidos": [
                        "Obtener muestra de refrigerante del sistema de enfriamiento (nivel 1)",
                        "Obtener muestra de aceite del motor"
                    ],
                    "⚙️ Sistema vibratorio / tambor": [
                        "Inspeccionar montajes de aislamiento del tambor"
                    ],
                    "🔧 Transmisión y correas": [
                        "Inspeccionar/ajustar/reemplazar correas"
                    ]
                }
            },
            "500h": {
                "label": "500 horas de servicio",
                "bloques": {
                    "🛢️ Motor": [
                        "Obtener muestra de aceite del eje",
                        "Cambiar aceite y filtro del motor"
                    ],
                    "⛽ Sistema de combustible": [
                        "Reemplazar filtro del sistema de combustible (en línea)",
                        "Reemplazar elemento de filtro primario del sistema de combustible (separador de agua)",
                        "Reemplazar filtro secundario del sistema de combustible",
                        "Limpiar colador del tanque de combustible"
                    ],
                    "🧮 Sistema hidráulico y vibratorio": [
                        "Obtener muestra de aceite del sistema hidráulico",
                        "Obtener muestra de aceite del soporte vibratorio"
                    ],
                    "🛡️ Seguridad y estructura": [
                        "Revisar freno de estacionamiento",
                        "Revisar par de los pernos del juego de revestimiento",
                        "Ajustar pestillo del capó"
                    ]
                }
            },
            "1000h": {
                "label": "1000 horas de servicio",
                "bloques": {
                    "🛞 Ejes y mandos finales": [
                        "Cambiar aceite del eje trasero",
                        "Cambiar aceite del planetario del mando final (eje)",
                        "Cambiar aceite del planetario del mando final (tambor)",
                        "Obtener muestra de aceite del planetario del mando final (eje)",
                        "Obtener muestra de aceite del planetario del mando final (tambor)"
                    ],
                    "🧮 Sistema hidráulico": [
                        "Reemplazar filtro de aceite del sistema hidráulico",
                        "Reemplazar respiradero del tanque hidráulico"
                    ],
                    "⚙️ Dirección / estructura": [
                        "Reemplazar cartucho del sistema de dirección",
                        "Inspeccionar Estructura de Protección en Caso de Vuelcos (ROPS)"
                    ],
                    "🔊 Sistema vibratorio": [
                        "Cambiar aceite del soporte vibratorio"
                    ],
                    "🧊 Sistema de enfriamiento": [
                        "Limpiar/reemplazar tapa de presión del sistema de enfriamiento"
                    ]
                }
            },
            "2000h": {
                "label": "2000 horas de servicio",
                "bloques": {
                    "⚙️ Sistema vibratorio / tambor": [
                        "Reemplazar montajes de aislamiento del tambor"
                    ],
                    "⛽ Combustible": [
                        "Reemplazar filtro de la tapa del tanque de combustible"
                    ]
                }
            },
            "3000h": {
                "label": "3000 horas de servicio",
                "bloques": {
                    "🧊 Sistema de enfriamiento": [
                        "Reemplazar termostato del agua del sistema de enfriamiento",
                        "Cambiar aceite de la caja de las pesas excéntricas",
                        "Cambiar aceite del sistema hidráulico"
                    ]
                }
            },
            "6000h": {
                "label": "6000 horas de servicio o cada 3 años",
                "bloques": {
                    "🧊 Sistema de enfriamiento": [
                        "Agregar prolongador de vida útil de refrigerante en el sistema de enfriamiento (ELC)"
                    ],
                    "🛡️ Seguridad": [
                        "Reemplazar cinturón de seguridad (cada 3 años)"
                    ]
                }
            },
            "largo_plazo": {
                "label": "Intervalos largos (10 000 h, 12 000 h y tareas anuales)",
                "bloques": {
                    "🧊 Sistema de enfriamiento y refrigerante": [
                        "Obtener muestra de refrigerante del sistema de enfriamiento (nivel 2) – cada año",
                        "Cambiar refrigerante del sistema de enfriamiento (ELC) cada 12 000 horas o 6 años"
                    ],
                    "🧪 Sistema de emisiones DEF": [
                        "Reemplazar filtros del múltiple de DEF (cada 10 000 horas)"
                    ],
                    "🔁 Tareas cuando sea necesario": [
                        "Limpiar/revisar batería",
                        "Reciclar batería cuando corresponda",
                        "Inspeccionar/reemplazar batería o cable de batería",
                        "Limpiar/reemplazar filtro de aire de la cabina",
                        "Inspeccionar/reemplazar cuchillas (hoja niveladora)",
                        "Limpiar rejilla del tubo de llenado de DEF",
                        "Llenar fluido de escape diésel",
                        "Limpiar/reemplazar filtro de fluido de escape diésel",
                        "Lubricar pestillos de la puerta",
                        "Cambiar aceite de enfriamiento del tambor",
                        "Inspeccionar/ajustar/reemplazar raspadores del tambor",
                        "Limpiar/reemplazar elemento de filtro de aire primario del motor",
                        "Reemplazar elemento de filtro de aire secundario del motor",
                        "Limpiar calcomanía (identificación del producto)",
                        "Cebar sistema de combustible",
                        "Drenar separador de agua del sistema de combustible",
                        "Reemplazar fusibles según se requiera",
                        "Inspeccionar filtro de aceite",
                        "Limpiar núcleo del radiador",
                        "Cambiar distancia entre neumáticos cuando se requiera",
                        "Apretar tuercas de las ruedas",
                        "Llenar depósito del lavaparabrisas",
                        "Inspeccionar/reemplazar limpiaparabrisas",
                        "Limpiar ventanas"
                    ]
                }
            },
            "todo": {
                "label": "Resumen general del programa de mantenimiento",
                "bloques": {
                    "📋 Recordatorios generales": [
                        "Antes de efectuar las tareas de un intervalo consecutivo, realizar también las tareas de los intervalos anteriores.",
                        "Si no se cumplen las horas de servicio, realizar entre 10 y 100 horas al menos cada 3 meses; entre 250 y 500 horas al menos cada 6 meses; entre 1000 y 2500 horas al menos una vez al año.",
                        "Seguir siempre las instrucciones de seguridad, advertencias y regulaciones de emisiones indicadas por el fabricante."
                    ]
                }
            }
        }
    },

    # =======================================================
    # CARGADOR DE RUEDAS
    # =======================================================
    "cargador": {
        "nombre": "Cargador de ruedas",
        "link": "https://sis2.cat.com/#/detail?keyword=Maintenance+Interval+Schedule&infoType=13&serviceMediaNumber=SEBU9108&serviceIeSystemControlNumber=i06271337&tab=service",
        "intervalos": {
            "diario_10h": {
                "label": "Cada día / 10 horas de servicio",
                "bloques": {
                    "🛡️ Seguridad y cabina": [
                        "Probar alarma de retroceso",
                        "Inspeccionar cinturón de seguridad",
                        "Inspeccionar herramienta",
                        "Lubricar herramienta según aplique"
                    ],
                    "🛢️ Motor y enfriamiento": [
                        "Limpiar/inspeccionar válvula de polvo del filtro de aire",
                        "Revisar nivel de refrigerante del sistema de enfriamiento",
                        "Revisar nivel de aceite del motor"
                    ],
                    "🧮 Sistema hidráulico": [
                        "Revisar nivel de aceite del sistema hidráulico"
                    ],
                    "⚙️ Transmisión": [
                        "Revisar nivel de aceite de la transmisión"
                    ]
                }
            },
            "50h": {
                "label": "50 horas de servicio",
                "bloques": {
                    "⚙️ Componentes estructurales / cucharón": [
                        "Lubricar cojinetes de pivote inferiores del cucharón",
                        "Lubricar varillaje del cucharón y cojinetes del cilindro del cargador"
                    ],
                    "🌬️ Cabina y aire": [
                        "Limpiar/reemplazar filtro de aire de la cabina"
                    ],
                    "⛽ Combustible": [
                        "Drenar filtro primario del sistema de combustible (separador de agua)"
                    ],
                    "🛞 Neumáticos": [
                        "Revisar inflado de los neumáticos"
                    ]
                }
            },
            "100h": {
                "label": "100 horas de servicio",
                "bloques": {
                    "⚙️ Dirección y articulaciones": [
                        "Lubricar cojinetes de oscilación del eje",
                        "Probar dirección secundaria",
                        "Lubricar cojinetes del cilindro de la dirección"
                    ],
                    "⚙️ Varillaje de cucharón": [
                        "Lubricar varillaje del cucharón y cojinetes del cilindro del cargador (si no se hizo en 50 h)"
                    ]
                }
            },
            "250h": {
                "label": "250 horas de servicio",
                "bloques": {
                    "🛞 Frenos y transmisión": [
                        "Revisar acumulador del freno",
                        "Realizar prueba del sistema de frenos"
                    ],
                    "🛞 Diferencial y mandos finales": [
                        "Revisar nivel de aceite del diferencial y del mando final",
                        "Lubricar estrías del eje motriz (central)",
                        "Lubricar cojinete de soporte del eje motriz"
                    ],
                    "🛢️ Motor": [
                        "Cambiar aceite y filtro del motor",
                        "Obtener muestra de aceite del motor"
                    ]
                }
            },
            "500h": {
                "label": "Primeras 500 h y cada 500 h",
                "bloques": {
                    "🛢️ Motor y refrigerante": [
                        "Revisar juego de válvulas del motor (primeras 500 horas)",
                        "Obtener muestra de refrigerante del sistema de enfriamiento",
                    ],
                    "⛽ Combustible": [
                        "Obtener muestra de aceite del diferencial y del mando final",
                        "Reemplazar elemento de filtro primario del sistema de combustible (separador de agua)",
                        "Reemplazar filtro secundario del sistema de combustible",
                        "Limpiar colador del tanque de combustible"
                    ],
                    "🧮 Sistema hidráulico": [
                        "Reemplazar filtro de aceite del sistema hidráulico",
                        "Obtener muestra de aceite del sistema hidráulico"
                    ],
                    "⚙️ Transmisión": [
                        "Reemplazar filtro de aceite de la transmisión",
                        "Obtener muestra de aceite de la transmisión"
                    ],
                    "🔧 Correas": [
                        "Inspeccionar/ajustar/reemplazar correas"
                    ]
                }
            },
            "1000h": {
                "label": "1000 horas de servicio",
                "bloques": {
                    "⚙️ Estructura y articulaciones": [
                        "Lubricar cojinetes de articulación",
                        "Lubricar uniones universales del eje motriz",
                        "Inspeccionar Estructura de Protección en Caso de Vuelcos (ROPS)"
                    ],
                    "🛢️ Motor": [
                        "Revisar juego de válvulas del motor (revisión periódica)"
                    ],
                    "⚙️ Transmisión": [
                        "Cambiar aceite de la transmisión"
                    ]
                }
            },
            "2000h": {
                "label": "2000 horas de servicio",
                "bloques": {
                    "🔋 Sistema eléctrico y frenos": [
                        "Limpiar, inspeccionar y reemplazar batería o cable de batería cuando corresponda",
                        "Revisar discos de freno"
                    ],
                    "🛞 Diferencial y mandos finales": [
                        "Cambiar aceite del diferencial y del mando final"
                    ],
                    "⛽ Combustible": [
                        "Reemplazar filtro de la tapa del tanque de combustible"
                    ]
                }
            },
            "3000h": {
                "label": "3000 horas de servicio",
                "bloques": {
                    "🧮 Sistema hidráulico": [
                        "Cambiar aceite del sistema hidráulico"
                    ],
                    "⚙️ Dirección": [
                        "Lubricar estrías de la columna de dirección (dirección HMU)"
                    ]
                }
            },
            "6000h": {
                "label": "6000 horas de servicio",
                "bloques": {
                    "🧊 Sistema de enfriamiento": [
                        "Agregar prolongador de vida útil de refrigerante en el sistema de enfriamiento (ELC)"
                    ]
                }
            },
            "largo_plazo": {
                "label": "Intervalos largos (3 años, 5000 h, 12 000 h y tareas condicionales)",
                "bloques": {
                    "🧊 Sistema de enfriamiento": [
                        "Cambiar refrigerante del sistema de enfriamiento (ELC) cada 12 000 horas",
                        "Obtener muestras de refrigerante según programa S·O·S"
                    ],
                    "🧊 Aire acondicionado": [
                        "Reemplazar secador receptor (refrigerante) cada 5 000 horas"
                    ],
                    "🛡️ Seguridad": [
                        "Reemplazar cinturón de seguridad cada 3 años"
                    ],
                    "🔁 Tareas cuando sea necesario": [
                        "Llenar tanque de grasa de lubricación automática",
                        "Limpiar/reemplazar elemento de filtro de aire del motor",
                        "Limpiar compartimiento del motor",
                        "Reemplazar cilindro del auxiliar de arranque con éter",
                        "Limpiar calcomanía (identificación del producto)",
                        "Cebar sistema de combustible",
                        "Drenar filtro primario del sistema de combustible (separador de agua)",
                        "Reemplazar/reajustar fusibles y disyuntores",
                        "Reemplazar luz de descarga de alta intensidad (HID)",
                        "Inspeccionar filtro de aceite",
                        "Limpiar núcleo del radiador",
                        "Revisar acumulador del control de amortiguación",
                        "Llenar depósito del lavaparabrisas",
                        "Limpiar ventanas"
                    ]
                }
            },
            "todo": {
                "label": "Resumen general del programa de mantenimiento",
                "bloques": {
                    "📋 Recordatorios generales": [
                        "Antes de efectuar las tareas de un intervalo consecutivo, realizar también las tareas de los intervalos anteriores.",
                        "Si no se cumplen las horas de servicio, realizar entre 10 y 100 horas al menos cada 3 meses; entre 250 y 500 horas al menos cada 6 meses; entre 1 000 y 2 500 horas al menos una vez al año.",
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
                        "Revisar nivel de refrigerante del sistema de enfriamiento",
                        "Revisar nivel de aceite del motor"
                    ],
                    "⛽ Combustible": [
                        "Drenar separador de agua del sistema de combustible",
                        "Drenar agua y sedimento en el tanque de combustible"
                    ],
                    "🧮 Sistema hidráulico": [
                        "Revisar nivel de aceite del sistema hidráulico"
                    ],
                    "🛡️ Seguridad": [
                        "Probar indicadores y medidores",
                        "Inspeccionar cinturón de seguridad",
                        "Probar alarma de desplazamiento"
                    ],
                    "⚙️ Tren de rodaje": [
                        "Inspeccionar ajuste de la cadena",
                        "Revisar tren de rodaje (undercarriage)"
                    ]
                }
            },
            "50h": {
                "label": "Cada 10 horas durante las primeras 50 h y luego cada 50 h",
                "bloques": {
                    "⚙️ Pluma, brazo y cucharón": [
                        "Lubricar varillaje de la pluma y del brazo (cada 10 h durante las primeras 50 h y luego según programa)",
                        "Lubricar varillaje del cucharón"
                    ]
                }
            },
            "100h": {
                "label": "100 horas de servicio",
                "bloques": {
                    "⚙️ Herramienta / martillo hidráulico": [
                        "Reemplazar filtro de aceite del martillo hidráulico (si aplica)",
                        "Lubricar nuevamente varillaje del cucharón si corresponde"
                    ]
                }
            },
            "500h": {
                "label": "Primeras 500 horas de servicio",
                "bloques": {
                    "🧊 Sistema de enfriamiento": [
                        "Obtener muestra de refrigerante del sistema de enfriamiento"
                    ],
                    "🛢️ Motor": [
                        "Cambiar aceite y filtro del motor"
                    ],
                    "⚙️ Mandos finales y rotación": [
                        "Cambiar aceite del mando final",
                        "Cambiar aceite del mando de rotación"
                    ]
                }
            },
            "500h_2": {
                "label": "Cada 500 horas de servicio",
                "bloques": {
                    "⚙️ Pluma, brazo y estructura": [
                        "Lubricar varillaje de la pluma y del brazo",
                        "Inspeccionar pluma, brazo y estructura (Boom, Stick and Frame)"
                    ],
                    "🛢️ Motor y mandos finales": [
                        "Obtener muestra de aceite del motor",
                        "Revisar nivel de aceite del mando final",
                        "Obtener muestra de aceite del mando final"
                    ],
                    "🧮 Sistema hidráulico y rotación": [
                        "Obtener muestra de aceite del sistema hidráulico",
                        "Revisar nivel de aceite del acoplamiento de la bomba",
                        "Lubricar cojinete de la rotación",
                        "Revisar nivel de aceite del mando de rotación",
                        "Obtener muestra de aceite del mando de rotación"
                    ]
                }
            },
            "1000h": {
                "label": "1000 horas de servicio",
                "bloques": {
                    "🔋 Sistema eléctrico": [
                        "Limpiar batería",
                        "Apretar sujeción de la batería"
                    ],
                    "🔧 Correas": [
                        "Inspeccionar/ajustar/reemplazar correas"
                    ],
                    "🛢️ Motor": [
                        "Cambiar aceite y filtro del motor"
                    ],
                    "⛽ Combustible": [
                        "Reemplazar elemento de filtro primario del sistema de combustible (separador de agua)",
                        "Reemplazar filtro secundario del sistema de combustible"
                    ],
                    "⚙️ Rotación": [
                        "Cambiar aceite del mando de rotación"
                    ]
                }
            },
            "2000h": {
                "label": "2000 horas de servicio",
                "bloques": {
                    "🧊 Sistema de enfriamiento": [
                        "Obtener muestra de refrigerante del sistema de enfriamiento"
                    ],
                    "⚙️ Mandos finales y rotación": [
                        "Cambiar aceite del mando final",
                        "Reemplazar filtro de la tapa del tanque de combustible",
                        "Lubricar engranaje de la rotación"
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
                    "🧮 Sistema hidráulico": [
                        "Cambiar aceite del sistema hidráulico"
                    ],
                    "🧊 Sistema de enfriamiento": [
                        "Agregar prolongador de vida útil de refrigerante en el sistema de enfriamiento (ELC)"
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
                        "Cambiar refrigerante del sistema de enfriamiento (ELC) cada 12 000 horas o 6 años"
                    ],
                    "🧪 Sistema de emisiones y combustible": [
                        "Reemplazar filtro de fluido de escape diésel (cada 5 000 horas)",
                        "Limpiar filtro de partículas para combustible diésel",
                        "Cambiar aceite del acoplamiento de la bomba (5 000 horas)",
                        "Reemplazar secador receptor (refrigerante) cada 5 000 horas",
                        "Reemplazar filtros del múltiple de DEF cada 10 000 horas"
                    ],
                    "🔁 Tareas cuando sea necesario": [
                        "Inspeccionar/reemplazar filtro de aire del acondicionador/calentador de cabina (recirculación)",
                        "Revisar nivel de electrolito de baterías",
                        "Inspeccionar/reemplazar batería o cable de batería",
                        "Inspeccionar cáncamo de levantamiento del cucharón",
                        "Inspeccionar/ajustar varillaje del cucharón",
                        "Inspeccionar/reemplazar puntas del cucharón",
                        "Limpiar/reemplazar filtro de aire de cabina (aire fresco)",
                        "Limpiar cámara",
                        "Limpiar condensador (refrigerante)",
                        "Limpiar rejilla del tubo de llenado de DEF",
                        "Drenar fluido de escape de combustible diésel",
                        "Llenar fluido de escape diésel",
                        "Reemplazar elementos del filtro de aire del motor",
                        "Reemplazar cilindro del auxiliar de arranque con éter",
                        "Limpiar calcomanía (identificación del producto)",
                        "Cebar sistema de combustible",
                        "Limpiar colador del tanque de combustible",
                        "Reemplazar fusibles",
                        "Purgar sistema hidráulico cuando corresponda",
                        "Reemplazar luz LED",
                        "Reemplazar filtro de aceite del martillo hidráulico cuando corresponda",
                        "Inspeccionar filtro de aceite",
                        "Limpiar radiador, posenfriador y núcleos del enfriador de aceite",
                        "Inspeccionar Estructura de Protección en Caso de Vuelcos (ROPS)",
                        "Ajustar cadena de orugas",
                        "Revisar tren de rodaje",
                        "Llenar depósito del lavaparabrisas",
                        "Inspeccionar/reemplazar limpiaparabrisas",
                        "Limpiar ventanas y parabrisas"
                    ]
                }
            },
            "todo": {
                "label": "Resumen general del programa de mantenimiento",
                "bloques": {
                    "📋 Recordatorios generales": [
                        "Utilizar horas de servicio, consumo de combustible, kilometraje o tiempo de calendario (lo que ocurra primero) para definir los intervalos.",
                        "Antes de efectuar las tareas de un intervalo consecutivo, realizar también las tareas de los intervalos anteriores.",
                        "Si no se cumplen las horas de servicio, realizar entre 10 y 100 horas al menos cada 3 meses; entre 250 y 500 horas al menos cada 6 meses; entre 1 000 y 2 500 horas al menos una vez al año.",
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
        "link": "https://sis2.cat.com/#/detail?keyword=Maintenance+Interval+Schedule&infoType=13&serviceMediaNumber=SEBU9087&serviceIeSystemControlNumber=i06105405&tab=service",
        "intervalos": {
            "diario_10h": {
                "label": "Cada día / 10 horas de servicio",
                "bloques": {
                    "🛡️ Seguridad y controles": [
                        "Probar alarma de retroceso",
                        "Probar sistema de frenos",
                        "Probar bocina",
                        "Inspeccionar cinturón de seguridad"
                    ],
                    "🧊 Cabina y aire": [
                        "Limpiar/inspeccionar/reemplazar filtro de la cabina (aire fresco)"
                    ],
                    "🛢️ Motor y enfriamiento": [
                        "Revisar nivel de refrigerante del sistema de enfriamiento",
                        "Revisar nivel de aceite del motor"
                    ],
                    "⛽ Combustible": [
                        "Drenar filtro primario del sistema de combustible (separador de agua)",
                        "Drenar agua y sedimentos del tanque de combustible"
                    ],
                    "🧮 Sistemas hidráulico y tren de fuerza": [
                        "Revisar nivel de aceite del sistema hidráulico",
                        "Revisar nivel de aceite del eje pivote",
                        "Revisar nivel de aceite del sistema de tren de fuerza"
                    ],
                    "⚙️ Tren de rodaje": [
                        "Limpiar tren de rodaje (undercarriage)"
                    ]
                }
            },
            "50h": {
                "label": "50 horas de servicio",
                "bloques": {
                    "⚙️ Hoja topadora y desgarrador": [
                        "Lubricar cilindros de inclinación y tirante de inclinación de la hoja topadora",
                        "Lubricar cojinetes de la horquilla del cilindro de levantamiento",
                        "Lubricar cojinetes del cilindro y del varillaje del desgarrador"
                    ],
                    "⚙️ Tren de rodaje": [
                        "Inspeccionar pasadores de cadena"
                    ],
                    "🧊 Cabina": [
                        "Limpiar/inspeccionar/reemplazar filtro de la cabina (recirculación)"
                    ]
                }
            },
            "250h": {
                "label": "250 horas de servicio",
                "bloques": {
                    "🛢️ Motor": [
                        "Obtener muestra de aceite del motor"
                    ],
                    "⚙️ Barra compensadora y mandos finales": [
                        "Revisar nivel de aceite de los pasadores de extremo de la barra compensadora",
                        "Revisar nivel de aceite del mando final"
                    ],
                    "⚙️ Cadena y cabrestante": [
                        "Revisar/ajustar cadena",
                        "Lubricar rodillos guiacables del cabrestante",
                        "Revisar nivel de aceite del cabrestante"
                    ]
                }
            },
            "500h": {
                "label": "500 horas iniciales y cada 500 horas de servicio",
                "bloques": {
                    "🧊 Sistema de enfriamiento": [
                        "Obtener muestra de refrigerante del sistema de enfriamiento (nivel 2) – 500 h iniciales"
                    ],
                    "⚙️ Cabrestante": [
                        "Cambiar/limpiar respiradero y aceite del cabrestante (500 h iniciales)"
                    ],
                    "🛢️ Motor y combustible": [
                        "Cambiar aceite del motor y filtro (cada 500 horas)",
                        "Limpiar/reemplazar filtro primario del sistema de combustible",
                        "Reemplazar filtro secundario del sistema de combustible",
                        "Reemplazar/limpiar colador y filtro de la tapa del tanque de combustible"
                    ],
                    "🧮 Sistemas hidráulico y tren de fuerza": [
                        "Obtener muestra de aceite del sistema hidráulico",
                        "Limpiar respiradero del tren de fuerza",
                        "Obtener muestra de aceite del sistema de tren de fuerza"
                    ],
                    "⚙️ Mandos finales y tensores": [
                        "Obtener muestra de aceite del mando final",
                        "Inspeccionar/limpiar protector de sello del mando final",
                        "Revisar nivel de aceite del compartimiento del resorte tensor"
                    ],
                    "🔧 Correas": [
                        "Inspeccionar/reemplazar correas"
                    ]
                }
            },
            "1000h": {
                "label": "1000 horas de servicio",
                "bloques": {
                    "🧮 Sistema hidráulico y tren de fuerza": [
                        "Reemplazar filtros de aceite del sistema hidráulico",
                        "Reemplazar filtro de aceite del tren de fuerza",
                        "Reemplazar filtro de carga de la dirección"
                    ]
                }
            },
            "1000h_2": {
                "label": "1000 horas de servicio o cada 6 meses",
                "bloques": {
                    "🔋 Sistema eléctrico y tren de fuerza": [
                        "Inspeccionar batería",
                        "Cambiar/limpiar rejillas y aceite del sistema de tren de fuerza",
                        "Inspeccionar Estructura de Protección en Caso de Vuelcos (ROPS)",
                        "Cambiar/limpiar respiradero y aceite del cabrestante"
                    ]
                }
            },
            "2000h": {
                "label": "2000 horas de servicio o cada año",
                "bloques": {
                    "🧊 Sistema de enfriamiento": [
                        "Obtener muestra de refrigerante del sistema de enfriamiento (nivel 2)"
                    ],
                    "⚙️ Estructura y tren de rodaje": [
                        "Inspeccionar barra compensadora y montajes del motor",
                        "Cambiar aceite del mando final",
                        "Reemplazar empaque del protector del sello del mando final",
                        "Cambiar aceite del sistema hidráulico",
                        "Inspeccionar unión del pasador protector del radiador",
                        "Inspeccionar bastidor de rodillos de la cadena",
                        "Inspeccionar guías del bastidor de rodillos de cadenas"
                    ]
                }
            },
            "2500h": {
                "label": "2500 horas de servicio",
                "bloques": {
                    "🛢️ Motor y combustible": [
                        "Inspeccionar/ajustar inyector unitario electrónico",
                        "Revisar/ajustar juego de válvulas del motor"
                    ]
                }
            },
            "6000h": {
                "label": "6000 horas de servicio o cada 3 años",
                "bloques": {
                    "🧊 Sistema de enfriamiento": [
                        "Agregar prolongador de vida útil de refrigerante del sistema de enfriamiento (ELC)",
                        "Reemplazar termostato del agua del sistema de enfriamiento"
                    ]
                }
            },
            "largo_plazo": {
                "label": "Intervalos largos (2 años, 3 años, 5000 h, 10 000 h, 12 000 h y tareas condicionales)",
                "bloques": {
                    "🧊 Aire acondicionado": [
                        "Reemplazar secador de refrigerante cada 2 años"
                    ],
                    "🛡️ Seguridad": [
                        "Reemplazar cinturón de seguridad cada 3 años"
                    ],
                    "🧪 Sistema de emisiones": [
                        "Limpiar bujía de encendido del ARD (cada 5 000 h)",
                        "Reemplazar filtro de fluido de escape diésel (cada 5 000 h)",
                        "Reemplazar inyector de fluido de escape diésel (cada 5 000 h)",
                        "Limpiar filtro de partículas para combustible diésel (cada 5 000 h)",
                        "Reemplazar filtros del múltiple de DEF (cada 10 000 h)"
                    ],
                    "🧊 Sistema de enfriamiento": [
                        "Cambiar refrigerante del sistema de enfriamiento (ELC) cada 12 000 horas o 6 años"
                    ],
                    "🔁 Tareas cuando sea necesario": [
                        "Reemplazar batería, cable de batería o interruptor de desconexión de la batería",
                        "Limpiar protector inferior (potencia)",
                        "Limpiar/ajustar cámara",
                        "Limpiar núcleos de enfriamiento",
                        "Limpiar rejilla del tubo de llenado de DEF",
                        "Llenar fluido de escape diésel",
                        "Reemplazar elementos de filtro de aire del motor",
                        "Limpiar antefiltro de aire del motor",
                        "Reemplazar cilindro del auxiliar de arranque con éter",
                        "Limpiar film de identificación del producto",
                        "Revisar posición de la rueda loca delantera",
                        "Reemplazar/reajustar fusibles y disyuntores",
                        "Limpiar rejilla de derivación del filtro del sistema hidráulico",
                        "Inspeccionar filtro de aceite",
                        "Limpiar/reemplazar tapa de presión del radiador",
                        "Inspeccionar/reemplazar punta del desgarrador y protector del vástago",
                        "Limpiar rejilla de barrido del convertidor de par",
                        "Instalar cable de acero del cabrestante",
                        "Llenar depósito del lavaparabrisas",
                        "Inspeccionar/reemplazar limpiaparabrisas",
                        "Limpiar ventanas"
                    ]
                }
            },
            "todo": {
                "label": "Resumen general del programa de mantenimiento",
                "bloques": {
                    "📋 Recordatorios generales": [
                        "Utilizar horas de servicio, consumo de combustible, kilometraje o tiempo de calendario (lo que ocurra primero) para definir los intervalos.",
                        "Antes de efectuar las tareas de un intervalo consecutivo, realizar también las tareas de los intervalos anteriores.",
                        "Si no se cumplen las horas de servicio, seguir los criterios de tiempo mínimos recomendados.",
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
        now=datetime.now().strftime("%Y-%m-%d %H:%M")   # ← AÑADIDO
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
                "Por favor escribe el código CID/FMI del que necesitas información. Puedes ingresas hasta 5 códigos separados por coma.<br>"
                "Ej: 168-4"
            )

        if mensaje == "2":
            ses["estado"] = "pidiendo_eventos"
            return responder(
                "Por favor escribe el evento EID/Level del que necesitas informaicón. Puedes ingresar hasta 5 eventos separados por coma.<br>"
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

    "Aquí tienes un ejemplo real sobre cómo aparece en pantalla:",
    extra={"imagen": "/static/ejemplos/codigos_eventos.jpg"}
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
                "3️⃣ Mantenimiento<br>"
                "4️⃣ Dif. código vs evento<br>"
                "5️⃣ Cambiar máquina<br>"
                "6️⃣ Finalizar<br>"
                "7️⃣ Generar PDF"
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

        return responder(
            f"📘 <b>Plan de mantenimiento — {info['nombre']}</b><br><br>"
            f"Selecciona el intervalo:<br><br>{lista}<br>9️⃣ Volver"
        )


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
