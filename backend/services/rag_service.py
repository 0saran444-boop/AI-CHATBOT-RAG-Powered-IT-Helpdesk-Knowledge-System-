import os
import json
import pickle
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import numpy as np

# Force offline mode for cached SentenceTransformers to prevent network calls
os.environ['HF_HUB_OFFLINE'] = '1'

from backend.extensions import db
from backend.models.knowledge import KnowledgeDocument, KnowledgeChunk
from backend.models.ticket import Ticket
from backend.models.ai_response import AIResponse
from backend.models.audit import AuditLog

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent.parent
VECTORSTORE_DIR = BASE_DIR / 'vectorstore'
VECTORSTORE_DIR.mkdir(parents=True, exist_ok=True)
FAISS_INDEX_PATH = VECTORSTORE_DIR / 'faiss_index.bin'
METADATA_PATH = VECTORSTORE_DIR / 'chunk_metadata.pkl'


class EmbeddingModelSingleton:
    """Lazy-loaded singleton for SentenceTransformer embeddings."""
    _instance = None

    @classmethod
    def get_model(cls):
        if cls._instance is None:
            try:
                from sentence_transformers import SentenceTransformer
                cls._instance = SentenceTransformer('all-MiniLM-L6-v2', local_files_only=True)
            except Exception as e:
                print(f"[RAG] Warning: Could not load local SentenceTransformer: {e}")
                cls._instance = None
        return cls._instance


class DocumentProcessor:
    """Extracts, cleans, and chunks text from PDF, DOCX, TXT, and Markdown files."""

    @staticmethod
    def extract_text(file_path: str, file_type: str) -> List[Dict[str, Any]]:
        """
        Extract text along with page/section metadata.
        Returns list of dicts: [{'text': str, 'page': int, 'section': str}]
        """
        file_type = file_type.upper().replace('.', '')
        results = []

        if file_type == 'PDF':
            import pypdf
            reader = pypdf.PdfReader(file_path)
            for page_idx, page in enumerate(reader.pages):
                page_text = page.extract_text() or ''
                page_text = page_text.strip()
                if page_text:
                    results.append({
                        'text': page_text,
                        'page': page_idx + 1,
                        'section': f"Page {page_idx + 1}"
                    })

        elif file_type == 'DOCX':
            import docx
            doc = docx.Document(file_path)
            current_section = "General"
            for para in doc.paragraphs:
                p_text = para.text.strip()
                if not p_text:
                    continue
                if para.style.name.startswith('Heading'):
                    current_section = p_text
                results.append({
                    'text': p_text,
                    'page': 1,
                    'section': current_section
                })

        else:  # TXT, MD, etc.
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                full_text = f.read()
            lines = [l.strip() for l in full_text.split('\n\n') if l.strip()]
            for idx, block in enumerate(lines):
                results.append({
                    'text': block,
                    'page': 1,
                    'section': f"Section {idx + 1}"
                })

        return results

    @staticmethod
    def chunk_text(pages_data: List[Dict[str, Any]], chunk_size: int = 500, overlap: int = 80) -> List[Dict[str, Any]]:
        """Sliding window chunking with metadata preservation."""
        chunks = []
        chunk_idx = 0

        for item in pages_data:
            text = item['text']
            page = item['page']
            section = item['section']

            start = 0
            while start < len(text):
                end = start + chunk_size
                chunk_str = text[start:end].strip()
                if len(chunk_str) > 30:  # Minimum meaningful text
                    chunks.append({
                        'chunk_index': chunk_idx,
                        'content': chunk_str,
                        'page_number': page,
                        'section_title': section
                    })
                    chunk_idx += 1
                start += (chunk_size - overlap)

        return chunks


class VectorStoreManager:
    """Manages FAISS index generation, persistence, and semantic similarity search."""

    @classmethod
    def rebuild_index(cls) -> bool:
        """Re-index all active knowledge chunks from database into FAISS."""
        import faiss

        all_chunks = KnowledgeChunk.query.all()
        if not all_chunks:
            if FAISS_INDEX_PATH.exists():
                FAISS_INDEX_PATH.unlink()
            if METADATA_PATH.exists():
                METADATA_PATH.unlink()
            return True

        model = EmbeddingModelSingleton.get_model()
        if not model:
            return False

        texts = [c.content for c in all_chunks]
        embeddings = model.encode(texts, normalize_embeddings=True)
        embeddings = np.array(embeddings, dtype=np.float32)

        dimension = embeddings.shape[1]
        # Inner product on normalized vectors equals cosine similarity
        index = faiss.IndexFlatIP(dimension)
        index.add(embeddings)

        # Save metadata mapping index position to chunk info
        metadata = [
            {
                'chunk_id': c.id,
                'document_id': c.document_id,
                'document_name': (c.document.title or c.document.filename) if c.document else '',
                'content': c.content,
                'page_number': c.page_number,
                'section_title': c.section_title
            }
            for c in all_chunks
        ]

        faiss.write_index(index, str(FAISS_INDEX_PATH))
        with open(METADATA_PATH, 'wb') as f:
            pickle.dump(metadata, f)

        return True

    @classmethod
    def search(cls, query: str, top_k: int = 4, min_score: float = 0.25) -> List[Dict[str, Any]]:
        """Perform semantic search against indexed knowledge base chunks."""
        import faiss

        if not FAISS_INDEX_PATH.exists() or not METADATA_PATH.exists():
            return []

        model = EmbeddingModelSingleton.get_model()
        if not model:
            return []

        query_vector = model.encode([query], normalize_embeddings=True)
        query_vector = np.array(query_vector, dtype=np.float32)

        index = faiss.read_index(str(FAISS_INDEX_PATH))
        with open(METADATA_PATH, 'rb') as f:
            metadata = pickle.load(f)

        scores, indices = index.search(query_vector, min(top_k, len(metadata)))
        results = []

        for score, idx in zip(scores[0], indices[0]):
            if idx < len(metadata) and score >= min_score:
                item = metadata[idx].copy()
                item['score'] = float(score)
                results.append(item)

        return results


class HistoricalTicketRetriever:
    """Retrieves similar previously resolved tickets for incident pattern matching."""

    @classmethod
    def search_similar(cls, query: str, exclude_ticket_id: Optional[int] = None, top_k: int = 2) -> List[Dict[str, Any]]:
        """Search resolved tickets by title/description and resolution similarity."""
        resolved_tickets = Ticket.query.filter(
            Ticket.status.in_([Ticket.STATUS_RESOLVED, Ticket.STATUS_CLOSED]),
            Ticket.resolution_summary.isnot(None)
        ).all()

        if exclude_ticket_id:
            resolved_tickets = [t for t in resolved_tickets if t.id != exclude_ticket_id]

        if not resolved_tickets:
            return []

        model = EmbeddingModelSingleton.get_model()
        if not model:
            # Fallback simple keyword match
            keywords = [w.lower() for w in query.split() if len(w) > 3]
            matches = []
            for t in resolved_tickets:
                target = f"{t.title} {t.description} {t.resolution_summary}".lower()
                overlap = sum(1 for kw in keywords if kw in target)
                if overlap > 0:
                    matches.append({
                        'ticket_number': t.ticket_number,
                        'title': t.title,
                        'root_cause': t.root_cause or 'N/A',
                        'resolution_summary': t.resolution_summary,
                        'similarity_score': min(0.95, round(0.4 + (overlap * 0.1), 2))
                    })
            matches.sort(key=lambda x: x['similarity_score'], reverse=True)
            return matches[:top_k]

        ticket_texts = [f"{t.title}. {t.description}. Resolution: {t.resolution_summary}" for t in resolved_tickets]
        query_emb = model.encode([query], normalize_embeddings=True)
        ticket_embs = model.encode(ticket_texts, normalize_embeddings=True)

        # Dot product for cosine similarity
        similarities = np.dot(ticket_embs, query_emb.T).flatten()

        ranked = []
        for idx, sim in enumerate(similarities):
            if sim >= 0.35:  # Relevance threshold
                t = resolved_tickets[idx]
                ranked.append({
                    'ticket_number': t.ticket_number,
                    'title': t.title,
                    'root_cause': t.root_cause or 'N/A',
                    'action_taken': t.action_taken or 'Resolved by technician',
                    'resolution_summary': t.resolution_summary,
                    'similarity_score': round(float(sim), 2)
                })

        ranked.sort(key=lambda x: x['similarity_score'], reverse=True)
        return ranked[:top_k]


class RAGService:
    """Core RAG service orchestrating document ingestion, vector retrieval, and AI resolution."""

    @classmethod
    def ingest_document(cls, document_id: int) -> Tuple[bool, Optional[str]]:
        """Process an uploaded document into knowledge chunks and update FAISS index."""
        doc = KnowledgeDocument.query.get(document_id)
        if not doc:
            return False, "Document not found"

        doc.status = KnowledgeDocument.STATUS_PROCESSING
        db.session.commit()

        try:
            # 1. Text extraction
            pages_data = DocumentProcessor.extract_text(doc.file_path, doc.file_type)
            if not pages_data:
                doc.status = KnowledgeDocument.STATUS_FAILED
                doc.error_message = "No readable text found in document"
                db.session.commit()
                return False, doc.error_message

            # 2. Text chunking
            chunks_data = DocumentProcessor.chunk_text(pages_data)

            # Clear existing chunks for this document
            KnowledgeChunk.query.filter_by(document_id=doc.id).delete()

            # 3. Save chunks in database
            for item in chunks_data:
                chunk = KnowledgeChunk(
                    document_id=doc.id,
                    chunk_index=item['chunk_index'],
                    content=item['content'],
                    page_number=item['page_number'],
                    section_title=item['section_title']
                )
                db.session.add(chunk)

            doc.chunk_count = len(chunks_data)
            doc.status = KnowledgeDocument.STATUS_PROCESSED
            doc.error_message = None
            db.session.commit()

            # 4. Rebuild vector store index
            VectorStoreManager.rebuild_index()

            AuditLog.log("DOC_PROCESSED", "KnowledgeDocument", doc.id, doc.uploaded_by_id, f"Indexed {len(chunks_data)} chunks from {doc.filename}")
            return True, None

        except Exception as e:
            db.session.rollback()
            doc.status = KnowledgeDocument.STATUS_FAILED
            doc.error_message = str(e)
            db.session.commit()
            return False, f"Ingestion error: {str(e)}"

    @classmethod
    def generate_resolution(cls, ticket_id: int) -> Optional[AIResponse]:
        """
        Generate an AI resolution suggestion for a ticket using retrieved knowledge and historical cases.
        Guarantees structured output, fallback extraction, and human-in-the-loop review state.
        """
        ticket = Ticket.query.get(ticket_id)
        if not ticket:
            return None

        query = f"{ticket.title}. {ticket.description}"

        # 1. Semantic retrieval from knowledge documents
        knowledge_matches = VectorStoreManager.search(query, top_k=4)

        # 2. Historical similar tickets retrieval
        similar_tickets = HistoricalTicketRetriever.search_similar(query, exclude_ticket_id=ticket.id, top_k=2)

        # 3. Format sources for UI display
        sources = [
            {
                'document_name': k['document_name'],
                'page': k.get('page_number', 1),
                'section': k.get('section_title', 'General'),
                'snippet': k['content'][:220] + ('...' if len(k['content']) > 220 else ''),
                'relevance': f"{int(k.get('score', 0) * 100)}%"
            }
            for k in knowledge_matches
        ]

        # 4. Synthesize AI Resolution
        ai_data = cls._synthesize_resolution(ticket, knowledge_matches, similar_tickets)

        # 5. Persist AIResponse
        ai_response = AIResponse(
            ticket_id=ticket.id,
            issue_summary=ai_data['issue_summary'],
            possible_causes=json.dumps(ai_data['possible_causes']),
            recommended_steps=json.dumps(ai_data['recommended_steps']),
            knowledge_sources=json.dumps(sources),
            similar_tickets=json.dumps(similar_tickets),
            escalation_recommended=ai_data['escalation_recommended'],
            confidence_score=ai_data['confidence_score'],
            status=AIResponse.STATUS_GENERATED
        )
        db.session.add(ai_response)

        # Update ticket status to CLASSIFIED if still NEW
        if ticket.status == Ticket.STATUS_NEW:
            ticket.status = Ticket.STATUS_CLASSIFIED

        db.session.commit()

        AuditLog.log("AI_GENERATED", "Ticket", ticket.id, None, f"Generated resolution suggestion for {ticket.ticket_number}")
        return ai_response

    @classmethod
    def _synthesize_resolution(cls, ticket: Ticket, knowledge_matches: List[Dict], similar_tickets: List[Dict]) -> Dict[str, Any]:
        """
        Build resolution recommendation using LLM if available, or domain-grounded synthesis fallback.
        """
        from backend.services.llm_service import LLMService

        # Try Gemini API structured resolution first
        llm_result = LLMService.generate_ticket_solution(
            ticket_number=ticket.ticket_number,
            title=ticket.title,
            description=ticket.description,
            category_name=ticket.category.name if ticket.category else 'General',
            knowledge_matches=knowledge_matches,
            similar_tickets=similar_tickets
        )
        if llm_result:
            return llm_result

        # Intelligent local synthesis fallback (Grounding from matches & ticket semantics)
        title_lower = ticket.title.lower()
        desc_lower = ticket.description.lower()
        full_text = f"{title_lower} {desc_lower}"

        causes = []
        steps = []
        escalate = False
        confidence = 0.70

        if knowledge_matches:
            confidence = min(0.94, round(0.70 + (float(knowledge_matches[0].get('score', 0.5)) * 0.25), 2))
            # Extract key insights from best match
            best_chunk = knowledge_matches[0]['content']
            lines = [l.strip() for l in best_chunk.split('\n') if len(l.strip()) > 15]
            for line in lines[:3]:
                if any(c in line.lower() for c in ['error', 'cause', 'reason', 'issue', 'fail']):
                    causes.append(line.lstrip('-•0123456789. '))
                elif any(s in line.lower() for s in ['verify', 'check', 'restart', 'run', 'configure', 'ensure', 'open']):
                    steps.append(line.lstrip('-•0123456789. '))

        if similar_tickets:
            best_hist = similar_tickets[0]
            if best_hist.get('root_cause') and best_hist['root_cause'] != 'N/A':
                causes.insert(0, f"Historical Cause ({best_hist['ticket_number']}): {best_hist['root_cause']}")
            if best_hist.get('resolution_summary'):
                steps.append(f"Previously effective resolution ({best_hist['ticket_number']}): {best_hist['resolution_summary']}")

        # Fallback contextual rules when documents do not specify steps
        if 'vpn' in full_text:
            summary = f"VPN tunnel connectivity problem preventing internal corporate resource access."
            if not causes:
                causes = [
                    "Internal DNS resolution failure over VPN interface",
                    "Split tunneling configuration route mismatch",
                    "Expired SSL VPN authentication credentials or certificate"
                ]
            if not steps:
                steps = [
                    "1. Confirm VPN connection status and IP assignment (10.x.x.x)",
                    "2. Flush client DNS cache with 'ipconfig /flushdns'",
                    "3. Test internal host connectivity using 'ping' and 'tracert'",
                    "4. If unresolved after restart, escalate to Network Support"
                ]
        elif any(w in full_text for w in ['password', 'login', 'account', 'locked']):
            summary = "Authentication or credential access failure."
            if not causes:
                causes = [
                    "Account locked due to consecutive failed password attempts",
                    "Password expired per active directory domain policy",
                    "MFA device token out of sync"
                ]
            if not steps:
                steps = [
                    "1. Verify user Active Directory status in Admin Console",
                    "2. Check if account is locked and unlock if appropriate",
                    "3. Initiate self-service password reset or issue temporary PIN",
                    "4. Validate MFA authenticator app enrollment"
                ]
        elif any(w in full_text for w in ['printer', 'spooler', 'print']):
            summary = "Printer hardware, network print queue, or driver communication fault."
            if not causes:
                causes = [
                    "Print spooler service halted on user workstation",
                    "Network printer IP address changed or offline",
                    "Corrupt local print driver"
                ]
            if not steps:
                steps = [
                    "1. Restart the Windows Print Spooler service ('net stop spooler && net start spooler')",
                    "2. Verify printer physical power, paper tray, and IP reachability",
                    "3. Remove and re-add printer via organizational print server",
                    "4. Reinstall certified PCL6 printer driver"
                ]
        else:
            summary = f"Technical incident reported regarding: {ticket.title}."
            if not causes:
                causes = [
                    "Application process deadlock or unexpected configuration exception",
                    "Local cache corruption or conflicting operating system policy",
                    "Network endpoint communication timeout"
                ]
            if not steps:
                steps = [
                    "1. Gather specific error message screenshots and diagnostic log files",
                    "2. Perform clean application restart and workstation reboot",
                    "3. Verify user group security privileges for the target service",
                    "4. If persistent, escalate ticket to Tier 2 Engineering"
                ]

        if ticket.priority == Ticket.PRIORITY_CRITICAL or 'escalat' in full_text:
            escalate = True

        return {
            'issue_summary': summary,
            'possible_causes': causes[:4],
            'recommended_steps': steps[:5],
            'escalation_recommended': escalate,
            'confidence_score': confidence
        }

