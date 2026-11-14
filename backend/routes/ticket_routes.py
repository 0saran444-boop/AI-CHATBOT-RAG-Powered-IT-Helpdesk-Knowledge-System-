from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
import os

from backend.extensions import db
from backend.models.ticket import Ticket, TicketCategory, TicketComment, TicketAttachment, TicketStatusHistory, TicketFeedback
from backend.models.ai_response import AIResponse
from backend.models.user import User
from backend.models.role import Role
from backend.services.ticket_service import TicketService
from backend.services.rag_service import RAGService
from backend.models.audit import AuditLog

ticket_bp = Blueprint('tickets', __name__, url_prefix='/tickets')


@ticket_bp.route('', methods=['GET'])
@ticket_bp.route('/', methods=['GET'])
@login_required
def list_tickets():
    """List tickets filtered by user role and search query parameters."""
    query = Ticket.query

    # Role-based scoping
    if current_user.is_employee:
        query = query.filter_by(created_by_id=current_user.id)
    elif current_user.role.name == Role.SUPPORT_AGENT:
        # Support engineers see assigned tickets or queue
        filter_mode = request.args.get('view', 'all')
        if filter_mode == 'assigned':
            query = query.filter_by(assigned_to_id=current_user.id)
        elif filter_mode == 'unassigned':
            query = query.filter_by(assigned_to_id=None)

    # Search & filters
    search_term = request.args.get('q', '').strip()
    status_filter = request.args.get('status')
    priority_filter = request.args.get('priority')
    category_filter = request.args.get('category')

    if search_term:
        query = query.filter(
            (Ticket.ticket_number.ilike(f"%{search_term}%")) |
            (Ticket.title.ilike(f"%{search_term}%")) |
            (Ticket.description.ilike(f"%{search_term}%"))
        )
    if status_filter:
        query = query.filter_by(status=status_filter)
    if priority_filter:
        query = query.filter_by(priority=priority_filter)
    if category_filter:
        query = query.filter_by(category_id=category_filter)

    tickets = query.order_by(Ticket.created_at.desc()).all()
    categories = TicketCategory.query.all()

    return render_template(
        'tickets/ticket_list.html',
        tickets=tickets,
        categories=categories,
        search_term=search_term,
        selected_status=status_filter,
        selected_priority=priority_filter,
        selected_category=int(category_filter) if category_filter else None
    )


@ticket_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create_ticket():
    """Create a new IT support ticket."""
    categories = TicketCategory.query.all()

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        category_id = request.form.get('category_id')
        category_id = int(category_id) if category_id else None
        priority = request.form.get('priority')

        if not title or not description:
            flash("Please provide both a title and description for your issue.", 'danger')
            return render_template('tickets/create_ticket.html', categories=categories, title=title, description=description)

        # 1. Create ticket (with auto-classification & SLA deadline)
        ticket = TicketService.create_ticket(
            title=title,
            description=description,
            user_id=current_user.id,
            category_id=category_id,
            priority=priority
        )

        # 2. Handle optional file attachment
        file = request.files.get('attachment')
        if file and file.filename:
            filename = secure_filename(file.filename)
            upload_dir = current_app.config['UPLOADS_DIR']
            upload_dir.mkdir(parents=True, exist_ok=True)
            save_path = upload_dir / f"{ticket.ticket_number}_{filename}"
            file.save(str(save_path))

            att = TicketAttachment(
                ticket_id=ticket.id,
                user_id=current_user.id,
                filename=filename,
                file_path=str(save_path),
                file_size=save_path.stat().st_size
            )
            db.session.add(att)
            db.session.commit()

        # 3. Automatically generate RAG resolution recommendation in background/pipeline
        try:
            RAGService.generate_resolution(ticket.id)
        except Exception as e:
            print(f"[RAG] Automatic resolution generation failed: {e}")

        flash(f"Ticket {ticket.ticket_number} created successfully! Our IT team and AI assistant are analyzing your issue.", 'success')
        return redirect(url_for('tickets.view_ticket', ticket_id=ticket.id))

    return render_template('tickets/create_ticket.html', categories=categories)


@ticket_bp.route('/<int:ticket_id>', methods=['GET'])
@login_required
def view_ticket(ticket_id: int):
    """
    Ticket Resolution Workspace (Section 44 Showcase Screen).
    Displays employee issue, AI Analysis panel, knowledge citations, similar historical tickets,
    comments, and resolution actions.
    """
    ticket = Ticket.query.get_or_404(ticket_id)

    # Permission check: Employees can only view their own tickets
    if current_user.is_employee and ticket.created_by_id != current_user.id:
        flash("You are not authorized to view this ticket.", 'danger')
        return redirect(url_for('tickets.list_tickets'))

    engineers = User.query.join(Role).filter(Role.name.in_([Role.ADMIN, Role.SUPPORT_AGENT])).all()
    ai_response = ticket.latest_ai_response

    # If no AI response exists yet, generate one on-demand for support engineer
    if not ai_response and not current_user.is_employee:
        ai_response = RAGService.generate_resolution(ticket.id)

    return render_template(
        'tickets/ticket_detail.html',
        ticket=ticket,
        ai_response=ai_response,
        engineers=engineers
    )


@ticket_bp.route('/<int:ticket_id>/ai-action', methods=['POST'])
@login_required
def handle_ai_action(ticket_id: int):
    """
    Handle Human-in-the-Loop review actions on AI suggestions:
    Approve, Modify, Reject, or Escalate (supports both AJAX and standard POST).
    """
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json or 'application/json' in request.headers.get('Accept', '')

    if current_user.is_employee:
        if is_ajax:
            return jsonify({'success': False, 'error': 'Unauthorized action.'}), 403
        flash("Unauthorized action.", 'danger')
        return redirect(url_for('tickets.view_ticket', ticket_id=ticket_id))

    ticket = Ticket.query.get_or_404(ticket_id)
    ai_response = ticket.latest_ai_response
    if not ai_response:
        if is_ajax:
            return jsonify({'success': False, 'error': 'No active AI recommendation found.'}), 404
        flash("No active AI recommendation found.", 'warning')
        return redirect(url_for('tickets.view_ticket', ticket_id=ticket_id))

    if request.is_json:
        data = request.get_json() or {}
        action = data.get('action')
        modified_notes = data.get('modified_notes', '').strip()
        escalation_reason = data.get('escalation_reason')
    else:
        action = request.form.get('action')  # APPROVE, MODIFY, REJECT, ESCALATE
        modified_notes = request.form.get('modified_notes', '').strip()
        escalation_reason = request.form.get('escalation_reason')

    message = ""
    if action == 'APPROVE':
        ai_response.status = AIResponse.STATUS_APPROVED
        ai_response.reviewed_by_id = current_user.id
        ai_response.reviewed_at = db.func.now()
        steps = ai_response.get_steps()
        if not ticket.action_taken and steps:
            ticket.action_taken = "\n".join(steps)
        AuditLog.log("AI_APPROVED", "AIResponse", ai_response.id, current_user.id, f"Approved AI suggestion for {ticket.ticket_number}")
        message = "AI recommendation approved as resolution guidance."
        flash(message, 'success')

    elif action == 'MODIFY':
        ai_response.status = AIResponse.STATUS_MODIFIED
        ai_response.modified_notes = modified_notes
        ai_response.reviewed_by_id = current_user.id
        ai_response.reviewed_at = db.func.now()
        AuditLog.log("AI_MODIFIED", "AIResponse", ai_response.id, current_user.id, f"Modified AI suggestion for {ticket.ticket_number}")
        message = "AI recommendation modified and saved."
        flash(message, 'info')

    elif action == 'REJECT':
        ai_response.status = AIResponse.STATUS_REJECTED
        ai_response.modified_notes = modified_notes
        ai_response.reviewed_by_id = current_user.id
        ai_response.reviewed_at = db.func.now()
        AuditLog.log("AI_REJECTED", "AIResponse", ai_response.id, current_user.id, f"Rejected AI suggestion for {ticket.ticket_number}")
        message = "AI recommendation rejected. Proceeding with manual resolution."
        flash(message, 'warning')

    elif action == 'ESCALATE':
        ai_response.status = AIResponse.STATUS_ESCALATED
        ai_response.reviewed_by_id = current_user.id
        ai_response.reviewed_at = db.func.now()
        reason = escalation_reason or 'Escalated based on AI recommendation complexity'
        TicketService.escalate_ticket(ticket.id, reason, current_user.id)
        message = f"Ticket {ticket.ticket_number} escalated successfully."
        flash(message, 'warning')
        if is_ajax:
            return jsonify({'success': True, 'action': action, 'status': ai_response.status, 'message': message})
        return redirect(url_for('tickets.view_ticket', ticket_id=ticket_id))

    db.session.commit()
    if is_ajax:
        return jsonify({'success': True, 'action': action, 'status': ai_response.status, 'message': message})
    return redirect(url_for('tickets.view_ticket', ticket_id=ticket_id))


@ticket_bp.route('/<int:ticket_id>/resolve', methods=['POST'])
@login_required
def resolve_ticket(ticket_id: int):
    """Mark ticket as resolved with Root Cause, Action Taken, and Resolution Summary."""
    if current_user.is_employee:
        flash("Employees cannot resolve tickets.", 'danger')
        return redirect(url_for('tickets.view_ticket', ticket_id=ticket_id))

    root_cause = request.form.get('root_cause', '').strip()
    action_taken = request.form.get('action_taken', '').strip()
    resolution_summary = request.form.get('resolution_summary', '').strip()

    if not root_cause or not resolution_summary:
        flash("Please provide both a root cause and resolution summary.", 'danger')
        return redirect(url_for('tickets.view_ticket', ticket_id=ticket_id))

    TicketService.resolve_ticket(
        ticket_id=ticket_id,
        root_cause=root_cause,
        action_taken=action_taken or 'Troubleshooting completed',
        resolution_summary=resolution_summary,
        user_id=current_user.id
    )
    flash("Ticket marked as RESOLVED! The employee has been notified to provide feedback.", 'success')
    return redirect(url_for('tickets.view_ticket', ticket_id=ticket_id))


@ticket_bp.route('/<int:ticket_id>/feedback', methods=['POST'])
@login_required
def submit_feedback(ticket_id: int):
    """Employee feedback submission."""
    ticket = Ticket.query.get_or_404(ticket_id)
    if ticket.created_by_id != current_user.id:
        flash("Only the ticket creator can submit feedback.", 'danger')
        return redirect(url_for('tickets.view_ticket', ticket_id=ticket_id))

    rating = int(request.form.get('rating', 5))
    comment = request.form.get('comment', '').strip()
    ai_useful = request.form.get('ai_useful') == 'yes'

    TicketService.submit_feedback(ticket.id, current_user.id, rating, comment, ai_useful)
    flash("Thank you for your feedback! It helps improve our IT support and RAG models.", 'success')
    return redirect(url_for('tickets.view_ticket', ticket_id=ticket_id))


@ticket_bp.route('/<int:ticket_id>/assign', methods=['POST'])
@login_required
def assign_ticket(ticket_id: int):
    """Assign ticket to engineer (supports both standard POST and AJAX)."""
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json or 'application/json' in request.headers.get('Accept', '')

    if current_user.is_employee:
        if is_ajax:
            return jsonify({'success': False, 'error': 'Unauthorized action.'}), 403
        flash("Unauthorized action.", 'danger')
        return redirect(url_for('tickets.view_ticket', ticket_id=ticket_id))

    if request.is_json:
        data = request.get_json() or {}
        engineer_id = int(data.get('engineer_id', 0))
    else:
        engineer_id = int(request.form.get('engineer_id', 0))

    ticket = TicketService.assign_ticket(ticket_id, engineer_id, current_user.id)
    engineer = User.query.get(engineer_id)

    if is_ajax:
        return jsonify({
            'success': True,
            'assigned_to': engineer.username if engineer else 'Unassigned',
            'role': engineer.role.name if engineer and engineer.role else 'Engineer',
            'message': f"Ticket assigned to {engineer.username if engineer else 'engineer'}."
        })

    flash("Ticket assigned successfully.", 'success')
    return redirect(url_for('tickets.view_ticket', ticket_id=ticket_id))


@ticket_bp.route('/<int:ticket_id>/comment', methods=['POST'])
@login_required
def add_comment(ticket_id: int):
    """Add discussion comment to ticket (supports both standard POST and AJAX)."""
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json or 'application/json' in request.headers.get('Accept', '')

    if request.is_json:
        data = request.get_json() or {}
        comment_text = data.get('comment', '').strip()
    else:
        comment_text = request.form.get('comment', '').strip()

    if not comment_text:
        if is_ajax:
            return jsonify({'success': False, 'error': 'Comment cannot be empty.'}), 400
        flash("Comment cannot be empty.", 'warning')
        return redirect(url_for('tickets.view_ticket', ticket_id=ticket_id))

    comment = TicketService.add_comment(ticket_id, current_user.id, comment_text)

    if is_ajax:
        return jsonify({
            'success': True,
            'comment': {
                'id': comment.id,
                'text': comment.comment,
                'author': current_user.username,
                'role': current_user.role.name if current_user.role else 'Employee',
                'is_employee': current_user.is_employee,
                'created_at': comment.created_at.strftime('%b %d, %H:%M')
            }
        })

    flash("Comment added.", 'info')
    return redirect(url_for('tickets.view_ticket', ticket_id=ticket_id))


@ticket_bp.route('/<int:ticket_id>/status', methods=['POST'])
@login_required
def update_status(ticket_id: int):
    """Update ticket lifecycle status (supports both standard POST and AJAX)."""
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json or 'application/json' in request.headers.get('Accept', '')

    if current_user.is_employee:
        if is_ajax:
            return jsonify({'success': False, 'error': 'Unauthorized action.'}), 403
        flash("Unauthorized action.", 'danger')
        return redirect(url_for('tickets.view_ticket', ticket_id=ticket_id))

    if request.is_json:
        data = request.get_json() or {}
        new_status = data.get('status')
        notes = data.get('notes')
    else:
        new_status = request.form.get('status')
        notes = request.form.get('notes')

    ticket = TicketService.update_status(ticket_id, new_status, current_user.id, notes)

    if is_ajax:
        return jsonify({
            'success': True,
            'status': new_status,
            'message': f"Ticket status updated to {new_status}."
        })

    flash(f"Ticket status updated to {new_status}.", 'info')
    return redirect(url_for('tickets.view_ticket', ticket_id=ticket_id))

