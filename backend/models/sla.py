from datetime import datetime
from backend.extensions import db


class SLAPolicy(db.Model):
    """SLA policy mapping ticket priority to resolution deadline hours."""
    __tablename__ = 'sla_policies'

    id = db.Column(db.Integer, primary_key=True)
    priority = db.Column(db.String(20), unique=True, nullable=False)  # LOW, MEDIUM, HIGH, CRITICAL
    resolution_time_hours = db.Column(db.Integer, nullable=False, default=8)
    response_time_hours = db.Column(db.Integer, nullable=False, default=2)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @classmethod
    def seed_default_policies(cls):
        """Seed default SLA policies if they do not exist."""
        defaults = [
            ('CRITICAL', 1, 0),
            ('HIGH', 4, 1),
            ('MEDIUM', 8, 2),
            ('LOW', 24, 4)
        ]
        for priority, res_hours, resp_hours in defaults:
            existing = cls.query.filter_by(priority=priority).first()
            if not existing:
                policy = cls(
                    priority=priority,
                    resolution_time_hours=res_hours,
                    response_time_hours=resp_hours
                )
                db.session.add(policy)
        db.session.commit()

    def to_dict(self):
        return {
            'id': self.id,
            'priority': self.priority,
            'resolution_time_hours': self.resolution_time_hours,
            'response_time_hours': self.response_time_hours
        }

