from flask import Flask, request, jsonify
from database import db
from database.models import OrdenDespacho, OrdenDespachoDetalles
import database.querys as queries
import os
import time
from datetime import datetime
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

app = Flask(__name__)

# Cargar variables de entorno
from dotenv import load_dotenv
load_dotenv()

# Expandir variables de entorno en DATABASE_URL
database_url = os.environ.get('DATABASE_URL', 'sqlite:///despachos.db')
database_url = database_url.replace('${DB_USER}', os.environ.get('DB_USER', ''))
database_url = database_url.replace('${DB_PASSWORD}', os.environ.get('DB_PASSWORD', ''))
database_url = database_url.replace('${DB_HOST}', os.environ.get('DB_HOST', ''))
database_url = database_url.replace('${DB_PORT}', os.environ.get('DB_PORT', ''))
database_url = database_url.replace('${DB_NAME}', os.environ.get('DB_NAME', ''))

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'clave-por-defecto')

print(f"🔗 Conectando a: {app.config['SQLALCHEMY_DATABASE_URI'].replace(os.environ.get('DB_PASSWORD', ''), '***')}")

db.init_app(app)

# El resto del código permanece igual...
def wait_for_db(max_retries=30, retry_interval=2):
    """Esperar a que la base de datos esté disponible"""
    for i in range(max_retries):
        try:
            db.session.execute(text('SELECT 1'))
            print("✅ Base de datos conectada exitosamente")
            return True
        except OperationalError as e:
            if i < max_retries - 1:
                print(f"⚠️  Esperando por base de datos... (intento {i + 1}/{max_retries}) - Error: {e}")
                time.sleep(retry_interval)
            else:
                print(f"❌ No se pudo conectar a la base de datos: {e}")
                return False
    return False

# Health check endpoint
@app.route('/health', methods=['GET'])
def health_check():
    """Health check para la aplicación y base de datos"""
    try:
        # Verificar que la aplicación está funcionando
        app_status = "healthy"
        
        # Verificar conexión a la base de datos
        try:
            db.session.execute(text('SELECT 1'))
            db_status = "healthy"
        except Exception as e:
            db_status = f"unhealthy: {str(e)}"
        
        overall_status = "healthy" if app_status == "healthy" and db_status == "healthy" else "unhealthy"
        
        return jsonify({
            "status": overall_status,
            "timestamp": datetime.utcnow().isoformat(),
            "components": {
                "application": app_status,
                "database": db_status
            }
        }), 200 if overall_status == "healthy" else 503
        
    except Exception as e:
        return jsonify({
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }), 503

# Health check simple (sin verificación de BD)
@app.route('/ready', methods=['GET'])
def readiness_check():
    """Readiness check - verifica si la app está lista para recibir tráfico"""
    return jsonify({
        "status": "ready",
        "timestamp": datetime.utcnow().isoformat()
    }), 200

# Liveness check
@app.route('/alive', methods=['GET'])
def liveness_check():
    """Liveness check - verifica si la app está viva"""
    return jsonify({
        "status": "alive", 
        "timestamp": datetime.utcnow().isoformat()
    }), 200

@app.route('/')
def home():
    return jsonify({
        "mensaje": "Sistema de órdenes de despacho",
        "endpoints": {
            "crear_orden": "POST /api/ordenes",
            "crear_multiples_ordenes": "POST /api/ordenes/batch", 
            "obtener_ordenes": "GET /api/ordenes",
            "obtener_orden": "GET /api/ordenes/<id>",
            "marcar_despachado": "PATCH /api/ordenes/<id>/despachar",
            "health": "GET /health",
            "ready": "GET /ready",
            "alive": "GET /alive"
        },
        "estados_permitidos": ["pendiente", "listo para despacho", "despachado"]
    })

# API para crear una sola orden
@app.route('/api/ordenes', methods=['POST'])
def crear_orden():
    try:
        datos = request.get_json()
        
        # Validaciones básicas
        if not datos:
            return jsonify({"error": "No se proporcionaron datos JSON"}), 400
        
        required_fields = ['id_venta', 'cliente_nombre', 'direccion_entrega', 'productos']
        for field in required_fields:
            if field not in datos:
                return jsonify({"error": f"Campo requerido faltante: {field}"}), 400
        
        # Validar estado
        estado = datos.get('estado', 'pendiente')
        estados_validos = ['pendiente', 'listo para despacho', 'despachado']
        if estado not in estados_validos:
            return jsonify({"error": f"Estado inválido. Debe ser uno de: {estados_validos}"}), 400
        
        # Crear la orden
        orden = queries.crear_orden_completa(datos)
        
        return jsonify({
            "mensaje": "Orden creada exitosamente",
            "orden_id": orden.id_orden,
            "id_venta": orden.id_venta,
            "estado": orden.estado
        }), 201
        
    except Exception as e:
        return jsonify({"error": f"Error al crear orden: {str(e)}"}), 500

# API para crear múltiples órdenes
@app.route('/api/ordenes/batch', methods=['POST'])
def crear_ordenes_batch():
    try:
        datos = request.get_json()
        
        if not datos or 'ordenes' not in datos:
            return jsonify({"error": "Se requiere el campo 'ordenes' con la lista de órdenes"}), 400
        
        resultados = []
        errores = []
        
        for i, orden_data in enumerate(datos['ordenes']):
            try:
                # Validar campos requeridos para cada orden
                required_fields = ['id_venta', 'cliente_nombre', 'direccion_entrega', 'productos']
                for field in required_fields:
                    if field not in orden_data:
                        errores.append(f"Orden {i}: Campo requerido faltante: {field}")
                        continue
                
                # Validar estado
                estado = orden_data.get('estado', 'pendiente')
                estados_validos = ['pendiente', 'listo para despacho', 'despachado']
                if estado not in estados_validos:
                    errores.append(f"Orden {i}: Estado inválido '{estado}'. Debe ser uno de: {estados_validos}")
                    continue
                
                # Crear la orden
                orden = queries.crear_orden_completa(orden_data)
                resultados.append({
                    "indice": i,
                    "orden_id": orden.id_orden,
                    "id_venta": orden.id_venta,
                    "estado": "creada"
                })
                
            except Exception as e:
                errores.append(f"Orden {i} ({orden_data.get('id_venta', 'N/A')}): {str(e)}")
        
        response = {
            "total_procesadas": len(resultados),
            "ordenes_creadas": resultados,
            "total_errores": len(errores)
        }
        
        if errores:
            response["errores"] = errores
        
        status_code = 201 if resultados else 400
        return jsonify(response), status_code
        
    except Exception as e:
        return jsonify({"error": f"Error en procesamiento batch: {str(e)}"}), 500

# API para obtener todas las órdenes
@app.route('/api/ordenes', methods=['GET'])
def obtener_ordenes():
    try:
        ordenes = queries.obtener_todas_ordenes()
        
        resultado = []
        for orden in ordenes:
            orden_data = {
                "id_orden": orden.id_orden,
                "id_venta": orden.id_venta,
                "cliente_nombre": orden.cliente_nombre,
                "cliente_telefono": orden.cliente_telefono,
                "direccion_entrega": orden.direccion_entrega,
                "fecha_estimada_entrega": orden.fecha_estimada_entrega.isoformat() if orden.fecha_estimada_entrega else None,
                "estado": orden.estado,
                "fecha_creacion": orden.fecha_creacion.isoformat(),
                "productos": []
            }
            
            # Agregar productos
            for detalle in orden.detalles:
                orden_data["productos"].append({
                    "id_producto": detalle.id_producto,
                    "nombre": detalle.nombre_producto,
                    "cantidad": detalle.cantidad_producto
                })
            
            resultado.append(orden_data)
        
        return jsonify({
            "total_ordenes": len(resultado),
            "ordenes": resultado
        })
        
    except Exception as e:
        return jsonify({"error": f"Error al obtener órdenes: {str(e)}"}), 500

# API para obtener una orden específica
@app.route('/api/ordenes/<int:orden_id>', methods=['GET'])
def obtener_orden(orden_id):
    try:
        orden = queries.obtener_orden_por_id(orden_id)
        
        if not orden:
            return jsonify({"error": "Orden no encontrada"}), 404
        
        orden_data = {
            "id_orden": orden.id_orden,
            "id_venta": orden.id_venta,
            "cliente_nombre": orden.cliente_nombre,
            "cliente_telefono": orden.cliente_telefono,
            "direccion_entrega": orden.direccion_entrega,
            "fecha_estimada_entrega": orden.fecha_estimada_entrega.isoformat() if orden.fecha_estimada_entrega else None,
            "estado": orden.estado,
            "fecha_creacion": orden.fecha_creacion.isoformat(),
            "productos": []
        }
        
        # Agregar productos
        for detalle in orden.detalles:
            orden_data["productos"].append({
                "id_producto": detalle.id_producto,
                "nombre": detalle.nombre_producto,
                "cantidad": detalle.cantidad_producto
            })
        
        return jsonify(orden_data)
        
    except Exception as e:
        return jsonify({"error": f"Error al obtener orden: {str(e)}"}), 500

# API para marcar una orden como despachada
@app.route('/api/ordenes/<int:orden_id>/despachar', methods=['PATCH'])
def marcar_orden_despachada(orden_id):
    try:
        orden, error = queries.marcar_como_despachado(orden_id)
        
        if error:
            if "no encontrada" in error:
                return jsonify({"error": error}), 404
            else:
                return jsonify({"error": error}), 400
        
        return jsonify({
            "mensaje": "Orden marcada como despachada exitosamente",
            "orden_id": orden.id_orden,
            "id_venta": orden.id_venta,
            "estado_anterior": "pendiente/listo para despacho",
            "estado_actual": orden.estado
        })
        
    except Exception as e:
        return jsonify({"error": f"Error al actualizar orden: {str(e)}"}), 500

# Inicialización de la base de datos
with app.app_context():
    try:
        if wait_for_db():
            db.create_all()
            print("✅ Tablas creadas exitosamente")
        else:
            print("⚠️  No se pudieron crear las tablas - la base de datos no está disponible")
    except Exception as e:
        print(f"❌ Error al crear tablas: {e}")

if __name__ == '__main__':
    host = os.environ.get('FLASK_HOST', '0.0.0.0')
    port = int(os.environ.get('FLASK_PORT', 5000))
    app.run(debug=True, host=host, port=port)