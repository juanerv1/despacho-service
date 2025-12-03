from database.models import db, OrdenDespacho, OrdenDespachoDetalle

def crear_orden(data, detalles):
    orden = OrdenDespacho(
        id_venta=data["id_venta"],
        cliente_nombre=data["cliente_nombre"],
        cliente_telefono=data["cliente_telefono"],
        direccion_entrega=data["direccion_entrega"],
        fecha_estimada_entrega=data.get("fecha_estimada_entrega"),
        estado=data["estado"]
    )

    db.session.add(orden)
    db.session.flush()

    for d in detalles:
        det = OrdenDespachoDetalle(
            id_orden=orden.id_orden,
            id_producto=d["id_producto"],
            nombre_producto=d["nombre_producto"],
            cantidad_producto=d["cantidad_producto"]
        )
        db.session.add(det)

    db.session.commit()
    return orden


def obtener_orden_por_id(id_orden):
    return OrdenDespacho.query.get(id_orden)


def obtener_ordenes(filtros):
    query = OrdenDespacho.query

    if "estado" in filtros:
        query = query.filter_by(estado=filtros["estado"])

    if "id_venta" in filtros:
        query = query.filter_by(id_venta=filtros["id_venta"])

    return query.all()
