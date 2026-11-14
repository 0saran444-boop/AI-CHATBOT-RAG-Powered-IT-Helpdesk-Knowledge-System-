from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from backend.extensions import db
from backend.models.role import Role


class User(UserMixin, db.Model):
    """User model representing application users with role-based permissions."""
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role_id = db.Column(db.Integer, db.ForeignKey('roles.id'), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    
    # Advanced Security & Account Lockout Tracking
    failed_login_attempts = db.Column(db.Integer, default=0)
    locked_until = db.Column(db.DateTime, nullable=True)
    last_login_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship to Role
    role = db.relationship('Role', back_populates='users')

    # Relationships to Tickets
    created_tickets = db.relationship('Ticket', foreign_keys='Ticket.created_by_id', back_populates='creator', lazy='dynamic')
    assigned_tickets = db.relationship('Ticket', foreign_keys='Ticket.assigned_to_id', back_populates='assignee', lazy='dynamic')

    @property
    def tickets(self):
        """Alias for created tickets."""
        return self.created_tickets

    def set_password(self, password: str) -> None:
        """Hash and store the user password using OWASP-recommended scrypt cryptographic hashing."""
        self.password_hash = generate_password_hash(password, method='scrypt')

    def check_password(self, password: str) -> bool:
        """Verify the password hash against the given plain text password using constant-time comparison."""
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    @property
    def is_locked(self) -> bool:
        """Check if account is temporarily locked due to brute-force attempts."""
        if self.locked_until and self.locked_until > datetime.utcnow():
            return True
        return False

    @property
    def lockout_time_remaining_str(self) -> str:
        """Formatted remaining lockout duration."""
        if not self.is_locked:
            return ""
        diff = self.locked_until - datetime.utcnow()
        mins, secs = divmod(int(diff.total_seconds()), 60)
        return f"{mins}m {secs}s"

    @property
    def is_admin(self) -> bool:
        """Check if user has Admin privileges."""
        return bool(self.role and self.role.name == Role.ADMIN)

    @property
    def is_agent(self) -> bool:
        """Check if user is a Support Agent or Admin."""
        return bool(self.role and self.role.name in [Role.ADMIN, Role.SUPPORT_AGENT])

    @property
    def is_employee(self) -> bool:
        """Check if user is an Employee."""
        return bool(self.role and self.role.name == Role.EMPLOYEE)

    def to_dict(self) -> dict:
        """Serialize user to dictionary."""
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'role': self.role.name if self.role else None,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

    def __repr__(self):
        return f"<User {self.username} (Role: {self.role.name if self.role else 'None'})>"

