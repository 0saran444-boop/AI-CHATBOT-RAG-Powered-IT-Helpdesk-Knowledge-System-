import os
import sys
from pathlib import Path

# Ensure project root is in Python sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from flask import Flask, redirect, url_for
from flask_login import current_user
from backend.config import Config
from backend.extensions import db, login_manager
from backend.models.user import User
from backend.models.role import Role
from backend.models.ticket import TicketCategory
from backend.models.sla import SLAPolicy
from backend.models.knowledge import KnowledgeDocument
from backend.services.auth_service import AuthService
from backend.services.rag_service import RAGService

# Import blueprints
from backend.routes.auth_routes import auth_bp
from backend.routes.ticket_routes import ticket_bp
from backend.routes.knowledge_routes import knowledge_bp
from backend.routes.admin_routes import admin_bp
from backend.routes.api_routes import api_bp
from backend.routes.chat_routes import chat_bp


def create_app(config_class=Config):
    """Application factory for IT Helpdesk RAG."""
    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(__file__), 'templates'),
        static_folder=os.path.join(os.path.dirname(__file__), 'static')
    )
    
    # Load configuration
    app.config.from_object(config_class)

    # Ensure required directories exist
    Config.DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)
    Config.VECTORSTORE_DIR.mkdir(parents=True, exist_ok=True)
    Config.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

    # Initialize extensions
    db.init_app(app)
    login_manager.init_app(app)

    # Configure user loader for Flask-Login
    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    # Register blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(ticket_bp)
    app.register_blueprint(knowledge_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(chat_bp)

    # Inject models into template context
    @app.context_processor
    def inject_models():
        from backend.models.ticket import Ticket, TicketComment, TicketCategory, TicketAttachment
        return dict(
            Ticket=Ticket,
            TicketComment=TicketComment,
            TicketCategory=TicketCategory,
            TicketAttachment=TicketAttachment,
            Role=Role
        )

    # Root route redirect
    @app.route('/')
    def index():
        if current_user.is_authenticated:
            if current_user.is_admin:
                return redirect(url_for('admin.dashboard'))
            return redirect(url_for('auth.dashboard'))
        return redirect(url_for('auth.login'))

    # Initialize database tables and seed baseline data
    with app.app_context():
        db.create_all()
        AuthService.seed_default_roles()
        AuthService.seed_default_users()
        TicketCategory.seed_default_categories()
        SLAPolicy.seed_default_policies()

        # Auto-index initial documents if present in documents/ directory
        for sample_file in Config.DOCUMENTS_DIR.glob('*.*'):
            if sample_file.suffix.lower() in ['.pdf', '.docx', '.txt', '.md'] and not sample_file.name.startswith('.'):
                existing = KnowledgeDocument.query.filter_by(filename=sample_file.name).first()
                if not existing:
                    doc = KnowledgeDocument(
                        filename=sample_file.name,
                        file_path=str(sample_file),
                        file_type=sample_file.suffix.lstrip('.').upper(),
                        file_size=sample_file.stat().st_size,
                        status=KnowledgeDocument.STATUS_UPLOADED
                    )
                    db.session.add(doc)
                    db.session.commit()
                    try:
                        RAGService.ingest_document(doc.id)
                    except Exception as e:
                        print(f"[RAG] Startup indexing error for {sample_file.name}: {e}")

    return app


app = create_app()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='127.0.0.1', port=port, debug=True)
