import json
from datetime import datetime
from backend.extensions import db


class AIResponse(db.Model):
    """RAG-generated resolution recommendation for a support ticket."""
    __tablename__ = 'ai_responses'

    STATUS_GENERATED = 'GENERATED'
    STATUS_APPROVED = 'APPROVED'
    STATUS_MODIFIED = 'MODIFIED'
    STATUS_REJECTED = 'REJECTED'
    STATUS_ESCALATED = 'ESCALATED'

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('tickets.id', ondelete='CASCADE'), nullable=False, index=True)
    issue_summary = db.Column(db.Text, nullable=False)
    possible_causes = db.Column(db.Text, nullable=False)      # JSON list of strings
    recommended_steps = db.Column(db.Text, nullable=False)    # JSON list of strings
    knowledge_sources = db.Column(db.Text, nullable=True)     # JSON list of source dicts
    similar_tickets = db.Column(db.Text, nullable=True)       # JSON list of similar ticket dicts
    escalation_recommended = db.Column(db.Boolean, default=False)
    confidence_score = db.Column(db.Float, default=0.85)
    
    # Review / Human-in-the-loop tracking
    status = db.Column(db.String(30), default=STATUS_GENERATED, index=True)
    modified_notes = db.Column(db.Text, nullable=True)
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    ticket = db.relationship('Ticket', back_populates='ai_responses')
    reviewer = db.relationship('User', foreign_keys=[reviewed_by_id])

    def get_causes(self):
        try:
            return json.loads(self.possible_causes) if self.possible_causes else []
        except Exception:
            return [self.possible_causes] if self.possible_causes else []

    def get_steps(self):
        try:
            return json.loads(self.recommended_steps) if self.recommended_steps else []
        except Exception:
            return [self.recommended_steps] if self.recommended_steps else []

    def get_sources(self):
        try:
            return json.loads(self.knowledge_sources) if self.knowledge_sources else []
        except Exception:
            return []

    def get_similar_tickets(self):
        try:
            return json.loads(self.similar_tickets) if self.similar_tickets else []
        except Exception:
            return []

    def to_dict(self):
        return {
            'id': self.id,
            'ticket_id': self.ticket_id,
            'issue_summary': self.issue_summary,
            'possible_causes': self.get_causes(),
            'recommended_steps': self.get_steps(),
            'knowledge_sources': self.get_sources(),
            'similar_tickets': self.get_similar_tickets(),
            'escalation_recommended': self.escalation_recommended,
            'confidence_score': round(self.confidence_score * 100, 1),
            'status': self.status,
            'modified_notes': self.modified_notes,
            'reviewed_by': self.reviewer.username if self.reviewer else None,
            'reviewed_at': self.reviewed_at.strftime('%Y-%m-%d %H:%M') if self.reviewed_at else None,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M')
        }

