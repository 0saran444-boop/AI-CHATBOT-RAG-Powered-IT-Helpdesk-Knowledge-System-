import os
import json
import logging
from typing import List, Dict, Any, Optional
import requests

logger = logging.getLogger(__name__)

GEMINI_MODEL = "gemini-3.5-flash-lite"
API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"


class LLMService:
    """Service to interact with Google Gemini API for intelligent IT helpdesk answers."""

    @staticmethod
    def get_api_key() -> Optional[str]:
        key = os.environ.get('GEMINI_API_KEY', '').strip()
        if key and not key.startswith('your-'):
            return key
        return None

    @classmethod
    def answer_query(
        cls,
        user_query: str,
        knowledge_matches: Optional[List[Dict[str, Any]]] = None,
        similar_tickets: Optional[List[Dict[str, Any]]] = None
    ) -> str:
        """
        Generate a question-based answer for the user query.
        Uses internal SOPs and historical tickets if present;
        otherwise provides an intelligent IT/technical explanation with helpdesk context.
        """
        api_key = cls.get_api_key()
        knowledge_matches = knowledge_matches or []
        similar_tickets = similar_tickets or []

        # If API key is available, use Gemini for synthesis
        if api_key:
            try:
                if knowledge_matches:
                    sop_texts = []
                    for idx, doc in enumerate(knowledge_matches[:3], 1):
                        sop_texts.append(
                            f"Document [{idx}]: {doc.get('document_name', 'SOP')} "
                            f"(Section: {doc.get('section_title', 'General')})\n"
                            f"Content:\n{doc.get('content', '')}"
                        )
                    sop_context = "\n\n".join(sop_texts)

                    hist_texts = []
                    for t in similar_tickets[:2]:
                        hist_texts.append(
                            f"Ticket #{t.get('ticket_number')}: {t.get('title')}\n"
                            f"Resolution: {t.get('resolution_summary')}"
                        )
                    hist_context = "\n\n".join(hist_texts) if hist_texts else "None"

                    prompt = f"""You are an expert IT Helpdesk AI Assistant.
An employee asked the following question:
"{user_query}"

Internal Company IT Documentation & SOPs:
{sop_context}

Past Resolved Tickets:
{hist_context}

Instructions:
1. Always prioritize answering the employee's exact question accurately and directly: "{user_query}".
2. First, evaluate whether the provided Internal Documentation & SOPs actually contain the correct answer to the question asked.
   - If YES (e.g., corporate VPN setup, email configuration, password policy, company software):
     Provide clear step-by-step instructions based on the internal SOP, and cite the document name (e.g. "**{knowledge_matches[0].get('document_name')}**").
   - If NO or if the match is merely superficial or unrelated keyword overlap (e.g., internal notes mention "father of HTML" but the user asked "who is father of computer", or general programming/IT concepts):
     Directly and correctly answer the employee's actual question using factual general knowledge (e.g., stating that Charles Babbage is the father of the computer). Do NOT force unrelated internal document excerpts as the answer.
3. If past resolved tickets provide a proven resolution for this exact issue, highlight it as a quick tip.
4. Keep the response structured, clear, and professional."""
                else:
                    prompt = f"""You are an expert IT Helpdesk AI Assistant.
An employee asked the following question:
"{user_query}"

This specific topic is not currently indexed in our company's internal SOP knowledge base.

Instructions:
1. Provide a direct, informative, and question-based answer explaining the topic or resolving the technical inquiry clearly and accurately.
2. Structure your explanation cleanly with bullet points, numbered steps, or concise paragraphs as appropriate.
3. At the end of your response, add this exact note:
\n\nℹ️ *Note: This response is based on general IT & technical knowledge. If you need company software access, licenses, or internal configuration assistance, please click **Create Ticket From This Question** below to connect with an IT engineer.*"""

                url = f"{API_URL}?key={api_key}"
                payload = {
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "temperature": 0.3,
                        "maxOutputTokens": 1024
                    }
                }

                resp = requests.post(url, json=payload, timeout=20)
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        if parts and "text" in parts[0]:
                            return parts[0]["text"].strip()
                else:
                    logger.warning(f"[LLMService] Gemini API returned {resp.status_code}: {resp.text}")
            except Exception as e:
                logger.error(f"[LLMService] Error calling Gemini API: {e}")

        # Local fallback if Gemini fails or is offline
        if knowledge_matches:
            top_doc = knowledge_matches[0]
            answer = (
                f"Based on our internal IT documentation (**{top_doc['document_name']}**, {top_doc.get('section_title', 'Section')}):\n\n"
                f"{top_doc['content']}\n\n"
            )
            if similar_tickets:
                answer += (
                    f"\n💡 *A similar incident ({similar_tickets[0]['ticket_number']}) was previously resolved:* "
                    f"{similar_tickets[0]['resolution_summary']}"
                )
            return answer

        return (
            f"Here is information regarding your inquiry on **{user_query}**:\n\n"
            f"This topic is not currently indexed in our internal SOP knowledge base. "
            f"You can submit a ticket using the **Create Support Ticket** button below so an IT engineer can assist you directly."
        )

    @classmethod
    def generate_ticket_solution(
        cls,
        ticket_number: str,
        title: str,
        description: str,
        category_name: str,
        knowledge_matches: List[Dict[str, Any]],
        similar_tickets: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """
        Generate structured JSON resolution analysis for an IT support ticket.
        """
        api_key = cls.get_api_key()
        if not api_key:
            return None

        try:
            context_docs = "\n\n".join([
                f"Source: {k['document_name']} (Page {k.get('page_number', 1)})\n{k['content']}"
                for k in knowledge_matches
            ])
            context_hist = "\n\n".join([
                f"Ticket: {t['ticket_number']} - {t['title']}\nResolution: {t['resolution_summary']}"
                for t in similar_tickets
            ])

            prompt = f"""You are an expert IT Helpdesk AI Assistant.
Analyze this IT support ticket and provide a structured troubleshooting guide based strictly on the provided internal documents and past tickets.

Ticket: {ticket_number} - {title}
Description: {description}
Category: {category_name}

Internal Knowledge:
{context_docs or 'No internal documentation found.'}

Historical Incidents:
{context_hist or 'No similar past tickets found.'}

Respond ONLY with a JSON object adhering to this schema:
{{
  "issue_summary": "Concise 1-2 sentence statement of the technical problem",
  "possible_causes": ["Cause 1", "Cause 2", "Cause 3"],
  "recommended_steps": ["Step 1: Check ...", "Step 2: Run ...", "Step 3: Verify ..."],
  "escalation_recommended": false,
  "confidence_score": 0.88
}}
"""
            url = f"{API_URL}?key={api_key}"
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "temperature": 0.2
                }
            }

            resp = requests.post(url, json=payload, timeout=20)
            if resp.status_code == 200:
                data = resp.json()
                candidates = data.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if parts and "text" in parts[0]:
                        parsed = json.loads(parts[0]["text"])
                        return {
                            "issue_summary": parsed.get("issue_summary", title),
                            "possible_causes": parsed.get("possible_causes", []),
                            "recommended_steps": parsed.get("recommended_steps", []),
                            "escalation_recommended": bool(parsed.get("escalation_recommended", False)),
                            "confidence_score": float(parsed.get("confidence_score", 0.85))
                        }
            else:
                logger.warning(f"[LLMService] Gemini JSON generation returned {resp.status_code}: {resp.text}")
        except Exception as e:
            logger.error(f"[LLMService] Error during ticket solution generation: {e}")

        return None
