from . import db
from .models import OrdenDespacho, OrdenDespachoDetalles
from datetime import datetime

def crear_orden_despacho(id_venta, cliente_nombre, direccion_entrega, cliente_telefono=None, fecha_estimada_entrega=None, estado="pendiente"):
    """Crear una nueva orden de despacho"""
    orden = OrdenDespacho(
        id_venta=id_venta,
        cliente_nombre=cliente_nombre,
        cliente_telefono=cliente_telefono,
        direccion_entrega=direccion_entrega,
        fecha_estimada_entrega=datetime.strptime(fecha_estimada_entrega, '%Y-%m-%d').date() if fecha_estimada_entrega else None,
        estado=estado
    )
    db.session.add(orden)
    db.session.commit()
    return orden

def agregar_detalle_orden(id_orden, id_producto, nombre_producto, cantidad_producto):
    """Agregar un producto a la orden de despacho"""
    detalle = OrdenDespachoDetalles(
        id_orden=id_orden,
        id_producto=id_producto,
        nombre_producto=nombre_producto,
        cantidad_producto=cantidad_producto
    )
    db.session.add(detalle)
    db.session.commit()
    return detalle

def obtener_orden_por_id(id_orden):
    """Obtener una orden con todos sus detalles"""
    return OrdenDespacho.query.get(id_orden)

def obtener_todas_ordenes():
    """Obtener todas las órdenes de despacho"""
    return OrdenDespacho.query.all()

def actualizar_estado_orden(id_orden, nuevo_estado):
    """Actualizar el estado de una orden"""
    orden = OrdenDespacho.query.get(id_orden)
    if orden:
        orden.estado = nuevo_estado
        db.session.commit()
    return orden

def marcar_como_despachado(id_orden):
    """Marcar una orden como despachada con validaciones"""
    orden = OrdenDespacho.query.get(id_orden)
    
    if not orden:
        return None, "Orden no encontrada"
    
    if orden.estado == "despachado":
        return orden, "La orden ya está despachada"
    
    if orden.estado not in ["pendiente", "listo para despacho"]:
        return orden, f"No se puede despachar una orden en estado: {orden.estado}"
    
    orden.estado = "despachado"
    db.session.commit()
    
    return orden, None

def crear_orden_completa(datos_orden):
    """Crear una orden completa con sus productos"""
    try:
        # Crear la orden principal
        orden = crear_orden_despacho(
            id_venta=datos_orden['id_venta'],
            cliente_nombre=datos_orden['cliente_nombre'],
            cliente_telefono=datos_orden.get('cliente_telefono'),
            direccion_entrega=datos_orden['direccion_entrega'],
            fecha_estimada_entrega=datos_orden.get('fecha_estimada_envio'),
            estado=datos_orden.get('estado', 'pendiente')
        )
        
        # Agregar los productos
        for producto in datos_orden['productos']:
            agregar_detalle_orden(
                id_orden=orden.id_orden,
                id_producto=producto['id_producto'],
                nombre_producto=producto['nombre'],
                cantidad_producto=producto['cantidad']
            )
        
        return orden
    except Exception as e:
        db.session.rollback()
        raise e