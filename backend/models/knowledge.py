from datetime import datetime
from backend.extensions import db


class KnowledgeDocument(db.Model):
    """Knowledge base document uploaded for RAG processing."""
    __tablename__ = 'knowledge_documents'

    # Document Statuses
    STATUS_UPLOADED = 'UPLOADED'
    STATUS_PROCESSING = 'PROCESSING'
    STATUS_PROCESSED = 'PROCESSED'
    STATUS_FAILED = 'FAILED'
    STATUS_INACTIVE = 'INACTIVE'

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    title = db.Column(db.String(255), nullable=True)
    category = db.Column(db.String(100), nullable=True)
    file_path = db.Column(db.String(500), nullable=False)
    file_type = db.Column(db.String(20), nullable=False)  # PDF, DOCX, TXT, MD
    file_size = db.Column(db.Integer, default=0)
    status = db.Column(db.String(30), default=STATUS_UPLOADED, index=True)
    version = db.Column(db.String(20), default='v1.0')
    change_summary = db.Column(db.String(255), default='Initial release')
    chunk_count = db.Column(db.Integer, default=0)
    error_message = db.Column(db.Text, nullable=True)
    uploaded_by_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    uploader = db.relationship('User', foreign_keys=[uploaded_by_id])
    chunks = db.relationship('KnowledgeChunk', back_populates='document', cascade='all, delete-orphan', lazy='dynamic')
    versions = db.relationship('KnowledgeDocumentVersion', back_populates='document', cascade='all, delete-orphan', order_by='desc(KnowledgeDocumentVersion.id)')

    @property
    def display_title(self) -> str:
        """Returns the document heading/title if set, otherwise falls back to a cleaned filename."""
        if self.title and self.title.strip():
            return self.title.strip()
        base = self.filename.rsplit('.', 1)[0]
        return base.replace('_', ' ').replace('-', ' ').title()

    @property
    def current_version(self) -> str:
        """Returns version string e.g. 'v1.0' or 'v1.1'."""
        return self.version or 'v1.0'

    def to_dict(self):
        return {
            'id': self.id,
            'title': self.display_title,
            'filename': self.filename,
            'category': self.category or 'General IT',
            'version': self.current_version,
            'change_summary': self.change_summary or 'Initial release',
            'file_type': self.file_type,
            'file_size': self.file_size,
            'status': self.status,
            'chunk_count': self.chunk_count,
            'uploaded_by': self.uploader.username if self.uploader else 'Admin',
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M'),
            'updated_at': self.updated_at.strftime('%Y-%m-%d %H:%M') if self.updated_at else None
        }


class KnowledgeDocumentVersion(db.Model):
    """Tracks revision history and version control for knowledge base documents."""
    __tablename__ = 'knowledge_document_versions'

    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.Integer, db.ForeignKey('knowledge_documents.id', ondelete='CASCADE'), nullable=False, index=True)
    version_number = db.Column(db.String(20), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_size = db.Column(db.Integer, default=0)
    chunk_count = db.Column(db.Integer, default=0)
    change_summary = db.Column(db.String(255), nullable=True)
    uploaded_by_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    document = db.relationship('KnowledgeDocument', back_populates='versions')
    uploader = db.relationship('User', foreign_keys=[uploaded_by_id])

    def to_dict(self):
        return {
            'id': self.id,
            'document_id': self.document_id,
            'version_number': self.version_number,
            'filename': self.filename,
            'file_size': f"{round(self.file_size / 1024, 1)} KB",
            'chunk_count': self.chunk_count,
            'change_summary': self.change_summary or 'Revision update',
            'uploaded_by': self.uploader.username if self.uploader else 'Admin',
            'created_at': self.created_at.strftime('%b %d, %Y %H:%M')
        }


class KnowledgeChunk(db.Model):
    """Text chunks extracted from knowledge documents with metadata for RAG retrieval."""
    __tablename__ = 'knowledge_chunks'

    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.Integer, db.ForeignKey('knowledge_documents.id', ondelete='CASCADE'), nullable=False, index=True)
    chunk_index = db.Column(db.Integer, nullable=False)
    content = db.Column(db.Text, nullable=False)
    page_number = db.Column(db.Integer, nullable=True)
    section_title = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    document = db.relationship('KnowledgeDocument', back_populates='chunks')

    def to_dict(self):
        return {
            'id': self.id,
            'document_id': self.document_id,
            'document_name': self.document.filename if self.document else '',
            'chunk_index': self.chunk_index,
            'content': self.content,
            'page_number': self.page_number,
            'section_title': self.section_title
        }

