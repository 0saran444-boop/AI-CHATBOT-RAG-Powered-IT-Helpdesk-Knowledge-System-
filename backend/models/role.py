from datetime import datetime
from backend.extensions import db


class Role(db.Model):
    """Role model for Role-Based Access Control (RBAC)."""
    __tablename__ = 'roles'

    # Predefined role names
    ADMIN = 'Admin'
    SUPPORT_AGENT = 'Support Agent'
    EMPLOYEE = 'Employee'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    users = db.relationship('User', back_populates='role', lazy='dynamic')

    def __repr__(self):
        return f"<Role {self.name}>"

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

