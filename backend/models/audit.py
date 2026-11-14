from datetime import datetime
from backend.extensions import db


class AuditLog(db.Model):
    """Audit logging table for system tracking and compliance."""
    __tablename__ = 'audit_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    action = db.Column(db.String(100), nullable=False, index=True)
    entity_type = db.Column(db.String(50), nullable=False)
    entity_id = db.Column(db.String(50), nullable=True)
    details = db.Column(db.Text, nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    user = db.relationship('User', foreign_keys=[user_id])

    @classmethod
    def log(cls, action: str, entity_type: str, entity_id=None, user_id=None, details=None):
        """Helper to create and persist an audit log entry."""
        log_entry = cls(
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            user_id=user_id,
            details=str(details) if details else None
        )
        db.session.add(log_entry)
        db.session.commit()
        return log_entry

    def to_dict(self):
        return {
            'id': self.id,
            'user': self.user.username if self.user else 'System',
            'action': self.action,
            'entity_type': self.entity_type,
            'entity_id': self.entity_id,
            'details': self.details,
            'timestamp': self.timestamp.strftime('%Y-%m-%d %H:%M:%S')
        }

