from datetime import datetime
from database.models import db, OrdenDespacho, OrdenDespachoDetalle

def crear_orden(data):
    
    try:
        orden = OrdenDespacho(
            id_venta=data["id_venta"],
            cliente_nombre=data["cliente_nombre"],
            cliente_telefono=data["cliente_telefono"],
            direccion_entrega=data["direccion_entrega"],
            fecha_estimada_entrega=datetime.strptime(data.get("fecha_estimada_entrega"), '%Y-%m-%d') 
            if data.get("fecha_estimada_entrega") else None,
            estado=data["estado"]
        )

        db.session.add(orden)
        db.session.flush()

        for d in data["productos"]:
            det = OrdenDespachoDetalle(
                id_orden=orden.id_orden,
                id_producto=d["id_producto"],
                nombre_producto=d["nombre"],
                cantidad_producto=d["cantidad"]
            )
            db.session.add(det)

        db.session.commit()
        return orden
    
    except Exception as e:
        db.session.rollback()
        raise e


def actualizar_orden(orden_id, **campos):
    """Actualizar una orden existente"""
    orden = OrdenDespacho.query.get(orden_id)
    
    if not orden:
        return None
    
    for campo, valor in campos.items():
        if hasattr(orden, campo):
            # Manejo especial para fecha
            if campo == "fecha_estimada_entrega" and valor:
                setattr(orden, campo, datetime.strptime(valor, '%Y-%m-%d'))
            else:
                setattr(orden, campo, valor)
    
    db.session.commit()
    return orden


def obtener_ordenes(id_orden=None, **filtros):
    """Obtener órdenes - puede ser por ID específico o con filtros"""
    
    # Si se pasa un ID específico, devolver esa orden
    if id_orden is not None:
        return OrdenDespacho.query.get(id_orden)
    
    # Si no hay ID, aplicar filtros
    query = OrdenDespacho.query
    
    if "estado" in filtros:
        query = query.filter_by(estado=filtros["estado"])
    
    if "id_venta" in filtros:
        query = query.filter_by(id_venta=filtros["id_venta"])
    
    return query.all()