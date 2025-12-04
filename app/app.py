from datetime import datetime
import queue
from flask import Flask, jsonify, request
from flask_cors import CORS
from database.models import OrdenDespachoDetalle, db, OrdenDespacho
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
cola_listo_para_despachar = PriorityQueue()

# Listas paralelas para consulta sin modificación
lista_pendientes = []  # Mantiene copia de cola_pendientes
lista_listos = []      # Mantiene copia de cola_listo_para_despachar

# Función para agregar a cola y lista paralela
def agregar_a_cola(cola, lista_paralela, orden, tipo):
    """Agrega orden a cola y lista paralela"""
    item = (orden.fecha_creacion.timestamp(), orden.id_orden, tipo)
    cola.put(item)
    lista_paralela.append(item)
    lista_paralela.sort(key=lambda x: x[0])  # Ordenar por timestamp
    print(f"📥 Agregada orden {orden.id_orden} a cola {tipo}")

def sacar_de_cola(cola, lista_paralela, tipo):
    """Saca elemento de cola y lista paralela"""
    if not cola.empty():
        try:
            item = cola.get_nowait()
            if item in lista_paralela:
                lista_paralela.remove(item)
            print(f"📤 Sacada orden {item[1]} de cola {tipo}")
            return item  # (timestamp, orden_id, tipo)
        except queue.Empty:
            return None
    return None

def obtener_siguiente_cola(cola, lista_paralela, tipo):
    """Obtiene el siguiente elemento sin sacarlo realmente"""
    if lista_paralela:
        return lista_paralela[0]  # Devuelve (timestamp, orden_id, tipo)
    return None

# API usando listas paralelas (sin tocar las colas)
@app.route("/api/colas", methods=["GET"])
def ver_colas():
    """Muestra el contenido de ambas colas usando listas paralelas"""
    try:
        def procesar_lista(lista_items, tipo):
            resultado = []
            for timestamp, orden_id, _ in lista_items:
                orden = querys.obtener_ordenes(id_orden=orden_id)
                if orden:
                    resultado.append({
                        "orden_id": orden.id_orden,
                        "id_venta": orden.id_venta,
                        "cliente_nombre": orden.cliente_nombre,
                        "fecha_creacion": orden.fecha_creacion.isoformat(),
                        "prioridad_timestamp": timestamp,
                        "tipo": tipo
                    })
            return resultado
        
        pendientes = procesar_lista(lista_pendientes, "pendiente")
        listos = procesar_lista(lista_listos, "listo_para_despacho")
        
        return jsonify({
            "colas": {
                "pendientes": {
                    "total": len(pendientes),
                    "ordenes": pendientes,
                    "siguiente": pendientes[0] if pendientes else None
                },
                "listo_para_despacho": {
                    "total": len(listos),
                    "ordenes": listos,
                    "siguiente": listos[0] if listos else None
                }
            },
            "debug": {
                "lista_pendientes_tamano": len(lista_pendientes),
                "lista_listos_tamano": len(lista_listos),
                "cola_pendientes_vacia": cola_pendientes.empty(),
                "cola_listos_vacia": cola_listo_para_despachar.empty()
            }
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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
    for det in orden.detalles:  # Cambié 'productos' por 'detalles'
        url = f"{INVENTARIO_URL}/{endpoint}/{det.id_producto}?cantidad={det.cantidad_producto}"
        
        try:
            r = requests.get(url, timeout=5)
            if r.status_code != 200:
                print(f"❌ Producto {det.id_producto} sin stock suficiente")
                return False  # no hay inventario
        except requests.exceptions.RequestException as e:
            print(f"❌ Error conectando con inventario: {e}")
            return False

    # Si está disponible, descontar
    for det in orden.detalles:
        url = f"{INVENTARIO_URL}/{endpoint}/{det.id_producto}/descontar"
        try:
            requests.post(url, json={"cantidad": det.cantidad_producto}, timeout=5)
        except requests.exceptions.RequestException as e:
            print(f"⚠️ Error descontando producto {det.id_producto}: {e}")

    # Marcar como despachado
    orden.estado = "despachado"
    db.session.commit()
    print(f"✅ Orden {orden.id_orden} despachada automáticamente")

    return True


def worker_cola():
    """Worker para procesar órdenes pendientes (usa para_despacho)"""
    with app.app_context():
        while True:
            try:
                # Usar función sacar_de_cola en lugar de get() directo
                item = sacar_de_cola(cola_pendientes, lista_pendientes, "pendiente")
                
                if not item:
                    time.sleep(5)  # Esperar si la cola está vacía
                    continue
                
                _, id_orden, tipo = item
                orden = querys.obtener_ordenes(id_orden=id_orden)
                
                if not orden:
                    print(f"⚠️ Orden {id_orden} no encontrada, saltando...")
                    continue
                
                print(f"🔎 Worker pendiente: Procesando orden {id_orden}...")
                
                # NO cambiar estado, mantener como "pendiente"
                # Procesar despacho directamente desde estado "pendiente"
                disponible = False
                intentos = 0
                max_intentos = 10
                
                while not disponible and intentos < max_intentos:
                    disponible = procesar_despacho(orden)
                    if not disponible:
                        intentos += 1
                        print(f"⏳ Intento {intentos}/{max_intentos}: Inventario para_despacho no disponible para orden {id_orden}, reintentando en 10s…")
                        time.sleep(30)
                
                if disponible:
                    # Si se pudo despachar, cambiar estado a "despachado"
                    orden_actualizada = querys.actualizar_orden(id_orden, estado="despachado")
                    print(f"✅ Orden {id_orden} despachada desde para_despacho")
                else:
                    # Si no se pudo despachar después de intentos, volver a poner en cola pendiente
                    print(f"❌ Orden {id_orden} no pudo ser despachada desde para_despacho después de {max_intentos} intentos")
                    agregar_a_cola(cola_pendientes, lista_pendientes, orden, "pendiente")
                    print(f"🔄 Orden {id_orden} devuelta a cola pendiente")
                
            except Exception as e:
                print(f"❌ Error en worker_cola: {e}")
                time.sleep(5)

def worker_cola_lista():
    """Worker para procesar órdenes listas para despachar"""
    with app.app_context():
        while True:
            try:
                # Usar función sacar_de_cola
                item = sacar_de_cola(cola_listo_para_despachar, lista_listos, "listo_para_despacho")
                
                if not item:
                    time.sleep(5)  # Esperar si la cola está vacía
                    continue
                
                _, id_orden, tipo = item
                orden = querys.obtener_ordenes(id_orden=id_orden)
                
                if not orden:
                    print(f"⚠️ Orden {id_orden} no encontrada, saltando...")
                    continue
                
                print(f"🔎 Worker listos: Procesando orden {id_orden}...")
                
                # Intentar despacho
                disponible = False
                intentos = 0
                max_intentos = 3
                
                while not disponible and intentos < max_intentos:
                    disponible = procesar_despacho(orden)
                    if not disponible:
                        intentos += 1
                        print(f"⏳ Intento {intentos}/{max_intentos}: Inventario no disponible para orden {id_orden}, reintentando en 10s…")
                        time.sleep(10)
                
                if disponible:
                    print(f"✅ Orden {id_orden} despachada correctamente")
                else:
                    print(f"❌ Orden {id_orden} no pudo ser despachada después de {max_intentos} intentos")
                    # Podrías volver a ponerla en cola pendiente si quieres
                    # agregar_a_cola(cola_pendientes, lista_pendientes, orden, "pendiente")
                
            except Exception as e:
                print(f"❌ Error en worker_cola_lista: {e}")
                time.sleep(5)
                
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
    """API unificada para crear una o múltiples órdenes"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({"error": "No se proporcionaron datos JSON"}), 400
        
        # Determinar si es batch o individual
        if 'ordenes' in data:
            return procesar_ordenes_batch(data['ordenes'])
        else:
            return procesar_orden_unica_interna(data)
            
    except Exception as e:
        return jsonify({"error": f"Error en la solicitud: {str(e)}"}), 500
    

def validar_orden(orden_data, indice=None):
    """Validar datos de una orden"""
    prefijo = f"Orden {indice}: " if indice is not None else ""
    
    # Campos requeridos
    required_fields = ['id_venta', 'cliente_nombre', 'direccion_entrega', 'productos']
    for field in required_fields:
        if field not in orden_data:
            raise ValueError(f"{prefijo}Campo requerido faltante: {field}")
    
    # Validar productos
    if not isinstance(orden_data['productos'], list) or len(orden_data['productos']) == 0:
        raise ValueError(f"{prefijo}Debe incluir al menos un producto")
    
    for i, producto in enumerate(orden_data['productos']):
        prod_fields = ['id_producto', 'nombre', 'cantidad']
        for field in prod_fields:
            if field not in producto:
                raise ValueError(f"{prefijo}Producto {i}: Campo requerido faltante: {field}")
    
    # Validar estado
    estado = orden_data.get('estado', 'pendiente')
    estados_validos = ['pendiente', 'listo para despacho', 'despachado']
    if estado not in estados_validos:
        raise ValueError(f"{prefijo}Estado inválido. Debe ser uno de: {estados_validos}")
    
    return True


def procesar_orden_unica_interna(orden_data, indice=None):
    """
    Versión interna de procesar_orden_unica que no retorna jsonify
    Para ser usada dentro de procesar_ordenes_batch
    """
    try:
        # Validar en la API
        prefijo = f"Orden {indice}: " if indice is not None else ""
        validar_orden(orden_data, indice)
        
        orden = querys.crear_orden(orden_data)
        
        # Log opcional según estado - USANDO NUEVAS FUNCIONES
        if orden.estado == "pendiente":
            print(f"📥 Orden {orden.id_orden} creada con estado pendiente")
            agregar_a_cola(cola_pendientes, lista_pendientes, orden, "pendiente")
            
        elif orden.estado == "listo para despacho":
            print(f"🚚 Orden {orden.id_orden} lista para despacho")
            agregar_a_cola(cola_listo_para_despachar, lista_listos, orden, "listo_para_despacho")
            
            # También podrías procesar inmediatamente si quieres
            # procesar_despacho(orden)
        
        # Retornar datos en lugar de jsonify
        return jsonify({
            "orden_id": orden.id_orden,
            "id_venta": orden.id_venta,
            "estado": orden.estado,
            "mensaje": "Orden creada exitosamente",
            "agregada_cola": orden.estado in ["pendiente", "listo para despacho"]
        }), 201
        
    except ValueError as e:
        return jsonify({"error": f"{prefijo}{str(e)}"}), 400
    
    except Exception as e:
        return jsonify({"error": f"{prefijo}Error al crear orden: {str(e)}"}), 500


def procesar_ordenes_batch(lista_ordenes):
    """Procesar múltiples órdenes"""
    try:
        if not isinstance(lista_ordenes, list):
            return jsonify({"error": "El campo 'ordenes' debe ser una lista"}), 400
        
        if len(lista_ordenes) == 0:
            return jsonify({"error": "La lista de órdenes está vacía"}), 400
        
        resultados = []
        errores = []
        
        # Procesar cada orden individualmente usando procesar_orden_unica
        for i, orden_data in enumerate(lista_ordenes):
            try:
                # Llamar a procesar_orden_unica internamente
                response, status_code = procesar_orden_unica_interna(orden_data, i)
                
                if status_code == 201:
                    # Extraer datos de la respuesta exitosa
                    resultados.append({
                        "indice": i,
                        "orden_id": response.json["orden_id"],
                        "id_venta": response.json["id_venta"],
                        "estado": response.json["estado"],
                        "success": True
                    })
                else:
                    errores.append({
                        "indice": i,
                        "error": response.json["error"],
                        "id_venta": orden_data.get('id_venta', 'N/A')
                    })
                    
            except Exception as e:
                errores.append({
                    "indice": i,
                    "error": f"Error interno: {str(e)}",
                    "id_venta": orden_data.get('id_venta', 'N/A')
                })
        
        # Construir respuesta
        response = {
            "procesadas": len(resultados),
            "exitosas": [r["orden_id"] for r in resultados],
            "errores": len(errores)
        }
        
        if resultados:
            response["ordenes"] = resultados
        
        if errores:
            response["detalle_errores"] = errores
        
        status_code = 201 if resultados else 400
        
        return jsonify(response), status_code
        
    except Exception as e:
        return jsonify({"error": f"Error en procesamiento batch: {str(e)}"}), 500
    
# ---------------------------------------
# API: CONSULTAR ORDENES
# ---------------------------------------
@app.route("/api/ordenes", methods=["GET"])
def obtener_ordenes():
    filtros = request.args.to_dict()
    ordenes = querys.obtener_ordenes(**filtros)

    resultado = []
    for o in ordenes:
        orden_dict = {
            "id_orden": o.id_orden,
            "id_venta": o.id_venta,
            "cliente_nombre": o.cliente_nombre,
            "cliente_telefono": o.cliente_telefono,
            "direccion_entrega": o.direccion_entrega,
            "fecha_estimada_entrega": o.fecha_estimada_entrega.isoformat() if o.fecha_estimada_entrega else None,
            "estado": o.estado,
            "fecha_creacion": o.fecha_creacion.isoformat(),
            "detalles": [
                {
                    "id_orden_detalle": d.id_orden_detalle,
                    "id_producto": d.id_producto,
                    "nombre_producto": d.nombre_producto,
                    "cantidad_producto": d.cantidad_producto
                }
                for d in o.detalles
            ]
        }
        resultado.append(orden_dict)

    return jsonify({
        "total": len(resultado),
        "ordenes": resultado
    }), 200


# ---------------------------------------
# API: ACTUALIZAR ORDEN
# ---------------------------------------
@app.route("/api/ordenes/<int:orden_id>", methods=["PUT"])
def actualizar_orden(orden_id, data):
    """Actualizar orden - estilo similar a tu código"""
    orden = OrdenDespacho.query.get(orden_id)
    
    if not orden:
        return None
    
    for campo in ["cliente_nombre", "cliente_telefono", "direccion_entrega", "fecha_estimada_entrega"]:
        if campo in data:
            if campo == "fecha_estimada_entrega" and data[campo]:
                setattr(orden, campo, datetime.strptime(data[campo], '%Y-%m-%d'))
            else:
                setattr(orden, campo, data[campo])
    
    db.session.commit()
    return orden


# ---------------------------------------
# API: CANCELAR ORDEN
# ---------------------------------------
@app.route("/api/ordenes/<int:orden_id>/cancelar", methods=["PATCH"])
def cancelar_orden(orden_id):
    """Cancelar una orden y removerla de las colas si está en alguna"""
    try:
        orden = querys.obtener_ordenes(id_orden=orden_id)
        
        if not orden:
            return jsonify({"error": "Orden no encontrada"}), 404
        
        # Remover de las colas si está en alguna
        remover_de_colas(orden_id)
        
        # Actualizar estado
        orden_actualizada = querys.actualizar_orden(orden_id, estado="cancelada")
        
        return jsonify({
            "mensaje": "Orden cancelada",
            "orden_id": orden_actualizada.id_orden,
            "estado_actual": orden_actualizada.estado,
            "removida_cola": True
        }), 200
        
    except Exception as e:
        return jsonify({"error": f"Error al cancelar orden: {str(e)}"}), 500

def remover_de_colas(orden_id):
    """Remover una orden de todas las colas y listas paralelas"""
    # Buscar en lista_pendientes y remover
    for item in lista_pendientes[:]:  # Copia para iterar
        if item[1] == orden_id:
            lista_pendientes.remove(item)
            print(f"🗑️ Orden {orden_id} removida de cola pendientes")
    
    # Buscar en lista_listos y remover
    for item in lista_listos[:]:  # Copia para iterar
        if item[1] == orden_id:
            lista_listos.remove(item)
            print(f"🗑️ Orden {orden_id} removida de cola listos")
    
    # Nota: No podemos remover directamente de PriorityQueue sin vaciarla
    # Pero las listas paralelas ya están actualizadas
    return True


# ---------------------------------------
# API: ENTREGAR ORDEN
# ---------------------------------------
@app.route("/api/ordenes/<int:orden_id>/entregar", methods=["PATCH"])
def entregar_orden(orden_id):
    # Primero obtener la orden para validar
    orden = querys.obtener_ordenes(orden_id)
    
    if not orden:
        return jsonify({"error": "Orden no encontrada"}), 404
    
    # Validar que no esté cancelada
    if orden.estado == "cancelada":
        return jsonify({"error": "No se puede entregar una orden cancelada"}), 400
    
    # Actualizar estado a entregado
    orden_actualizada = querys.actualizar_orden(orden_id, estado="entregada")
    
    return jsonify({
        "mensaje": "Orden marcada como entregada",
        "orden_id": orden_actualizada.id_orden,
        "estado_anterior": orden.estado,
        "estado_actual": orden_actualizada.estado
    }), 200




@app.route("/api/admin/limpiar-db", methods=["DELETE"])
def limpiar_base_datos_simple():
    """
    ⚠️  Borra TODOS los datos - SOLO para desarrollo
    """
    try:
        # Contar antes de borrar
        total_ordenes = db.session.query(OrdenDespacho).count()
        total_detalles = db.session.query(OrdenDespachoDetalle).count()
        
        # Borrar todo
        db.session.query(OrdenDespachoDetalle).delete()
        db.session.query(OrdenDespacho).delete()
        db.session.commit()
        
        # Vaciar cola
        while not cola_pendientes.empty():
            cola_pendientes.get()
        
        return jsonify({
            "mensaje": "Base de datos limpiada",
            "eliminado": {
                "ordenes": total_ordenes,
                "detalles": total_detalles,
                "cola": "vaciada"
            }
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


# ---------------------------------------
# INICIO DEL SERVICIO
# ---------------------------------------
with app.app_context():
    db.create_all()

    # Restaurar cola de pendientes
    pendientes = querys.obtener_ordenes(estado="pendiente")
    for p in pendientes:
        agregar_a_cola(cola_pendientes, lista_pendientes, p, "pendiente")

    # Restaurar cola de listos para despachar
    listos = querys.obtener_ordenes(estado="listo para despacho")
    for l in listos:
        agregar_a_cola(cola_listo_para_despachar, lista_listos, l, "listo_para_despacho")

    print(f"🔁 Colas restauradas: {len(pendientes)} pendientes, {len(listos)} listos")

# Hilo background
threading.Thread(target=worker_cola, daemon=True).start()
threading.Thread(target=worker_cola_lista, daemon=True).start()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
