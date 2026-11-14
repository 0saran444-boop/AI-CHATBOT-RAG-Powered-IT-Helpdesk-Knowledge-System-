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
    chunk_count = db.Column(db.Integer, default=0)
    error_message = db.Column(db.Text, nullable=True)
    uploaded_by_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    uploader = db.relationship('User', foreign_keys=[uploaded_by_id])
    chunks = db.relationship('KnowledgeChunk', back_populates='document', cascade='all, delete-orphan', lazy='dynamic')

    @property
    def display_title(self) -> str:
        """Returns the document heading/title if set, otherwise falls back to a cleaned filename."""
        if self.title and self.title.strip():
            return self.title.strip()
        base = self.filename.rsplit('.', 1)[0]
        return base.replace('_', ' ').replace('-', ' ').title()

    def to_dict(self):
        return {
            'id': self.id,
            'title': self.display_title,
            'filename': self.filename,
            'category': self.category or 'General IT',
            'file_type': self.file_type,
            'file_size': self.file_size,
            'status': self.status,
            'chunk_count': self.chunk_count,
            'uploaded_by': self.uploader.username if self.uploader else 'Admin',
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M'),
            'updated_at': self.updated_at.strftime('%Y-%m-%d %H:%M') if self.updated_at else None
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

