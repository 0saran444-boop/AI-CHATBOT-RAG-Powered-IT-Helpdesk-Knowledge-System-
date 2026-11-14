from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager

# SQLAlchemy database instance
db = SQLAlchemy()

# Flask-Login manager instance
login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message = 'Please log in to access this page.'
login_manager.login_message_category = 'warning'

