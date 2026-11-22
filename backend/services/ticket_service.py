from datetime import datetime, timedelta
from typing import Optional, Tuple
from backend.extensions import db
from backend.models.ticket import (
    Ticket, TicketCategory, TicketComment, 
    TicketStatusHistory, TicketEscalation, TicketFeedback
)
from backend.models.sla import SLAPolicy
from backend.models.audit import AuditLog
from backend.models.user import User


class TicketService:
    """Service handling IT support ticket lifecycle, auto-classification, and SLA calculations."""

    @staticmethod
    def auto_classify(title: str, description: str) -> Tuple[Optional[int], str, str]:
        """
        Analyze issue text and determine Category, Subcategory, and Priority.
        Returns: (category_id, subcategory, priority)
        """
        text = f"{title} {description}".lower()

        cat_name = 'Other'
        subcat = 'General Inquiry'
        priority = Ticket.PRIORITY_MEDIUM

        # Priority rules
        if any(w in text for w in ['outage', 'entire company', 'server down', 'critical', 'breach', 'ransomware', 'emergency']):
            priority = Ticket.PRIORITY_CRITICAL
        elif any(w in text for w in ['cannot access', 'blocked', 'urgent', 'fails', 'broken', 'error', 'deadline', 'cannot work']):
            priority = Ticket.PRIORITY_HIGH
        elif any(w in text for w in ['slow', 'minor', 'how to', 'request', 'info', 'question']):
            priority = Ticket.PRIORITY_LOW

        # Category rules
        if any(w in text for w in ['vpn', 'tunnel', 'anyconnect', 'globalprotect', 'cisco vpn']):
            cat_name = 'VPN'
            subcat = 'VPN Client / Routing'
            if priority == Ticket.PRIORITY_MEDIUM:
                priority = Ticket.PRIORITY_HIGH
        elif any(w in text for w in ['wifi', 'network', 'ethernet', 'internet', 'dns', 'gateway', 'subnet', 'router', 'switch']):
            cat_name = 'Network'
            subcat = 'Connectivity & DNS'
        elif any(w in text for w in ['mail', 'outlook', 'exchange', 'inbox', 'smtp', 'imap', 'spam']):
            cat_name = 'Email'
            subcat = 'Mailbox & Sync'
        elif any(w in text for w in ['server', 'ssh', 'active directory', 'rdp', 'linux', 'windows server', 'vmware']):
            cat_name = 'Server'
            subcat = 'Server Access & Host'
            if priority == Ticket.PRIORITY_MEDIUM:
                priority = Ticket.PRIORITY_HIGH
        elif any(w in text for w in ['password', 'login', 'sso', 'mfa', '2fa', 'lockout', 'authenticator', 'reset']):
            cat_name = 'Authentication'
            subcat = 'Account & Credentials'
        elif any(w in text for w in ['print', 'printer', 'spooler', 'toner', 'paper jam', 'xerox', 'hp']):
            cat_name = 'Printer'
            subcat = 'Print Spooler / Driver'
            priority = Ticket.PRIORITY_LOW if priority != Ticket.PRIORITY_CRITICAL else priority
        elif any(w in text for w in ['laptop', 'monitor', 'keyboard', 'mouse', 'dock', 'screen', 'hardware', 'usb']):
            cat_name = 'Hardware'
            subcat = 'Physical Device'
        elif any(w in text for w in ['database', 'mysql', 'postgres', 'sql', 'query', 'oracle', 'mongo']):
            cat_name = 'Database'
            subcat = 'Database Query / Connection'
        elif any(w in text for w in ['install', 'software', 'license', 'crash', 'freeze', 'zoom', 'teams', 'slack', 'excel']):
            cat_name = 'Software'
            subcat = 'Application Bug / Install'

        category = TicketCategory.query.filter_by(name=cat_name).first()
        category_id = category.id if category else None

        return category_id, subcat, priority

    @staticmethod
    def calculate_sla_deadline(priority: str) -> datetime:
        """Calculate the SLA deadline based on priority configuration."""
        policy = SLAPolicy.query.filter_by(priority=priority).first()
        hours = policy.resolution_time_hours if policy else 8
        return datetime.utcnow() + timedelta(hours=hours)

    @classmethod
    def create_ticket(cls, title: str, description: str, user_id: int, 
                      category_id: Optional[int] = None, 
                      priority: Optional[str] = None) -> Ticket:
        """Create a new ticket with automatic number generation, classification, and SLA deadline."""
        # 1. Generate sequential Ticket Number (e.g., TKT-1001)
        last_ticket = Ticket.query.order_by(Ticket.id.desc()).first()
        next_num = 1001 if not last_ticket else (last_ticket.id + 1001)
        ticket_number = f"TKT-{next_num}"

        # 2. Auto-classification if not explicitly provided
        auto_cat_id, auto_subcat, auto_priority = cls.auto_classify(title, description)
        final_category_id = category_id or auto_cat_id
        final_priority = priority or auto_priority
        final_subcategory = auto_subcat

        # 3. Calculate SLA
        deadline = cls.calculate_sla_deadline(final_priority)

        # 4. Create Ticket Record
        ticket = Ticket(
            ticket_number=ticket_number,
            title=title.strip(),
            description=description.strip(),
            category_id=final_category_id,
            subcategory=final_subcategory,
            priority=final_priority,
            status=Ticket.STATUS_NEW,
            created_by_id=user_id,
            sla_deadline=deadline
        )
        db.session.add(ticket)
        db.session.commit()

        # 5. Log initial status
        cls.record_status_change(ticket.id, None, Ticket.STATUS_NEW, user_id, "Ticket created by employee")
        AuditLog.log("TICKET_CREATED", "Ticket", ticket.id, user_id, f"Created {ticket_number}: {title}")

        return ticket

    @classmethod
    def record_status_change(cls, ticket_id: int, old_status: Optional[str], 
                             new_status: str, user_id: int, notes: Optional[str] = None) -> TicketStatusHistory:
        """Record status transition in history."""
        history = TicketStatusHistory(
            ticket_id=ticket_id,
            old_status=old_status,
            new_status=new_status,
            changed_by_id=user_id,
            notes=notes
        )
        db.session.add(history)
        db.session.commit()
        return history

    @classmethod
    def assign_ticket(cls, ticket_id: int, engineer_id: int, assigned_by_id: int) -> Ticket:
        """Assign ticket to a support engineer."""
        ticket = Ticket.query.get_or_404(ticket_id)
        engineer = User.query.get_or_404(engineer_id)

        old_status = ticket.status
        ticket.assigned_to_id = engineer.id
        if ticket.status in [Ticket.STATUS_NEW, Ticket.STATUS_CLASSIFIED]:
            ticket.status = Ticket.STATUS_ASSIGNED

        db.session.commit()

        cls.record_status_change(
            ticket.id, old_status, ticket.status, assigned_by_id, 
            f"Assigned to {engineer.username}"
        )
        AuditLog.log(
            "TICKET_ASSIGNED", "Ticket", ticket.id, assigned_by_id, 
            f"{ticket.ticket_number} assigned to {engineer.username}"
        )
        return ticket

    @classmethod
    def update_status(cls, ticket_id: int, new_status: str, user_id: int, notes: Optional[str] = None) -> Ticket:
        """Update ticket lifecycle status."""
        ticket = Ticket.query.get_or_404(ticket_id)
        old_status = ticket.status
        ticket.status = new_status
        db.session.commit()

        cls.record_status_change(ticket.id, old_status, new_status, user_id, notes)
        AuditLog.log(
            "STATUS_CHANGED", "Ticket", ticket.id, user_id, 
            f"{ticket.ticket_number} status changed from {old_status} to {new_status}"
        )
        return ticket

    @classmethod
    def escalate_ticket(cls, ticket_id: int, reason: str, escalated_by_id: int, 
                        new_assignee_id: Optional[int] = None, 
                        level: str = 'Level 2 Support') -> Ticket:
        """Escalate ticket to higher support tier."""
        ticket = Ticket.query.get_or_404(ticket_id)
        old_status = ticket.status
        prev_assignee = ticket.assigned_to_id

        ticket.status = Ticket.STATUS_ESCALATED
        if new_assignee_id:
            ticket.assigned_to_id = new_assignee_id

        escalation = TicketEscalation(
            ticket_id=ticket.id,
            previous_assignee_id=prev_assignee,
            new_assignee_id=new_assignee_id,
            escalation_level=level,
            reason=reason,
            escalated_by_id=escalated_by_id
        )
        db.session.add(escalation)
        db.session.commit()

        cls.record_status_change(
            ticket.id, old_status, Ticket.STATUS_ESCALATED, escalated_by_id, 
            f"Escalated to {level}. Reason: {reason}"
        )
        AuditLog.log(
            "TICKET_ESCALATED", "Ticket", ticket.id, escalated_by_id, 
            f"{ticket.ticket_number} escalated to {level}"
        )
        return ticket

    @classmethod
    def resolve_ticket(cls, ticket_id: int, root_cause: str, action_taken: str, 
                       resolution_summary: str, user_id: int) -> Ticket:
        """Mark ticket as RESOLVED with detailed root cause and action taken."""
        ticket = Ticket.query.get_or_404(ticket_id)
        old_status = ticket.status

        ticket.status = Ticket.STATUS_RESOLVED
        ticket.resolution_date = datetime.utcnow()
        ticket.root_cause = root_cause.strip()
        ticket.action_taken = action_taken.strip()
        ticket.resolution_summary = resolution_summary.strip()
        db.session.commit()

        cls.record_status_change(
            ticket.id, old_status, Ticket.STATUS_RESOLVED, user_id, 
            f"Resolved: {resolution_summary}"
        )
        AuditLog.log(
            "TICKET_RESOLVED", "Ticket", ticket.id, user_id, 
            f"{ticket.ticket_number} resolved by user {user_id}"
        )
        return ticket

    @classmethod
    def submit_feedback(cls, ticket_id: int, user_id: int, rating: int, 
                        comment: str, ai_useful: bool) -> TicketFeedback:
        """Save employee post-resolution feedback."""
        ticket = Ticket.query.get_or_404(ticket_id)
        
        # Check if already submitted
        existing = TicketFeedback.query.filter_by(ticket_id=ticket_id).first()
        if existing:
            existing.rating = rating
            existing.comment = comment
            existing.ai_useful = ai_useful
            db.session.commit()
            return existing

        feedback = TicketFeedback(
            ticket_id=ticket.id,
            user_id=user_id,
            rating=rating,
            comment=comment.strip() if comment else None,
            ai_useful=ai_useful
        )
        db.session.add(feedback)
        db.session.commit()
        AuditLog.log(
            "FEEDBACK_SUBMITTED", "Ticket", ticket.id, user_id, 
            f"Rating: {rating}/5, AI Useful: {ai_useful}"
        )
        return feedback

    @classmethod
    def add_comment(cls, ticket_id: int, user_id: int, comment_text: str) -> TicketComment:
        """Add a comment to the ticket thread."""
        comment = TicketComment(
            ticket_id=ticket_id,
            user_id=user_id,
            comment=comment_text.strip()
        )
        db.session.add(comment)
        db.session.commit()
        return comment

