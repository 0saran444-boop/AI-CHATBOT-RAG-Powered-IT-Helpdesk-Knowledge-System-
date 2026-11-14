from backend.routes.auth_routes import auth_bp
from backend.routes.ticket_routes import ticket_bp
from backend.routes.knowledge_routes import knowledge_bp
from backend.routes.admin_routes import admin_bp
from backend.routes.api_routes import api_bp

__all__ = ['auth_bp', 'ticket_bp', 'knowledge_bp', 'admin_bp', 'api_bp']
