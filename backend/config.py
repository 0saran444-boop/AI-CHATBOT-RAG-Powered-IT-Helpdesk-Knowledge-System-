import os
from pathlib import Path
from dotenv import load_dotenv

# Base directory is the project root (one level above backend/)
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from .env
dotenv_path = BASE_DIR / '.env'
if dotenv_path.exists():
    load_dotenv(dotenv_path)


class Config:
    """Base application configuration."""
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-me-in-production')
    
    # Database configuration
    raw_db_url = os.environ.get('DATABASE_URL')
    db_dir = BASE_DIR / 'database'
    db_dir.mkdir(parents=True, exist_ok=True)

    if not raw_db_url or 'database/helpdesk.db' in raw_db_url:
        db_file = (db_dir / 'helpdesk.db').resolve()
        posix_path = db_file.as_posix()
        database_url = f"sqlite:///{posix_path}"
    elif raw_db_url.startswith("postgres://"):
        # Fix legacy Heroku postgres:// prefix for SQLAlchemy
        database_url = raw_db_url.replace("postgres://", "postgresql://", 1)
    else:
        database_url = raw_db_url
        
    SQLALCHEMY_DATABASE_URI = database_url
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Storage paths
    DOCUMENTS_DIR = BASE_DIR / os.environ.get('DOCUMENTS_PATH', 'documents')
    VECTORSTORE_DIR = BASE_DIR / os.environ.get('VECTORSTORE_PATH', 'vectorstore')
    UPLOADS_DIR = BASE_DIR / os.environ.get('UPLOADS_PATH', 'uploads')
    
    # Session configuration
    SESSION_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_DURATION = 60 * 60 * 24 * 7  # 7 days

