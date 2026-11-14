from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, jsonify, send_file
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from pathlib import Path

from backend.extensions import db
from backend.models.knowledge import KnowledgeDocument, KnowledgeChunk, KnowledgeDocumentVersion
from backend.services.rag_service import RAGService, VectorStoreManager
from backend.models.audit import AuditLog

knowledge_bp = Blueprint('knowledge', __name__, url_prefix='/knowledge')

ALLOWED_EXTENSIONS = {'pdf', 'docx', 'txt', 'md'}


def suggest_next_version(curr: str) -> str:
    """Helper to suggest next version number e.g. v1.0 -> v1.1."""
    if not curr:
        return 'v1.1'
    curr_clean = curr.lstrip('v').split()[0]
    try:
        parts = curr_clean.split('.')
        major = int(parts[0])
        minor = int(parts[1]) if len(parts) > 1 else 0
        return f"v{major}.{minor + 1}"
    except Exception:
        return 'v1.1'


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@knowledge_bp.route('', methods=['GET'])
@knowledge_bp.route('/', methods=['GET'])
@login_required
def index():
    """List all knowledge base documents and indexing status."""
    documents = KnowledgeDocument.query.order_by(KnowledgeDocument.created_at.desc()).all()
    total_chunks = KnowledgeChunk.query.count()
    return render_template(
        'knowledge/knowledge_list.html',
        documents=documents,
        total_chunks=total_chunks
    )


@knowledge_bp.route('/<int:doc_id>', methods=['GET'])
@login_required
def document_detail(doc_id: int):
    """View full document breakdown with all section headers, content, and metadata."""
    doc = KnowledgeDocument.query.get_or_404(doc_id)
    chunks = KnowledgeChunk.query.filter_by(document_id=doc.id).order_by(KnowledgeChunk.chunk_index.asc()).all()

    # Group chunks by section header
    sections = []
    seen = {}
    for c in chunks:
        header = c.section_title or f"Section {c.chunk_index + 1}"
        if header not in seen:
            item = {
                'header': header,
                'page': c.page_number or 1,
                'chunks': [c]
            }
            seen[header] = item
            sections.append(item)
        else:
            seen[header]['chunks'].append(c)

    return render_template(
        'knowledge/document_detail.html',
        doc=doc,
        sections=sections,
        total_chunks=len(chunks)
    )


def _apply_document_update(doc, file_path, filename, file_type, heading, category, change_summary, version_number=None):
    """Applies new file changes to an existing document, archives old revision, and re-indexes FAISS."""
    if not version_number:
        version_number = suggest_next_version(doc.version)

    doc.filename = filename
    doc.file_path = str(file_path)
    doc.file_type = file_type
    doc.file_size = file_path.stat().st_size
    doc.title = heading
    doc.category = category
    doc.version = version_number
    doc.change_summary = change_summary
    doc.updated_at = datetime.utcnow()

    # Record new version in revision history
    ver = KnowledgeDocumentVersion(
        document_id=doc.id,
        version_number=version_number,
        filename=filename,
        file_path=str(file_path),
        file_size=doc.file_size,
        change_summary=change_summary,
        uploaded_by_id=current_user.id
    )
    db.session.add(ver)
    db.session.commit()

    # Re-extract chunks and re-index vector store
    success, error = RAGService.ingest_document(doc.id)
    ver.chunk_count = doc.chunk_count
    db.session.commit()

    AuditLog.log("DOC_VERSION_UPDATED", "KnowledgeDocument", doc.id, current_user.id, f"Updated '{doc.display_title}' to {version_number} ({change_summary})")
    flash(f"Document '{doc.display_title}' updated to {version_number} with new changes! Chunks re-indexed ({doc.chunk_count} chunks).", 'success')
    return redirect(url_for('knowledge.index'))


@knowledge_bp.route('/upload', methods=['POST'])
@login_required
def upload():
    """Upload a new internal IT SOP / troubleshooting document or update if same document exists."""
    if current_user.is_employee:
        flash("Only IT Support Managers and Administrators can upload knowledge documents.", 'danger')
        return redirect(url_for('knowledge.index'))

    file = request.files.get('document')
    if not file or file.filename == '':
        flash("No file selected for upload.", 'danger')
        return redirect(url_for('knowledge.index'))

    if not allowed_file(file.filename):
        flash("Allowed file types are: PDF, DOCX, TXT, MD.", 'danger')
        return redirect(url_for('knowledge.index'))

    heading = request.form.get('title', '').strip()
    category = request.form.get('category', '').strip() or 'General IT SOP'
    change_summary = request.form.get('change_summary', '').strip() or 'Initial document upload'

    filename = secure_filename(file.filename)
    # If heading wasn't provided, format nicely from filename
    if not heading:
        base_name = filename.rsplit('.', 1)[0]
        heading = base_name.replace('_', ' ').replace('-', ' ').title()

    docs_dir = current_app.config['DOCUMENTS_DIR']
    docs_dir.mkdir(parents=True, exist_ok=True)
    save_path = docs_dir / filename

    file.save(str(save_path))
    file_type = filename.rsplit('.', 1)[1].upper()

    # Check if this document already exists -> Update the same file with new changes!
    existing_doc = KnowledgeDocument.query.filter(
        db.or_(
            KnowledgeDocument.filename == filename,
            KnowledgeDocument.title == heading
        )
    ).first()

    if existing_doc:
        return _apply_document_update(
            existing_doc,
            file_path=save_path,
            filename=filename,
            file_type=file_type,
            heading=heading or existing_doc.title,
            category=category or existing_doc.category,
            change_summary=change_summary or 'Updated document with new changes'
        )

    # Brand new document
    doc = KnowledgeDocument(
        filename=filename,
        title=heading,
        category=category,
        file_path=str(save_path),
        file_type=file_type,
        file_size=save_path.stat().st_size,
        status=KnowledgeDocument.STATUS_UPLOADED,
        version='v1.0',
        change_summary=change_summary,
        uploaded_by_id=current_user.id
    )
    db.session.add(doc)
    db.session.commit()

    # Record initial v1.0 version
    init_ver = KnowledgeDocumentVersion(
        document_id=doc.id,
        version_number='v1.0',
        filename=filename,
        file_path=str(save_path),
        file_size=doc.file_size,
        change_summary=change_summary,
        uploaded_by_id=current_user.id
    )
    db.session.add(init_ver)
    db.session.commit()

    AuditLog.log("DOC_UPLOADED", "KnowledgeDocument", doc.id, current_user.id, f"Uploaded '{heading}' v1.0 ({filename})")

    # Automatically trigger ingestion pipeline
    success, error = RAGService.ingest_document(doc.id)
    init_ver.chunk_count = doc.chunk_count
    db.session.commit()

    if success:
        flash(f"Document '{heading}' (v1.0) uploaded and indexed successfully into vector store ({doc.chunk_count} chunks)!", 'success')
    else:
        flash(f"Document uploaded, but ingestion reported: {error}", 'warning')

    return redirect(url_for('knowledge.index'))


@knowledge_bp.route('/<int:doc_id>/update_file', methods=['POST'])
@login_required
def update_file(doc_id: int):
    """Upload revised file for an existing document with new changes and revision tracking."""
    if current_user.is_employee:
        flash("Only IT Support Managers and Administrators can update knowledge documents.", 'danger')
        return redirect(url_for('knowledge.index'))

    doc = KnowledgeDocument.query.get_or_404(doc_id)
    file = request.files.get('document')
    if not file or file.filename == '':
        flash("Please select a revised file to upload.", 'danger')
        return redirect(url_for('knowledge.index'))

    if not allowed_file(file.filename):
        flash("Allowed file types are: PDF, DOCX, TXT, MD.", 'danger')
        return redirect(url_for('knowledge.index'))

    change_summary = request.form.get('change_summary', '').strip() or 'Updated file with new changes'
    custom_ver = request.form.get('version', '').strip()
    new_version = custom_ver if custom_ver else suggest_next_version(doc.version)

    filename = secure_filename(file.filename)
    docs_dir = current_app.config['DOCUMENTS_DIR']
    docs_dir.mkdir(parents=True, exist_ok=True)
    save_path = docs_dir / filename
    file.save(str(save_path))
    file_type = filename.rsplit('.', 1)[1].upper()

    return _apply_document_update(
        doc,
        file_path=save_path,
        filename=filename,
        file_type=file_type,
        heading=doc.title,
        category=doc.category,
        change_summary=change_summary,
        version_number=new_version
    )


@knowledge_bp.route('/<int:doc_id>/versions', methods=['GET'])
@login_required
def get_versions(doc_id: int):
    """Return revision history of a document."""
    doc = KnowledgeDocument.query.get_or_404(doc_id)
    versions = KnowledgeDocumentVersion.query.filter_by(document_id=doc.id).order_by(KnowledgeDocumentVersion.id.desc()).all()
    return jsonify({
        'document_id': doc.id,
        'title': doc.display_title,
        'current_version': doc.current_version,
        'versions': [v.to_dict() for v in versions]
    })


@knowledge_bp.route('/<int:doc_id>/rollback/<int:version_id>', methods=['POST'])
@login_required
def rollback_version(doc_id: int, version_id: int):
    """Rollback document to a previous revision."""
    if current_user.is_employee:
        flash("Unauthorized.", 'danger')
        return redirect(url_for('knowledge.index'))

    doc = KnowledgeDocument.query.get_or_404(doc_id)
    target_ver = KnowledgeDocumentVersion.query.get_or_404(version_id)
    if target_ver.document_id != doc.id:
        flash("Invalid version for this document.", 'danger')
        return redirect(url_for('knowledge.index'))

    new_version_num = f"{target_ver.version_number}-r"
    change_summary = f"Rolled back to {target_ver.version_number} ({target_ver.filename})"

    doc.filename = target_ver.filename
    doc.file_path = target_ver.file_path
    doc.file_size = target_ver.file_size
    doc.version = new_version_num
    doc.change_summary = change_summary
    doc.updated_at = datetime.utcnow()

    # Record rollback as a new revision
    rollback_rec = KnowledgeDocumentVersion(
        document_id=doc.id,
        version_number=new_version_num,
        filename=target_ver.filename,
        file_path=target_ver.file_path,
        file_size=target_ver.file_size,
        change_summary=change_summary,
        uploaded_by_id=current_user.id
    )
    db.session.add(rollback_rec)
    db.session.commit()

    # Re-ingest restored file
    RAGService.ingest_document(doc.id)
    rollback_rec.chunk_count = doc.chunk_count
    db.session.commit()

    AuditLog.log("DOC_ROLLBACK", "KnowledgeDocument", doc.id, current_user.id, f"Rolled back '{doc.display_title}' to {target_ver.version_number}")
    flash(f"Document '{doc.display_title}' rolled back to {target_ver.version_number} successfully! AI index restored.", 'info')
    return redirect(url_for('knowledge.index'))


@knowledge_bp.route('/<int:doc_id>/update', methods=['POST'])
@login_required
def update_heading(doc_id: int):
    """Update document heading and category (Admin & Manager)."""
    if current_user.is_employee:
        flash("Unauthorized.", 'danger')
        return redirect(url_for('knowledge.index'))

    doc = KnowledgeDocument.query.get_or_404(doc_id)
    new_title = request.form.get('title', '').strip()
    new_cat = request.form.get('category', '').strip()

    if new_title:
        doc.title = new_title
    if new_cat:
        doc.category = new_cat

    db.session.commit()
    # Rebuild vector store metadata with new title
    VectorStoreManager.rebuild_index()
    AuditLog.log("DOC_UPDATED", "KnowledgeDocument", doc.id, current_user.id, f"Updated heading to '{doc.title}'")
    flash(f"Document heading updated to '{doc.display_title}' successfully!", 'success')
    return redirect(url_for('knowledge.index'))


@knowledge_bp.route('/<int:doc_id>/reprocess', methods=['POST'])
@login_required
def reprocess(doc_id: int):
    """Reprocess document and rebuild embeddings."""
    if current_user.is_employee:
        flash("Unauthorized.", 'danger')
        return redirect(url_for('knowledge.index'))

    success, error = RAGService.ingest_document(doc_id)
    if success:
        flash("Document reprocessed and vector store updated.", 'success')
    else:
        flash(f"Processing failed: {error}", 'danger')
    return redirect(url_for('knowledge.index'))


@knowledge_bp.route('/<int:doc_id>/delete', methods=['POST'])
@login_required
def delete(doc_id: int):
    """Delete document and update FAISS index (Admin & Manager)."""
    if current_user.is_employee:
        flash("Only Managers and Administrators can delete knowledge documents.", 'danger')
        return redirect(url_for('knowledge.index'))

    doc = KnowledgeDocument.query.get_or_404(doc_id)
    filename = doc.display_title
    db.session.delete(doc)
    db.session.commit()

    # Rebuild vector store
    VectorStoreManager.rebuild_index()
    AuditLog.log("DOC_DELETED", "KnowledgeDocument", doc_id, current_user.id, f"Deleted {filename}")
    flash(f"Document '{filename}' deleted from knowledge base.", 'info')
    return redirect(url_for('knowledge.index'))


@knowledge_bp.route('/<int:doc_id>/view', methods=['GET'])
@login_required
def view_document(doc_id: int):
    """View / stream document file directly in browser."""
    doc = KnowledgeDocument.query.get_or_404(doc_id)
    file_path = Path(doc.file_path)
    if not file_path.exists():
        file_path = current_app.config['DOCUMENTS_DIR'] / doc.filename
    if not file_path.exists():
        flash(f"Document file '{doc.filename}' could not be located on the server disk.", 'danger')
        return redirect(url_for('knowledge.index'))

    mimetype_map = {
        'PDF': 'application/pdf',
        'TXT': 'text/plain; charset=utf-8',
        'MD': 'text/markdown; charset=utf-8',
        'DOCX': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    }
    mimetype = mimetype_map.get(doc.file_type.upper(), 'application/octet-stream')

    return send_file(
        str(file_path),
        mimetype=mimetype,
        as_attachment=False,
        download_name=doc.filename
    )


@knowledge_bp.route('/<int:doc_id>/preview', methods=['GET'])
@login_required
def preview_document(doc_id: int):
    """Return JSON preview of document metadata, headers, and indexed text chunks."""
    doc = KnowledgeDocument.query.get_or_404(doc_id)
    chunks = KnowledgeChunk.query.filter_by(document_id=doc.id).order_by(KnowledgeChunk.chunk_index.asc()).all()

    # Extract unique section headers
    headers = []
    seen = set()
    for c in chunks:
        h = c.section_title or f"Section {c.chunk_index + 1}"
        if h not in seen:
            seen.add(h)
            headers.append({
                'title': h,
                'page': c.page_number or 1,
                'chunk_index': c.chunk_index + 1
            })

    return jsonify({
        'id': doc.id,
        'title': doc.display_title,
        'filename': doc.filename,
        'category': doc.category or 'General IT SOP',
        'file_type': doc.file_type,
        'file_size': f"{round(doc.file_size / 1024, 1)} KB",
        'chunk_count': len(chunks),
        'status': doc.status,
        'uploaded_by': doc.uploader.username if doc.uploader else 'Admin',
        'uploaded_at': doc.created_at.strftime('%b %d, %Y'),
        'view_url': url_for('knowledge.view_document', doc_id=doc.id),
        'detail_url': url_for('knowledge.document_detail', doc_id=doc.id),
        'headers': headers,
        'chunks': [
            {
                'index': c.chunk_index + 1,
                'section': c.section_title or f"Section {c.chunk_index + 1}",
                'page': c.page_number or 1,
                'content': c.content
            }
            for c in chunks[:50]
        ],
        'total_chunks': len(chunks)
    })


@knowledge_bp.route('/search', methods=['GET'])
@login_required
def test_search():
    """Test semantic search against vectorstore directly (supports both HTML & AJAX)."""
    query = request.args.get('q', '').strip()
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.args.get('ajax') == '1' or 'application/json' in request.headers.get('Accept', '')
    results = []
    if query:
        results = VectorStoreManager.search(query, top_k=5)
    
    if is_ajax:
        return jsonify({
            'query': query,
            'total': len(results),
            'results': results
        })

    return render_template('knowledge/knowledge_search.html', query=query, results=results)

