from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from datetime import datetime, timedelta

from backend.extensions import db
from backend.models.user import User
from backend.models.role import Role
from backend.models.ticket import Ticket, TicketCategory, TicketComment
from backend.models.ai_response import AIResponse
from backend.models.sla import SLAPolicy
from backend.models.audit import AuditLog

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


@admin_bp.before_request
@login_required
def require_admin():
    """Ensure only administrators can access admin portal."""
    if not current_user.is_admin:
        flash("Administrative access required.", 'danger')
        return redirect(url_for('auth.dashboard'))


@admin_bp.route('', methods=['GET'])
@admin_bp.route('/', methods=['GET'])
def dashboard():
    """Main Admin Dashboard with operational metrics, SLA tracking, and AI analytics."""
    # 1. Ticket volume statistics
    total_tickets = Ticket.query.count()
    open_tickets = Ticket.query.filter(Ticket.status.notin_([Ticket.STATUS_RESOLVED, Ticket.STATUS_CLOSED])).count()
    resolved_tickets = Ticket.query.filter(Ticket.status.in_([Ticket.STATUS_RESOLVED, Ticket.STATUS_CLOSED])).count()
    critical_tickets = Ticket.query.filter_by(priority=Ticket.PRIORITY_CRITICAL).count()

    # 2. SLA Breakdown
    active_tickets = Ticket.query.filter(Ticket.status.notin_([Ticket.STATUS_RESOLVED, Ticket.STATUS_CLOSED])).all()
    sla_within = sum(1 for t in active_tickets if t.sla_status == 'WITHIN_SLA')
    sla_near_breach = sum(1 for t in active_tickets if t.sla_status == 'NEAR_BREACH')
    sla_breached = sum(1 for t in active_tickets if t.sla_status == 'BREACHED')

    # 3. AI Performance Analytics (Section 29)
    total_suggestions = AIResponse.query.count()
    accepted = AIResponse.query.filter_by(status=AIResponse.STATUS_APPROVED).count()
    modified = AIResponse.query.filter_by(status=AIResponse.STATUS_MODIFIED).count()
    rejected = AIResponse.query.filter_by(status=AIResponse.STATUS_REJECTED).count()
    acceptance_rate = round(((accepted + modified) / total_suggestions * 100), 1) if total_suggestions > 0 else 0.0

    # 4. Category breakdown
    categories = TicketCategory.query.all()
    category_stats = [
        {'name': cat.name, 'count': Ticket.query.filter_by(category_id=cat.id).count()}
        for cat in categories
    ]

    return render_template(
        'admin/dashboard.html',
        total_tickets=total_tickets,
        open_tickets=open_tickets,
        resolved_tickets=resolved_tickets,
        critical_tickets=critical_tickets,
        sla_within=sla_within,
        sla_near_breach=sla_near_breach,
        sla_breached=sla_breached,
        total_suggestions=total_suggestions,
        accepted=accepted,
        modified=modified,
        rejected=rejected,
        acceptance_rate=acceptance_rate,
        category_stats=category_stats
    )


@admin_bp.route('/users', methods=['GET', 'POST'])
def manage_users():
    """User Management: list users, update roles, toggle active status."""
    if request.method == 'POST':
        user_id = int(request.form.get('user_id'))
        role_name = request.form.get('role')
        user = User.query.get_or_404(user_id)
        role = Role.query.filter_by(name=role_name).first()
        if role:
            user.role_id = role.id
            db.session.commit()
            AuditLog.log("ROLE_CHANGED", "User", user.id, current_user.id, f"Changed {user.username} role to {role_name}")
            flash(f"Updated role for {user.username} to {role_name}.", 'success')
        return redirect(url_for('admin.manage_users'))

    users = User.query.order_by(User.created_at.desc()).all()
    roles = Role.query.all()
    return render_template('admin/users.html', users=users, roles=roles)


@admin_bp.route('/users/<int:user_id>/toggle-status', methods=['POST'])
def toggle_user_status(user_id: int):
    """Toggle user active / inactive status (ON / OFF switch)."""
    if user_id == current_user.id:
        flash("You cannot deactivate your own administrative account.", 'warning')
        return redirect(request.referrer or url_for('admin.manage_users'))

    user = User.query.get_or_404(user_id)
    user.is_active = not bool(user.is_active)
    db.session.commit()

    status_str = "ACTIVE (ON)" if user.is_active else "INACTIVE (OFF)"
    AuditLog.log("USER_STATUS_TOGGLED", "User", user.id, current_user.id, f"Toggled {user.username} status to {status_str}")
    flash(f"User '{user.username}' status changed to {status_str}.", 'success' if user.is_active else 'info')
    return redirect(request.referrer or url_for('admin.manage_users'))


@admin_bp.route('/users/<int:user_id>/delete', methods=['POST'])
def delete_user(user_id: int):
    """Delete a user account with safety checks and clean relationship cleanup."""
    if user_id == current_user.id:
        flash("You cannot delete your own administrative account.", 'warning')
        return redirect(url_for('admin.manage_users'))

    user = User.query.get_or_404(user_id)
    username = user.username

    # Reassign created tickets and comments to admin to maintain complete data integrity
    Ticket.query.filter_by(created_by_id=user.id).update({'created_by_id': current_user.id})
    Ticket.query.filter_by(assigned_to_id=user.id).update({'assigned_to_id': None})
    TicketComment.query.filter_by(user_id=user.id).update({'user_id': current_user.id})
    AuditLog.query.filter_by(user_id=user.id).update({'user_id': None})

    db.session.delete(user)
    db.session.commit()

    AuditLog.log("USER_DELETED", "User", user_id, current_user.id, f"Permanently deleted user '{username}'")
    flash(f"User '{username}' has been deleted successfully.", 'success')
    return redirect(url_for('admin.manage_users'))


@admin_bp.route('/sla', methods=['GET', 'POST'])
def manage_sla():
    """SLA Policy Configuration."""
    if request.method == 'POST':
        for priority in [Ticket.PRIORITY_LOW, Ticket.PRIORITY_MEDIUM, Ticket.PRIORITY_HIGH, Ticket.PRIORITY_CRITICAL]:
            hours = request.form.get(f'hours_{priority}')
            if hours:
                policy = SLAPolicy.query.filter_by(priority=priority).first()
                if policy:
                    policy.resolution_time_hours = int(hours)
        db.session.commit()
        AuditLog.log("SLA_UPDATED", "SLAPolicy", None, current_user.id, "Updated SLA policy resolution hours")
        flash("SLA policies updated successfully.", 'success')
        return redirect(url_for('admin.manage_sla'))

    policies = SLAPolicy.query.order_by(SLAPolicy.resolution_time_hours.asc()).all()
    return render_template('admin/sla.html', policies=policies)


@admin_bp.route('/reports', methods=['GET'])
def reports():
    """Reporting and comprehensive data analytics dashboard (Section 33)."""
    from backend.models.ticket import TicketFeedback

    # 1. Ticket volume & resolution metrics
    total_tickets = Ticket.query.count()
    open_count = Ticket.query.filter(Ticket.status.notin_([Ticket.STATUS_RESOLVED, Ticket.STATUS_CLOSED])).count()
    resolved_tickets = Ticket.query.filter(
        Ticket.status.in_([Ticket.STATUS_RESOLVED, Ticket.STATUS_CLOSED])
    ).all()
    resolved_count = len(resolved_tickets)
    resolution_rate = round((resolved_count / total_tickets * 100), 1) if total_tickets > 0 else 0.0

    # 2. MTTR & SLA compliance
    total_hours = 0.0
    within_sla_count = 0
    for t in resolved_tickets:
        if t.resolution_date:
            diff = t.resolution_date - t.created_at
            total_hours += (diff.total_seconds() / 3600.0)
            if t.sla_deadline and t.resolution_date <= t.sla_deadline:
                within_sla_count += 1
        elif t.created_at:
            within_sla_count += 1

    avg_resolution_hours = round(total_hours / resolved_count, 1) if resolved_count and total_hours > 0 else 0.0
    sla_compliance_rate = round((within_sla_count / resolved_count * 100), 1) if resolved_count > 0 else 100.0

    # Active SLA status breakdown
    active_tickets = Ticket.query.filter(Ticket.status.notin_([Ticket.STATUS_RESOLVED, Ticket.STATUS_CLOSED])).all()
    sla_within = sum(1 for t in active_tickets if t.sla_status == 'WITHIN_SLA')
    sla_near_breach = sum(1 for t in active_tickets if t.sla_status == 'NEAR_BREACH')
    sla_breached = sum(1 for t in active_tickets if t.sla_status == 'BREACHED')

    # 3. Customer Satisfaction (CSAT) analytics
    feedbacks = TicketFeedback.query.all()
    feedback_count = len(feedbacks)
    avg_csat = round(sum(f.rating for f in feedbacks) / feedback_count, 1) if feedback_count > 0 else 5.0
    ai_helpful_count = sum(1 for f in feedbacks if f.ai_useful)
    ai_helpfulness_rate = round((ai_helpful_count / feedback_count * 100), 1) if feedback_count > 0 else 100.0

    # 4. Priority breakdown
    priorities = [Ticket.PRIORITY_CRITICAL, Ticket.PRIORITY_HIGH, Ticket.PRIORITY_MEDIUM, Ticket.PRIORITY_LOW]
    priority_counts = {p: Ticket.query.filter_by(priority=p).count() for p in priorities}

    # 5. AI performance metrics
    total_ai = AIResponse.query.count()
    accepted_ai = AIResponse.query.filter_by(status=AIResponse.STATUS_APPROVED).count()
    modified_ai = AIResponse.query.filter_by(status=AIResponse.STATUS_MODIFIED).count()
    rejected_ai = AIResponse.query.filter_by(status=AIResponse.STATUS_REJECTED).count()
    escalated_ai = AIResponse.query.filter_by(status=AIResponse.STATUS_ESCALATED).count()

    acc_rate = round(accepted_ai / total_ai * 100, 1) if total_ai else 0.0
    mod_rate = round(modified_ai / total_ai * 100, 1) if total_ai else 0.0
    rej_rate = round(rejected_ai / total_ai * 100, 1) if total_ai else 0.0
    esc_rate = round(escalated_ai / total_ai * 100, 1) if total_ai else 0.0
    ai_acceptance_rate = round(((accepted_ai + modified_ai) / total_ai * 100), 1) if total_ai else 0.0

    # 6. Category breakdown
    categories = TicketCategory.query.all()
    cat_counts = [
        {'name': c.name, 'count': Ticket.query.filter_by(category_id=c.id).count()}
        for c in categories
    ]
    cat_chart_labels = [c['name'] for c in cat_counts if c['count'] > 0]
    cat_chart_data = [c['count'] for c in cat_counts if c['count'] > 0]

    # 7. Time-series Daily Trend (Last 7 Days)
    today = datetime.utcnow().date()
    trend_labels = []
    trend_created = []
    trend_resolved = []
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        trend_labels.append(day.strftime('%b %d'))
        day_start = datetime.combine(day, datetime.min.time())
        day_end = datetime.combine(day, datetime.max.time())
        
        c_count = Ticket.query.filter(Ticket.created_at >= day_start, Ticket.created_at <= day_end).count()
        r_count = Ticket.query.filter(
            Ticket.resolution_date >= day_start, 
            Ticket.resolution_date <= day_end
        ).count()
        trend_created.append(c_count)
        trend_resolved.append(r_count)

    # 8. Support Engineer Productivity & Workload
    engineers = User.query.join(Role).filter(Role.name.in_([Role.ADMIN, Role.SUPPORT_AGENT])).all()
    engineer_stats = []
    for eng in engineers:
        assigned = Ticket.query.filter_by(assigned_to_id=eng.id).count()
        resolved = Ticket.query.filter(
            Ticket.assigned_to_id == eng.id,
            Ticket.status.in_([Ticket.STATUS_RESOLVED, Ticket.STATUS_CLOSED])
        ).count()
        rate = round((resolved / assigned * 100), 1) if assigned > 0 else 0.0
        engineer_stats.append({
            'username': eng.username,
            'role': eng.role.name,
            'assigned': assigned,
            'resolved': resolved,
            'rate': rate
        })

    return render_template(
        'admin/reports.html',
        total_tickets=total_tickets,
        open_count=open_count,
        resolved_count=resolved_count,
        resolution_rate=resolution_rate,
        avg_resolution_hours=avg_resolution_hours,
        sla_compliance_rate=sla_compliance_rate,
        sla_within=sla_within,
        sla_near_breach=sla_near_breach,
        sla_breached=sla_breached,
        avg_csat=avg_csat,
        feedback_count=feedback_count,
        ai_helpfulness_rate=ai_helpfulness_rate,
        priority_counts=priority_counts,
        cat_counts=cat_counts,
        cat_chart_labels=cat_chart_labels,
        cat_chart_data=cat_chart_data,
        total_ai=total_ai,
        accepted_ai=accepted_ai,
        modified_ai=modified_ai,
        rejected_ai=rejected_ai,
        escalated_ai=escalated_ai,
        acc_rate=acc_rate,
        mod_rate=mod_rate,
        rej_rate=rej_rate,
        esc_rate=esc_rate,
        ai_acceptance_rate=ai_acceptance_rate,
        trend_labels=trend_labels,
        trend_created=trend_created,
        trend_resolved=trend_resolved,
        engineer_stats=engineer_stats
    )


@admin_bp.route('/reports/export', methods=['GET'])
def export_csv():
    """Export operational ticket data to CSV for Business Intelligence / Data Science analysis."""
    import csv
    import io
    from flask import Response
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'Ticket ID', 'Title', 'Category', 'Priority', 'Status',
        'Created By', 'Assigned To', 'Created At', 'Resolution Date',
        'Resolution Hours', 'SLA Status', 'CSAT Rating'
    ])
    
    tickets = Ticket.query.order_by(Ticket.created_at.desc()).all()
    for t in tickets:
        res_hours = ""
        if t.resolution_date:
            diff = t.resolution_date - t.created_at
            res_hours = f"{diff.total_seconds() / 3600.0:.1f}"
            
        rating = t.feedback.rating if t.feedback else "N/A"
        writer.writerow([
            t.ticket_number,
            t.title,
            t.category.name if t.category else "Uncategorized",
            t.priority,
            t.status,
            t.creator.username if t.creator else "Unknown",
            t.assignee.username if t.assignee else "Unassigned",
            t.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            t.resolution_date.strftime('%Y-%m-%d %H:%M:%S') if t.resolution_date else "",
            res_hours,
            t.sla_status,
            rating
        ])
        
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=it_helpdesk_analytics_report.csv"}
    )


@admin_bp.route('/audit-logs', methods=['GET'])
def audit_logs():
    """Audit Logging Viewer with automatic 30-day retention and date-wise filtering."""
    # 1. Automatic 1-Month Cleanup: Automatically delete audit logs older than 30 days
    one_month_ago = datetime.utcnow() - timedelta(days=30)
    purged_count = AuditLog.query.filter(AuditLog.timestamp < one_month_ago).delete(synchronize_session=False)
    if purged_count > 0:
        db.session.commit()

    # 2. Filters & date-wise queries
    filter_type = request.args.get('filter', 'all')
    date_str = request.args.get('date', '').strip()

    today = datetime.utcnow().date()
    today_start = datetime.combine(today, datetime.min.time())
    today_end = datetime.combine(today, datetime.max.time())

    login_actions = ['LOGIN_SUCCESS', 'LOGIN_FAILED', 'LOGIN_BLOCKED_LOCKED', 'ACCOUNT_LOCKED']

    query = AuditLog.query

    if filter_type == 'today_logins':
        query = query.filter(
            AuditLog.action.in_(login_actions),
            AuditLog.timestamp >= today_start,
            AuditLog.timestamp <= today_end
        )
    elif filter_type == 'all_logins':
        query = query.filter(AuditLog.action.in_(login_actions))
    
    if date_str:
        try:
            target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            d_start = datetime.combine(target_date, datetime.min.time())
            d_end = datetime.combine(target_date, datetime.max.time())
            query = query.filter(AuditLog.timestamp >= d_start, AuditLog.timestamp <= d_end)
        except ValueError:
            pass

    logs = query.order_by(AuditLog.timestamp.desc()).limit(200).all()

    # 3. Metrics for stats cards
    today_logins_count = AuditLog.query.filter(
        AuditLog.action == 'LOGIN_SUCCESS',
        AuditLog.timestamp >= today_start,
        AuditLog.timestamp <= today_end
    ).count()

    today_failed_count = AuditLog.query.filter(
        AuditLog.action.in_(['LOGIN_FAILED', 'LOGIN_BLOCKED_LOCKED', 'ACCOUNT_LOCKED']),
        AuditLog.timestamp >= today_start,
        AuditLog.timestamp <= today_end
    ).count()

    total_logs_count = AuditLog.query.count()

    return render_template(
        'admin/audit_logs.html',
        logs=logs,
        filter_type=filter_type,
        selected_date=date_str,
        today_logins_count=today_logins_count,
        today_failed_count=today_failed_count,
        total_logs_count=total_logs_count,
        today_date_str=today.strftime('%b %d, %Y'),
        purged_auto_count=purged_count
    )


@admin_bp.route('/audit-logs/<int:log_id>/delete', methods=['POST'])
def delete_audit_log(log_id: int):
    """Delete a single audit log entry."""
    log = AuditLog.query.get_or_404(log_id)
    db.session.delete(log)
    db.session.commit()
    flash(f"Audit log #{log_id} deleted successfully.", 'info')
    return redirect(request.referrer or url_for('admin.audit_logs'))


@admin_bp.route('/audit-logs/purge', methods=['POST'])
def purge_audit_logs():
    """Manual purge options: older than 30 days, today's logs, or all logs."""
    purge_mode = request.form.get('purge_mode', 'older_than_30_days')
    today = datetime.utcnow().date()
    today_start = datetime.combine(today, datetime.min.time())
    today_end = datetime.combine(today, datetime.max.time())

    if purge_mode == 'older_than_30_days':
        cutoff = datetime.utcnow() - timedelta(days=30)
        deleted = AuditLog.query.filter(AuditLog.timestamp < cutoff).delete(synchronize_session=False)
        msg = f"Purged {deleted} audit logs older than 30 days."
    elif purge_mode == 'today_logins':
        login_actions = ['LOGIN_SUCCESS', 'LOGIN_FAILED', 'LOGIN_BLOCKED_LOCKED', 'ACCOUNT_LOCKED']
        deleted = AuditLog.query.filter(
            AuditLog.action.in_(login_actions),
            AuditLog.timestamp >= today_start,
            AuditLog.timestamp <= today_end
        ).delete(synchronize_session=False)
        msg = f"Deleted {deleted} login logs from today."
    elif purge_mode == 'all':
        deleted = AuditLog.query.delete()
        msg = f"Cleared all {deleted} audit logs."
    else:
        deleted = 0
        msg = "No logs deleted."

    db.session.commit()
    flash(msg, 'success')
    return redirect(url_for('admin.audit_logs'))

