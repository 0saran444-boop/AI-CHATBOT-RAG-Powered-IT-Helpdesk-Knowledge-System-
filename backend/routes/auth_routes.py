from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from backend.services.auth_service import AuthService
from backend.models.role import Role

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Handle user login."""
    if current_user.is_authenticated:
        return redirect(url_for('auth.dashboard'))

    if request.method == 'POST':
        identifier = request.form.get('identifier', '').strip()
        password = request.form.get('password', '')
        remember = bool(request.form.get('remember'))

        user, error = AuthService.authenticate_user(identifier, password)
        if error:
            flash(error, 'danger')
            return render_template('login.html', identifier=identifier), 401

        login_user(user, remember=remember)
        flash(f'Welcome back, {user.username}!', 'success')

        next_page = request.args.get('next')
        if next_page and next_page.startswith('/'):
            return redirect(next_page)
        if user.is_admin:
            return redirect(url_for('admin.dashboard'))
        return redirect(url_for('auth.dashboard'))

    return render_template('login.html')


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    """Handle user registration. Public self-registration is strictly restricted to Employee role."""
    if current_user.is_authenticated:
        if current_user.is_admin:
            return redirect(url_for('admin.dashboard'))
        return redirect(url_for('auth.dashboard'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        
        # Strictly enforce Employee role for self-registration
        role_name = Role.EMPLOYEE

        if password != confirm_password:
            flash("Passwords do not match.", 'danger')
            return render_template(
                'register.html', 
                username=username, 
                email=email
            ), 400

        user, error = AuthService.register_user(username, email, password, role_name)
        if error:
            flash(error, 'danger')
            return render_template(
                'register.html', 
                username=username, 
                email=email
            ), 400

        flash("Account created successfully as Employee! Please sign in with your credentials.", 'success')
        return redirect(url_for('auth.login'))

    return render_template('register.html')


@auth_bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    """Allow authenticated users to update their password with advance security checks."""
    if request.method == 'POST':
        current_pwd = request.form.get('current_password', '')
        new_pwd = request.form.get('new_password', '')
        confirm_pwd = request.form.get('confirm_password', '')

        if new_pwd != confirm_pwd:
            flash("New passwords do not match.", 'danger')
            return render_template('change_password.html'), 400

        success, err = AuthService.change_password(current_user.id, current_pwd, new_pwd)
        if not success:
            flash(err, 'danger')
            return render_template('change_password.html'), 400

        flash("Your password has been updated successfully!", 'success')
        return redirect(url_for('auth.dashboard'))

    return render_template('change_password.html')


@auth_bp.route('/logout')
@login_required
def logout():
    """Log out the current user."""
    logout_user()
    flash("You have been signed out successfully.", 'info')
    return redirect(url_for('auth.login'))


@auth_bp.route('/dashboard')
@login_required
def dashboard():
    """User dashboard landing page with role-based statistics."""
    from backend.models.ticket import Ticket

    if current_user.is_admin:
        return redirect(url_for('admin.dashboard'))

    if current_user.is_employee:
        open_count = Ticket.query.filter(
            Ticket.created_by_id == current_user.id,
            Ticket.status.notin_([Ticket.STATUS_RESOLVED, Ticket.STATUS_CLOSED])
        ).count()
        resolved_count = Ticket.query.filter(
            Ticket.created_by_id == current_user.id,
            Ticket.status.in_([Ticket.STATUS_RESOLVED, Ticket.STATUS_CLOSED])
        ).count()
        recent_tickets = Ticket.query.filter_by(created_by_id=current_user.id).order_by(Ticket.created_at.desc()).limit(5).all()
        return render_template(
            'dashboard.html',
            user=current_user,
            open_count=open_count,
            resolved_count=resolved_count,
            recent_tickets=recent_tickets
        )
    else:
        assigned_count = Ticket.query.filter(
            Ticket.assigned_to_id == current_user.id,
            Ticket.status.notin_([Ticket.STATUS_RESOLVED, Ticket.STATUS_CLOSED])
        ).count()
        unassigned_count = Ticket.query.filter(
            Ticket.assigned_to_id.is_(None),
            Ticket.status.notin_([Ticket.STATUS_RESOLVED, Ticket.STATUS_CLOSED])
        ).count()
        critical_count = Ticket.query.filter(
            Ticket.priority.in_([Ticket.PRIORITY_CRITICAL, Ticket.PRIORITY_HIGH]),
            Ticket.status.notin_([Ticket.STATUS_RESOLVED, Ticket.STATUS_CLOSED])
        ).count()
        active_tickets = Ticket.query.filter(Ticket.status.notin_([Ticket.STATUS_RESOLVED, Ticket.STATUS_CLOSED])).all()
        sla_alert_count = sum(1 for t in active_tickets if t.sla_status in ['NEAR_BREACH', 'BREACHED'])
        recent_tickets = Ticket.query.order_by(Ticket.created_at.desc()).limit(6).all()
        return render_template(
            'dashboard.html',
            user=current_user,
            assigned_count=assigned_count,
            unassigned_count=unassigned_count,
            critical_count=critical_count,
            sla_alert_count=sla_alert_count,
            recent_tickets=recent_tickets
        )

