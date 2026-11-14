from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user
import json

from backend.services.rag_service import VectorStoreManager, HistoricalTicketRetriever, RAGService
from backend.services.llm_service import LLMService
from backend.models.knowledge import KnowledgeChunk

chat_bp = Blueprint('chat', __name__, url_prefix='/chat')


@chat_bp.route('', methods=['GET'])
@chat_bp.route('/', methods=['GET'])
@login_required
def index():
    """Interactive Self-Service IT Helpdesk Chatbot for employees."""
    return render_template('chat/chat.html')


@chat_bp.route('/query', methods=['POST'])
@login_required
def query_bot():
    """
    RAG Chat query endpoint.
    Retrieves knowledge chunks, checks similar historical solutions,
    and returns an answer with source citations.
    """
    data = request.get_json() or {}
    user_query = data.get('message', '').strip()

    if not user_query:
        return jsonify({'error': 'Message cannot be empty'}), 400

    # 1. Vector Search against internal SOPs
    knowledge_matches = VectorStoreManager.search(user_query, top_k=3)

    # 2. Similar historical tickets
    similar_cases = HistoricalTicketRetriever.search_similar(user_query, top_k=2)

    # 3. Format sources
    sources = [
        {
            'document_name': k['document_name'],
            'page': k.get('page_number', 1),
            'section': k.get('section_title', 'General'),
            'snippet': k['content'][:200] + '...',
            'relevance': f"{int(k.get('score', 0) * 100)}%"
        }
        for k in knowledge_matches
    ]

    # 4. Generate intelligent, question-based answer using Gemini & internal RAG context
    answer_text = LLMService.answer_query(
        user_query=user_query,
        knowledge_matches=knowledge_matches,
        similar_tickets=similar_cases
    )

    return jsonify({
        'answer': answer_text,
        'sources': sources,
        'similar_tickets': similar_cases,
        'suggested_ticket_title': user_query[:100],
        'suggested_ticket_description': f"Employee inquired via IT Chatbot:\n\n\"{user_query}\"\n\nBot suggested internal SOPs, but user opted to submit formal support ticket."
    })
