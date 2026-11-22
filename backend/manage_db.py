import sys
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

DB_PATH = BASE_DIR / 'database' / 'helpdesk.db'
BACKUP_DIR = BASE_DIR / 'database' / 'backups'


def backup_database():
    """Create a timestamped backup copy of helpdesk.db."""
    if not DB_PATH.exists():
        print(f"[!] Database file not found at {DB_PATH}")
        return

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_file = BACKUP_DIR / f"helpdesk_backup_{timestamp}.db"

    shutil.copy2(DB_PATH, backup_file)
    print(f"[✓] Database successfully backed up to:")
    print(f"    {backup_file}")


def export_sql_dump():
    """Export complete database into a readable SQL dump file."""
    if not DB_PATH.exists():
        print(f"[!] Database file not found at {DB_PATH}")
        return

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    dump_file = BACKUP_DIR / f"helpdesk_dump_{timestamp}.sql"

    conn = sqlite3.connect(DB_PATH)
    with open(dump_file, 'w', encoding='utf-8') as f:
        for line in conn.iterdump():
            f.write(f"{line}\n")
    conn.close()

    print(f"[✓] Database exported as SQL dump to:")
    print(f"    {dump_file}")


def init_database():
    """Initialize or update tables and seed data using app context."""
    from backend.app import app, db
    from backend.services.auth_service import AuthService
    from backend.models.ticket import TicketCategory
    from backend.models.sla import SLAPolicy

    with app.app_context():
        db.create_all()
        AuthService.seed_default_roles()
        AuthService.seed_default_users()
        TicketCategory.seed_default_categories()
        SLAPolicy.seed_default_policies()
        print("[✓] Database initialized with all tables, default roles, SLA policies, and default accounts.")


if __name__ == '__main__':
    command = sys.argv[1].lower() if len(sys.argv) > 1 else 'backup'

    if command == 'backup':
        backup_database()
    elif command in ['export', 'export-sql', 'dump']:
        export_sql_dump()
    elif command in ['init', 'reset']:
        init_database()
    else:
        print("Usage:")
        print("  python backend/manage_db.py backup     # Create timestamped .db backup")
        print("  python backend/manage_db.py export-sql # Export database as .sql dump")
        print("  python backend/manage_db.py init       # Recreate/seed baseline tables")

