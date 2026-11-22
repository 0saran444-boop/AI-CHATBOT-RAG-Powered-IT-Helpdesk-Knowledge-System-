from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required

from backend.services.rag_service import VectorStoreManager, HistoricalTicketRetriever
from backend.services.llm_service import LLMService

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
    Advanced Gemini RAG Chat query endpoint.
    Retrieves internal knowledge chunks, checks similar historical solutions,
    processes multi-turn conversation memory, and returns an answer with
    interactive follow-up suggestions and model telemetry.
    """
    data = request.get_json() or {}
    user_query = data.get('message', '').strip()
    history = data.get('history', [])

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

    # 4. Generate intelligent answer using Advanced Gemini Engine with Multi-Turn Memory
    result = LLMService.answer_query(
        user_query=user_query,
        knowledge_matches=knowledge_matches,
        similar_tickets=similar_cases,
        conversation_history=history,
        return_meta=True
    )

    answer_text = result.get('answer', '')
    follow_ups = result.get('follow_ups', [])
    model_used = result.get('model_used', 'Google Gemini 3.5')
    latency_ms = result.get('latency_ms', 0)
    confidence = result.get('confidence', 0.90)

    return jsonify({
        'answer': answer_text,
        'follow_ups': follow_ups,
        'model_used': model_used,
        'latency_ms': latency_ms,
        'confidence': confidence,
        'sources': sources,
        'similar_tickets': similar_cases,
        'suggested_ticket_title': user_query[:100],
        'suggested_ticket_description': f"Employee inquired via IT Chatbot:\n\n\"{user_query}\"\n\nResolution steps were provided, but user opted to submit a formal support ticket."
    })
