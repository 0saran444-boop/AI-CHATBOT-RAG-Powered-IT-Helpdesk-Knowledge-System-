from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user

from backend.extensions import db
from backend.models.ticket import Ticket, TicketCategory, TicketComment, TicketFeedback
from backend.models.knowledge import KnowledgeDocument
from backend.models.ai_response import AIResponse
from backend.models.sla import SLAPolicy
from backend.services.ticket_service import TicketService
from backend.services.rag_service import RAGService

api_bp = Blueprint('api', __name__, url_prefix='/api')


@api_bp.route('/tickets', methods=['GET'])
@login_required
def get_tickets():
    """List tickets for current authenticated user/role."""
    if current_user.is_employee:
        tickets = Ticket.query.filter_by(created_by_id=current_user.id).all()
    else:
        tickets = Ticket.query.all()
    return jsonify([t.to_dict() for t in tickets])


@api_bp.route('/tickets/<int:ticket_id>', methods=['GET'])
@login_required
def get_ticket(ticket_id: int):
    """Fetch single ticket details."""
    ticket = Ticket.query.get_or_404(ticket_id)
    if current_user.is_employee and ticket.created_by_id != current_user.id:
        return jsonify({'error': 'Unauthorized'}), 403
    return jsonify(ticket.to_dict())


@api_bp.route('/tickets/<int:ticket_id>/ai-analysis', methods=['GET', 'POST'])
@login_required
def ticket_ai_analysis(ticket_id: int):
    """Retrieve or trigger RAG resolution analysis for a ticket."""
    ticket = Ticket.query.get_or_404(ticket_id)
    if current_user.is_employee and ticket.created_by_id != current_user.id:
        return jsonify({'error': 'Unauthorized'}), 403

    if request.method == 'POST' or not ticket.latest_ai_response:
        ai_resp = RAGService.generate_resolution(ticket.id)
    else:
        ai_resp = ticket.latest_ai_response

    return jsonify(ai_resp.to_dict() if ai_resp else {'error': 'Failed to generate analysis'})


@api_bp.route('/knowledge', methods=['GET'])
@login_required
def get_knowledge():
    """List indexed knowledge base documents."""
    docs = KnowledgeDocument.query.all()
    return jsonify([d.to_dict() for d in docs])


@api_bp.route('/sla', methods=['GET'])
@login_required
def get_sla():
    """Fetch configured SLA policies."""
    policies = SLAPolicy.query.all()
    return jsonify([p.to_dict() for p in policies])


@api_bp.route('/dashboard', methods=['GET'])
@login_required
def get_dashboard_stats():
    """Return dashboard summary metrics."""
    total = Ticket.query.count()
    open_count = Ticket.query.filter(Ticket.status.notin_([Ticket.STATUS_RESOLVED, Ticket.STATUS_CLOSED])).count()
    resolved_count = Ticket.query.filter(Ticket.status.in_([Ticket.STATUS_RESOLVED, Ticket.STATUS_CLOSED])).count()
    return jsonify({
        'total_tickets': total,
        'open_tickets': open_count,
        'resolved_tickets': resolved_count,
        'user_role': current_user.role.name if current_user.role else 'Employee'
    })

