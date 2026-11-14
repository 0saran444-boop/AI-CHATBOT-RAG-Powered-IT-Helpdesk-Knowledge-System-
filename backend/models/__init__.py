from backend.extensions import db
from backend.models.role import Role
from backend.models.user import User
from backend.models.ticket import (
    TicketCategory, Ticket, TicketComment, TicketAttachment, 
    TicketStatusHistory, TicketEscalation, TicketFeedback
)
from backend.models.knowledge import KnowledgeDocument, KnowledgeChunk, KnowledgeDocumentVersion
from backend.models.ai_response import AIResponse
from backend.models.sla import SLAPolicy
from backend.models.audit import AuditLog

__all__ = [
    'db',
    'Role',
    'User',
    'TicketCategory',
    'Ticket',
    'TicketComment',
    'TicketAttachment',
    'TicketStatusHistory',
    'TicketEscalation',
    'TicketFeedback',
    'KnowledgeDocument',
    'KnowledgeChunk',
    'AIResponse',
    'SLAPolicy',
    'AuditLog'
]
