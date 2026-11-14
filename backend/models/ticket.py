from datetime import datetime, timedelta
from backend.extensions import db


class TicketCategory(db.Model):
    """Category classification for IT tickets."""
    __tablename__ = 'ticket_categories'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.String(255), nullable=True)

    tickets = db.relationship('Ticket', back_populates='category', lazy='dynamic')

    @classmethod
    def seed_default_categories(cls):
        """Seed initial IT Helpdesk categories."""
        categories = [
            ('Network', 'Network infrastructure, Wi-Fi, switches, routers, and connectivity'),
            ('VPN', 'Virtual Private Network access, client issues, and tunnel connection errors'),
            ('Email', 'Outlook, Exchange, spam filter, and mailbox access'),
            ('Hardware', 'Laptops, desktops, monitors, docks, and physical peripherals'),
            ('Software', 'Application installations, licenses, updates, and crashes'),
            ('Server', 'Windows/Linux servers, VM access, SSH, and Active Directory'),
            ('Database', 'MySQL, PostgreSQL, Oracle, and database connection timeouts'),
            ('Printer', 'Office network printers, scanner configuration, and print spoolers'),
            ('Authentication', 'SSO, MFA, password resets, and account lockout'),
            ('Security', 'Phishing alerts, virus scans, firewall blocks, and endpoint security'),
            ('Application', 'Internal enterprise tools, ERP, CRM, and portal errors'),
            ('Other', 'General IT questions and unclassified support requests')
        ]
        for name, desc in categories:
            existing = cls.query.filter_by(name=name).first()
            if not existing:
                cat = cls(name=name, description=desc)
                db.session.add(cat)
        db.session.commit()

    def to_dict(self):
        return {'id': self.id, 'name': self.name, 'description': self.description}


class Ticket(db.Model):
    """Core IT Support Ticket model with SLA and RAG resolution tracking."""
    __tablename__ = 'tickets'

    # Priorities
    PRIORITY_LOW = 'LOW'
    PRIORITY_MEDIUM = 'MEDIUM'
    PRIORITY_HIGH = 'HIGH'
    PRIORITY_CRITICAL = 'CRITICAL'

    # Status Lifecycle
    STATUS_NEW = 'NEW'
    STATUS_CLASSIFIED = 'CLASSIFIED'
    STATUS_ASSIGNED = 'ASSIGNED'
    STATUS_IN_PROGRESS = 'IN_PROGRESS'
    STATUS_WAITING_FOR_USER = 'WAITING_FOR_USER'
    STATUS_RESOLVED = 'RESOLVED'
    STATUS_CLOSED = 'CLOSED'
    STATUS_ESCALATED = 'ESCALATED'
    STATUS_LEVEL_2_SUPPORT = 'LEVEL_2_SUPPORT'

    id = db.Column(db.Integer, primary_key=True)
    ticket_number = db.Column(db.String(30), unique=True, nullable=False, index=True)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=False)
    
    category_id = db.Column(db.Integer, db.ForeignKey('ticket_categories.id'), nullable=True)
    subcategory = db.Column(db.String(50), nullable=True)
    priority = db.Column(db.String(20), default=PRIORITY_MEDIUM, nullable=False)
    status = db.Column(db.String(30), default=STATUS_NEW, nullable=False, index=True)
    
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    assigned_to_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    
    # SLA Tracking
    sla_deadline = db.Column(db.DateTime, nullable=True)
    resolution_date = db.Column(db.DateTime, nullable=True)

    # Resolution outcome
    root_cause = db.Column(db.Text, nullable=True)
    action_taken = db.Column(db.Text, nullable=True)
    resolution_summary = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    category = db.relationship('TicketCategory', back_populates='tickets')
    creator = db.relationship('User', foreign_keys=[created_by_id], back_populates='created_tickets')
    assignee = db.relationship('User', foreign_keys=[assigned_to_id], back_populates='assigned_tickets')
    comments = db.relationship('TicketComment', back_populates='ticket', cascade='all, delete-orphan', lazy='dynamic')
    attachments = db.relationship('TicketAttachment', back_populates='ticket', cascade='all, delete-orphan', lazy='dynamic')
    status_history = db.relationship('TicketStatusHistory', back_populates='ticket', cascade='all, delete-orphan', order_by='TicketStatusHistory.created_at.asc()')
    escalations = db.relationship('TicketEscalation', back_populates='ticket', cascade='all, delete-orphan')
    ai_responses = db.relationship('AIResponse', back_populates='ticket', cascade='all, delete-orphan', order_by='AIResponse.created_at.desc()')
    feedback = db.relationship('TicketFeedback', back_populates='ticket', uselist=False, cascade='all, delete-orphan')

    @property
    def latest_ai_response(self):
        """Fetch the most recent AI suggestion."""
        return self.ai_responses[0] if self.ai_responses else None

    @property
    def ordered_comments(self):
        """Fetch comments in chronological order."""
        return self.comments.order_by(TicketComment.created_at.asc()).all()

    @property
    def is_resolved(self):
        return self.status in [self.STATUS_RESOLVED, self.STATUS_CLOSED]

    @property
    def sla_status(self):
        """Calculate real-time SLA status: WITHIN_SLA, NEAR_BREACH, or BREACHED."""
        if not self.sla_deadline:
            return 'WITHIN_SLA'
        
        now = self.resolution_date or datetime.utcnow()
        if now > self.sla_deadline:
            return 'BREACHED'
        
        # Near breach if less than 20% or 1 hour remains
        time_left = self.sla_deadline - now
        if time_left < timedelta(hours=1) and not self.is_resolved:
            return 'NEAR_BREACH'
            
        return 'WITHIN_SLA'

    @property
    def time_remaining_str(self):
        """Human-readable time until SLA deadline."""
        if not self.sla_deadline or self.is_resolved:
            return 'Completed'
        now = datetime.utcnow()
        diff = self.sla_deadline - now
        if diff.total_seconds() < 0:
            overdue = abs(diff)
            hours, remainder = divmod(int(overdue.total_seconds()), 3600)
            mins = remainder // 60
            return f"Overdue by {hours}h {mins}m"
        else:
            hours, remainder = divmod(int(diff.total_seconds()), 3600)
            mins = remainder // 60
            return f"{hours}h {mins}m remaining"

    def to_dict(self):
        return {
            'id': self.id,
            'ticket_number': self.ticket_number,
            'title': self.title,
            'description': self.description,
            'category': self.category.name if self.category else 'Unassigned',
            'subcategory': self.subcategory or '',
            'priority': self.priority,
            'status': self.status,
            'created_by': self.creator.username if self.creator else 'Unknown',
            'assigned_to': self.assignee.username if self.assignee else 'Unassigned',
            'sla_status': self.sla_status,
            'time_remaining': self.time_remaining_str,
            'sla_deadline': self.sla_deadline.strftime('%Y-%m-%d %H:%M') if self.sla_deadline else None,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M'),
            'updated_at': self.updated_at.strftime('%Y-%m-%d %H:%M') if self.updated_at else None
        }


class TicketComment(db.Model):
    """Discussion comments between employees and support engineers."""
    __tablename__ = 'ticket_comments'

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('tickets.id', ondelete='CASCADE'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    comment = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    ticket = db.relationship('Ticket', back_populates='comments')
    author = db.relationship('User', foreign_keys=[user_id])


class TicketAttachment(db.Model):
    """File attachments uploaded for a ticket."""
    __tablename__ = 'ticket_attachments'

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('tickets.id', ondelete='CASCADE'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_size = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    ticket = db.relationship('Ticket', back_populates='attachments')
    uploader = db.relationship('User', foreign_keys=[user_id])


class TicketStatusHistory(db.Model):
    """Audit log tracking every status transition."""
    __tablename__ = 'ticket_status_history'

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('tickets.id', ondelete='CASCADE'), nullable=False, index=True)
    old_status = db.Column(db.String(30), nullable=True)
    new_status = db.Column(db.String(30), nullable=False)
    changed_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    notes = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    ticket = db.relationship('Ticket', back_populates='status_history')
    changed_by = db.relationship('User', foreign_keys=[changed_by_id])


class TicketEscalation(db.Model):
    """Record of ticket escalations between support tiers."""
    __tablename__ = 'ticket_escalations'

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('tickets.id', ondelete='CASCADE'), nullable=False, index=True)
    previous_assignee_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    new_assignee_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    escalation_level = db.Column(db.String(50), default='Level 2 Support')
    reason = db.Column(db.Text, nullable=False)
    escalated_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    ticket = db.relationship('Ticket', back_populates='escalations')
    previous_assignee = db.relationship('User', foreign_keys=[previous_assignee_id])
    new_assignee = db.relationship('User', foreign_keys=[new_assignee_id])
    escalated_by = db.relationship('User', foreign_keys=[escalated_by_id])


class TicketFeedback(db.Model):
    """Employee feedback after ticket resolution."""
    __tablename__ = 'ticket_feedback'

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('tickets.id', ondelete='CASCADE'), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    rating = db.Column(db.Integer, nullable=False)  # 1 to 5
    comment = db.Column(db.Text, nullable=True)
    ai_useful = db.Column(db.Boolean, default=True)  # Was AI suggestion useful?
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    ticket = db.relationship('Ticket', back_populates='feedback')
    user = db.relationship('User', foreign_keys=[user_id])

