from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class OrdenDespacho(db.Model):
    __tablename__ = "orden_despacho"

    id_orden = db.Column(db.Integer, primary_key=True)
    id_venta = db.Column(db.Integer, nullable=False)
    cliente_nombre = db.Column(db.String(120), nullable=False)
    cliente_telefono = db.Column(db.String(30), nullable=False)
    direccion_entrega = db.Column(db.String(250), nullable=False)
    fecha_estimada_entrega = db.Column(db.DateTime, nullable=True)
    estado = db.Column(db.String(40), default="pendiente")
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)

    detalles = db.relationship(
        "OrdenDespachoDetalle",
        backref="orden",
        cascade="all, delete-orphan",
        lazy=True
    )


class OrdenDespachoDetalle(db.Model):
    __tablename__ = "orden_despacho_detalles"

    id_orden_detalle = db.Column(db.Integer, primary_key=True)
    id_orden = db.Column(db.Integer, db.ForeignKey("orden_despacho.id_orden"))
    id_producto = db.Column(db.Integer, nullable=False)
    nombre_producto = db.Column(db.String(120), nullable=False)
    cantidad_producto = db.Column(db.Integer, nullable=False)
