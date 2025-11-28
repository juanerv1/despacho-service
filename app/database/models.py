from . import db
from datetime import datetime

class OrdenDespacho(db.Model):
    __tablename__ = 'orden_despacho'
    
    id_orden = db.Column(db.Integer, primary_key=True)
    id_venta = db.Column(db.Integer, nullable=False)
    cliente_nombre = db.Column(db.String(100), nullable=False)
    cliente_telefono = db.Column(db.String(20))
    direccion_entrega = db.Column(db.Text, nullable=False)
    fecha_estimada_entrega = db.Column(db.Date)
    estado = db.Column(db.String(50), default='pendiente')
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relación con los detalles
    detalles = db.relationship('OrdenDespachoDetalles', backref='orden', lazy=True)

class OrdenDespachoDetalles(db.Model):
    __tablename__ = 'orden_despacho_detalles'
    
    id_orden_detalle = db.Column(db.Integer, primary_key=True)
    id_orden = db.Column(db.Integer, db.ForeignKey('orden_despacho.id_orden'), nullable=False)
    id_producto = db.Column(db.Integer, nullable=False)
    nombre_producto = db.Column(db.String(200), nullable=False)
    cantidad_producto = db.Column(db.Integer, nullable=False)