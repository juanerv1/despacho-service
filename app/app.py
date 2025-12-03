from flask import Flask, jsonify, request
from flask_cors import CORS
from database.models import db, OrdenDespacho
from database import querys
from queue import PriorityQueue
import threading
import time
import requests

app = Flask(__name__)
CORS(app)

# Configuración base de datos
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///despachos.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db.init_app(app)

INVENTARIO_URL = "http://inventario-service:8000/api/inventario"

# Cola de prioridad (FIFO basada en fecha_creacion)
cola_pendientes = PriorityQueue()


# ---------------------------------------
# FUNCIONES DE PROCESAMIENTO
# ---------------------------------------
def procesar_despacho(orden):
    """
    Procesa una orden dependiendo de su estado:
    - pendiente → validar 'para_despacho'
    - lista para enviar → validar 'stock'
    """
    endpoint = "para_despacho" if orden.estado == "pendiente" else "stock"

    # Primero validar disponibilidad
    for det in orden.detalles:
        url = f"{INVENTARIO_URL}/{endpoint}/{det.id_producto}?cantidad={det.cantidad_producto}"
        r = requests.get(url)

        if r.status_code != 200:
            return False  # no hay inventario

    # Si está disponible, descontar
    for det in orden.detalles:
        url = f"{INVENTARIO_URL}/{endpoint}/{det.id_producto}/descontar"
        requests.post(url, json={"cantidad": det.cantidad_producto})

    # Marcar como enviada
    orden.estado = "enviada"
    db.session.commit()
    print(f"✔ Orden {orden.id_orden} enviada")

    return True


def worker_cola():
    with app.app_context():  # <<<<< AGREGADO CRÍTICO
        while True:
            try:
                prioridad, id_orden = cola_pendientes.get()

                orden = OrdenDespacho.query.get(id_orden)
                if not orden:
                    continue
                
                print(f"🔎 Procesando orden {id_orden} desde la cola…")

                # Revisar disponibilidad cada 5 segundos
                disponible = False
                while not disponible:
                    disponible = procesar_despacho(orden)
                    if not disponible:
                        print(f"⏳ Inventario no disponible para orden {id_orden}, reintentando en 5s…")
                        time.sleep(5)
                
                print(f"✅ Orden {id_orden} enviada correctamente")

            except Exception as e:
                print(f"❌ Error en hilo: {e}")
            finally:
                time.sleep(1)


# ---------------------------------------
# API: HEALTHCHECK
# ---------------------------------------
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


# ---------------------------------------
# API: CREAR ORDEN
# ---------------------------------------
@app.route("/api/ordenes", methods=["POST"])
def crear_orden():
    data = request.get_json()

    detalles = data["detalles"]
    orden = queries.crear_orden(data, detalles)

    if orden.estado == "pendiente":
        cola_pendientes.put((orden.fecha_creacion.timestamp(), orden.id_orden))
        print(f"📥 Orden {orden.id_orden} añadida a la cola")
    elif orden.estado == "lista para enviar":
        procesar_despacho(orden)

    return jsonify({"id_orden": orden.id_orden, "estado": orden.estado}), 201


# ---------------------------------------
# API: CONSULTAR ORDENES
# ---------------------------------------
@app.route("/api/ordenes", methods=["GET"])
def obtener_ordenes():
    filtros = request.args.to_dict()
    ordenes = queries.obtener_ordenes(filtros)

    resultado = []
    for o in ordenes:
        resultado.append({
            "id_orden": o.id_orden,
            "id_venta": o.id_venta,
            "estado": o.estado,
            "fecha_creacion": o.fecha_creacion.isoformat(),
            "detalles": [
                {
                    "id_producto": d.id_producto,
                    "nombre_producto": d.nombre_producto,
                    "cantidad_producto": d.cantidad_producto
                }
                for d in o.detalles
            ]
        })

    return jsonify(resultado), 200


# ---------------------------------------
# API: ACTUALIZAR ORDEN
# ---------------------------------------
@app.route("/api/ordenes/<int:orden_id>", methods=["PUT"])
def actualizar_orden(orden_id):
    data = request.get_json()
    orden = queries.obtener_orden_por_id(orden_id)

    if not orden:
        return jsonify({"error": "Orden no encontrada"}), 404

    for campo in ["cliente_nombre", "cliente_telefono", "direccion_entrega", "fecha_estimada_entrega"]:
        if campo in data:
            setattr(orden, campo, data[campo])

    db.session.commit()
    return jsonify({"mensaje": "Orden actualizada"}), 200


# ---------------------------------------
# API: CANCELAR ORDEN
# ---------------------------------------
@app.route("/api/ordenes/<int:orden_id>/cancelar", methods=["PATCH"])
def cancelar_orden(orden_id):
    orden = queries.obtener_orden_por_id(orden_id)

    if not orden:
        return jsonify({"error": "Orden no encontrada"}), 404

    orden.estado = "cancelada"
    db.session.commit()

    return jsonify({"mensaje": "Orden cancelada"}), 200


# ---------------------------------------
# INICIO DEL SERVICIO
# ---------------------------------------
with app.app_context():
    db.create_all()

    # Restaurar cola
    pendientes = OrdenDespacho.query.filter_by(estado="pendiente").all()
    for p in pendientes:
        cola_pendientes.put((p.fecha_creacion.timestamp(), p.id_orden))

    print(f"🔁 Cola restaurada con {len(pendientes)} órdenes pendientes")

# Hilo background
threading.Thread(target=worker_cola, daemon=True).start()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
