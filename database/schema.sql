-- =====================================================================
-- RAG-Powered IT Helpdesk and Intelligent Ticket Resolution System
-- Database Schema (MySQL / PostgreSQL / SQLite Compatible)
-- =====================================================================

-- 1. Roles Table (RBAC)
CREATE TABLE IF NOT EXISTS roles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(50) UNIQUE NOT NULL,
    description VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. Users Table
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username VARCHAR(80) UNIQUE NOT NULL,
    email VARCHAR(120) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role_id INTEGER NOT NULL,
    is_active BOOLEAN DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (role_id) REFERENCES roles (id) ON DELETE RESTRICT
);

-- 3. Ticket Categories Table
CREATE TABLE IF NOT EXISTS ticket_categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(50) UNIQUE NOT NULL,
    description VARCHAR(255)
);

-- 4. SLA Policies Table
CREATE TABLE IF NOT EXISTS sla_policies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    priority VARCHAR(20) UNIQUE NOT NULL,
    resolution_time_hours INTEGER NOT NULL DEFAULT 8,
    response_time_hours INTEGER NOT NULL DEFAULT 2,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 5. Support Tickets Table
CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_number VARCHAR(30) UNIQUE NOT NULL,
    title VARCHAR(255) NOT NULL,
    description TEXT NOT NULL,
    category_id INTEGER,
    subcategory VARCHAR(50),
    priority VARCHAR(20) NOT NULL DEFAULT 'MEDIUM',
    status VARCHAR(30) NOT NULL DEFAULT 'NEW',
    created_by_id INTEGER NOT NULL,
    assigned_to_id INTEGER,
    sla_deadline TIMESTAMP,
    resolution_date TIMESTAMP,
    root_cause TEXT,
    action_taken TEXT,
    resolution_summary TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (category_id) REFERENCES ticket_categories (id) ON DELETE SET NULL,
    FOREIGN KEY (created_by_id) REFERENCES users (id) ON DELETE CASCADE,
    FOREIGN KEY (assigned_to_id) REFERENCES users (id) ON DELETE SET NULL
);

-- 6. Ticket Discussion Comments
CREATE TABLE IF NOT EXISTS ticket_comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    comment TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (ticket_id) REFERENCES tickets (id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);

-- 7. Ticket File Attachments
CREATE TABLE IF NOT EXISTS ticket_attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    filename VARCHAR(255) NOT NULL,
    file_path VARCHAR(500) NOT NULL,
    file_size INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (ticket_id) REFERENCES tickets (id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);

-- 8. Ticket Status Lifecycle History
CREATE TABLE IF NOT EXISTS ticket_status_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER NOT NULL,
    old_status VARCHAR(30),
    new_status VARCHAR(30) NOT NULL,
    changed_by_id INTEGER,
    notes VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (ticket_id) REFERENCES tickets (id) ON DELETE CASCADE,
    FOREIGN KEY (changed_by_id) REFERENCES users (id) ON DELETE SET NULL
);

-- 9. Ticket Escalations
CREATE TABLE IF NOT EXISTS ticket_escalations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER NOT NULL,
    previous_assignee_id INTEGER,
    new_assignee_id INTEGER,
    escalation_level VARCHAR(50) DEFAULT 'Level 2 Support',
    reason TEXT NOT NULL,
    escalated_by_id INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (ticket_id) REFERENCES tickets (id) ON DELETE CASCADE,
    FOREIGN KEY (previous_assignee_id) REFERENCES users (id) ON DELETE SET NULL,
    FOREIGN KEY (new_assignee_id) REFERENCES users (id) ON DELETE SET NULL,
    FOREIGN KEY (escalated_by_id) REFERENCES users (id) ON DELETE CASCADE
);

-- 10. Post-Resolution Feedback
CREATE TABLE IF NOT EXISTS ticket_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER UNIQUE NOT NULL,
    user_id INTEGER NOT NULL,
    rating INTEGER NOT NULL, -- 1 to 5
    comment TEXT,
    ai_useful BOOLEAN DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (ticket_id) REFERENCES tickets (id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);

-- 11. Knowledge Documents Table
CREATE TABLE IF NOT EXISTS knowledge_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename VARCHAR(255) NOT NULL,
    title VARCHAR(255),
    category VARCHAR(100),
    file_path VARCHAR(500) NOT NULL,
    file_type VARCHAR(20) NOT NULL,
    file_size INTEGER DEFAULT 0,
    status VARCHAR(30) DEFAULT 'UPLOADED',
    chunk_count INTEGER DEFAULT 0,
    error_message TEXT,
    uploaded_by_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (uploaded_by_id) REFERENCES users (id) ON DELETE SET NULL
);

-- 12. Knowledge Chunks Table (Vector Ingestion Metadata)
CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    page_number INTEGER,
    section_title VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (document_id) REFERENCES knowledge_documents (id) ON DELETE CASCADE
);

-- 13. AI Resolution Recommendations (Human-in-the-Loop)
CREATE TABLE IF NOT EXISTS ai_responses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER NOT NULL,
    issue_summary TEXT NOT NULL,
    possible_causes TEXT NOT NULL, -- JSON array
    recommended_steps TEXT NOT NULL, -- JSON array
    knowledge_sources TEXT, -- JSON array
    similar_tickets TEXT, -- JSON array
    escalation_recommended BOOLEAN DEFAULT 0,
    confidence_score REAL DEFAULT 0.85,
    status VARCHAR(30) DEFAULT 'GENERATED', -- 'GENERATED', 'APPROVED', 'MODIFIED', 'REJECTED', 'ESCALATED'
    modified_notes TEXT,
    reviewed_by_id INTEGER,
    reviewed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (ticket_id) REFERENCES tickets (id) ON DELETE CASCADE,
    FOREIGN KEY (reviewed_by_id) REFERENCES users (id) ON DELETE SET NULL
);

-- 14. Audit Logs Table
CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    action VARCHAR(100) NOT NULL,
    entity_type VARCHAR(50) NOT NULL,
    entity_id VARCHAR(50),
    details TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE SET NULL
);

-- Performance Indexes
CREATE INDEX IF NOT EXISTS idx_tickets_number ON tickets (ticket_number);
CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets (status);
CREATE INDEX IF NOT EXISTS idx_tickets_priority ON tickets (priority);
CREATE INDEX IF NOT EXISTS idx_tickets_creator ON tickets (created_by_id);
CREATE INDEX IF NOT EXISTS idx_tickets_assignee ON tickets (assigned_to_id);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON knowledge_chunks (document_id);
CREATE INDEX IF NOT EXISTS idx_ai_ticket ON ai_responses (ticket_id);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_logs (action);
