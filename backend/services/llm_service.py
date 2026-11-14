import os
import json
import logging
import re
import time
from typing import List, Dict, Any, Optional, Union
import requests

logger = logging.getLogger(__name__)

# Advanced Gemini Model Priority Chain (Failover resilience)
PRIMARY_MODEL = os.environ.get('GEMINI_PRIMARY_MODEL', 'gemini-3.8-flash')
FALLBACK_MODELS = [
    PRIMARY_MODEL,
    'gemini-3.8-flash',
    'gemini-3.5-flash-lite',
    'gemini-3.5-flash',
    'gemini-flash-latest'
]
# Remove duplicates while preserving order
GEMINI_MODELS = list(dict.fromkeys(FALLBACK_MODELS))

BASE_API_URL = "https://generativelanguage.googleapis.com/v1beta/models"

SYSTEM_INSTRUCTION = (
    "You are Gemini Enterprise IT Support Specialist — an advanced, authoritative AI helpdesk technician "
    "with deep expertise in enterprise IT infrastructure, Windows, macOS, Linux, networking (VPN, DNS, DHCP, Proxies), "
    "cloud services (Microsoft 365, Exchange, Active Directory), cybersecurity, hardware, and desktop troubleshooting.\n\n"
    "Core Principles:\n"
    "1. Priority Grounding: When provided with Company SOPs or Historical Resolved Tickets, evaluate if they directly solve the inquiry. "
    "If YES, base your instructions on the internal documentation and clearly cite the document name (e.g. **[VPN Setup Guide] (Section: Troubleshooting)**). "
    "If the question is general computing knowledge or internal docs have only superficial keyword overlap, provide a factual, accurate technical answer.\n"
    "2. Structured Troubleshooting:\n"
    "   - Direct Answer / Summary\n"
    "   - Root Cause Analysis (explain why the problem occurs)\n"
    "   - Step-by-Step Resolution with clear terminal/PowerShell/bash commands in fenced code blocks\n"
    "   - Verification Step (how the user verifies the fix worked)\n"
    "   - Safety Warnings when dealing with destructive operations (e.g. deleting files, registry changes)\n"
    "3. Multi-turn Cohesion: Seamlessly refer back to previous conversation turns when asked follow-up questions.\n"
    "4. Follow-up Suggestions: At the very end of your response, output exactly 2 or 3 relevant follow-up questions formatted strictly as:\n"
    "💡 Follow-up suggestions:\n"
    "- Question 1\n"
    "- Question 2\n"
    "- Question 3"
)


class LLMService:
    """Advanced Service to interact with Google Gemini API with multi-model fallback, multi-turn memory, and RAG grounding."""

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
        similar_tickets: Optional[List[Dict[str, Any]]] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        return_meta: bool = False
    ) -> Union[str, Dict[str, Any]]:
        """
        Generate an advanced question-based answer using Google Gemini.
        Supports multi-turn conversation memory, dynamic multi-model failover,
        and grounding against internal SOPs and past tickets.
        """
        api_key = cls.get_api_key()
        knowledge_matches = knowledge_matches or []
        similar_tickets = similar_tickets or []
        conversation_history = conversation_history or []
        start_time = time.time()

        # Build prompt with RAG grounding context
        if knowledge_matches:
            sop_texts = []
            for idx, doc in enumerate(knowledge_matches[:3], 1):
                sop_texts.append(
                    f"Document [{idx}]: {doc.get('document_name', 'SOP')} "
                    f"(Section: {doc.get('section_title', 'General')}, Page: {doc.get('page_number', 1)})\n"
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

            current_turn_prompt = (
                f"An employee asked the following technical inquiry:\n"
                f"\"{user_query}\"\n\n"
                f"Internal Company IT Documentation & SOPs:\n{sop_context}\n\n"
                f"Past Resolved Similar Tickets:\n{hist_context}\n\n"
                f"Instructions:\n"
                f"1. Evaluate whether the internal SOPs contain the answer to \"{user_query}\".\n"
                f"   - If YES: Provide step-by-step instructions based on the internal SOP, citing the document name (e.g. **{knowledge_matches[0].get('document_name')}**).\n"
                f"   - If NO or superficial overlap: Answer the employee's actual question accurately using technical knowledge.\n"
                f"2. Include root cause, troubleshooting steps, and exact terminal/powershell commands where applicable.\n"
                f"3. Provide 2-3 follow-up suggestions at the end."
            )
        else:
            current_turn_prompt = (
                f"An employee asked the following technical inquiry:\n"
                f"\"{user_query}\"\n\n"
                f"Note: This specific topic is not currently indexed in our company's internal SOP knowledge base.\n\n"
                f"Instructions:\n"
                f"1. Provide a direct, authoritative, step-by-step technical explanation resolving the inquiry.\n"
                f"2. Structure cleanly with code blocks, bullet points, or numbered steps.\n"
                f"3. At the end, add: ℹ️ *Note: Based on general IT engineering knowledge. For physical hardware or domain credential issues, you can submit a ticket below.*\n"
                f"4. Provide 2-3 follow-up suggestions at the end."
            )

        # Assemble multi-turn contents for Gemini
        contents = []
        if conversation_history:
            # Take up to the last 6 messages to preserve context while maintaining efficiency
            for turn in conversation_history[-6:]:
                role = turn.get('role', 'user')
                if role in ('bot', 'assistant'):
                    role = 'model'
                text_content = turn.get('text') or turn.get('content') or ''
                if text_content and text_content.strip():
                    contents.append({
                        "role": role,
                        "parts": [{"text": text_content.strip()}]
                    })

        # Append the current query with RAG context as the final user turn
        contents.append({
            "role": "user",
            "parts": [{"text": current_turn_prompt}]
        })

        # If API key is available, attempt Gemini generation across fallback models
        if api_key:
            for model_name in GEMINI_MODELS:
                try:
                    url = f"{BASE_API_URL}/{model_name}:generateContent?key={api_key}"
                    payload = {
                        "systemInstruction": {
                            "parts": [{"text": SYSTEM_INSTRUCTION}]
                        },
                        "contents": contents,
                        "generationConfig": {
                            "temperature": 0.25,
                            "topP": 0.95,
                            "maxOutputTokens": 1500
                        }
                    }

                    timeout = 6 if '3.8' in model_name else 12
                    resp = requests.post(url, json=payload, timeout=timeout)
                    if resp.status_code == 200:
                        data = resp.json()
                        candidates = data.get("candidates", [])
                        if candidates:
                            parts = candidates[0].get("content", {}).get("parts", [])
                            if parts and "text" in parts[0]:
                                raw_text = parts[0]["text"].strip()
                                elapsed_ms = int((time.time() - start_time) * 1000)

                                # Extract follow-up suggestions from response
                                follow_ups = []
                                match = re.search(r'💡\s*Follow-up suggestions:\s*\n((?:[-*]\s*.+\n?)+)', raw_text, re.IGNORECASE)
                                if match:
                                    lines = match.group(1).strip().split('\n')
                                    follow_ups = [l.strip().lstrip('-*').strip() for l in lines if l.strip()]
                                    clean_answer = raw_text[:match.start()].strip()
                                else:
                                    clean_answer = raw_text

                                clean_model_name = model_name.replace('-', ' ').title()
                                if return_meta:
                                    return {
                                        "answer": clean_answer,
                                        "follow_ups": follow_ups[:3],
                                        "model_used": f"Google {clean_model_name}",
                                        "latency_ms": elapsed_ms,
                                        "confidence": 0.95 if knowledge_matches else 0.88
                                    }
                                return clean_answer
                    else:
                        logger.warning(f"[LLMService] Model {model_name} returned HTTP {resp.status_code}: {resp.text[:120]}")
                except Exception as e:
                    logger.warning(f"[LLMService] Model {model_name} invocation failed: {e}. Trying fallback...")

        # Local intelligent synthesis fallback if API key absent or all Gemini calls fail
        elapsed_ms = int((time.time() - start_time) * 1000)
        default_follow_ups = [
            "How do I verify network connectivity?",
            "What if restarting the service does not help?",
            "How do I escalate this to Level 2 support?"
        ]

        if knowledge_matches:
            top_doc = knowledge_matches[0]
            answer = (
                f"### Verified Company SOP Guidance\n\n"
                f"Based on internal IT documentation (**{top_doc['document_name']}**, {top_doc.get('section_title', 'Section')}):\n\n"
                f"{top_doc['content']}\n\n"
            )
            if similar_tickets:
                answer += (
                    f"\n💡 *A similar incident ({similar_tickets[0]['ticket_number']}) was previously resolved:*\n"
                    f"> {similar_tickets[0]['resolution_summary']}\n"
                )
            if return_meta:
                return {
                    "answer": answer,
                    "follow_ups": default_follow_ups,
                    "model_used": "Internal RAG Knowledge Engine",
                    "latency_ms": elapsed_ms,
                    "confidence": 0.90
                }
            return answer

        fallback_answer = (
            f"Here is guidance regarding your inquiry on **{user_query}**:\n\n"
            f"This topic is not currently indexed in our company's internal SOP knowledge base.\n\n"
            f"**Recommended Steps:**\n"
            f"1. Check physical network cable and Wi-Fi connection.\n"
            f"2. Restart the affected software application or reboot your laptop.\n"
            f"3. If this requires IT domain permissions or corporate software licenses, please click **Create Support Ticket** below so a desktop engineer can assist you directly."
        )
        if return_meta:
            return {
                "answer": fallback_answer,
                "follow_ups": default_follow_ups,
                "model_used": "Internal RAG Fallback",
                "latency_ms": elapsed_ms,
                "confidence": 0.75
            }
        return fallback_answer

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
        Generate structured JSON resolution analysis for an IT support ticket using Gemini.
        Features multi-model failover and structured schema validation.
        """
        api_key = cls.get_api_key()
        if not api_key:
            return None

        context_docs = "\n\n".join([
            f"Source: {k['document_name']} (Page {k.get('page_number', 1)})\n{k['content']}"
            for k in knowledge_matches
        ])
        context_hist = "\n\n".join([
            f"Ticket: {t['ticket_number']} - {t['title']}\nResolution: {t['resolution_summary']}"
            for t in similar_tickets
        ])

        prompt = f"""You are Gemini Enterprise IT Support AI Specialist.
Analyze this IT support ticket and provide a structured troubleshooting guide based strictly on the provided internal documents and past tickets.

Ticket: {ticket_number} - {title}
Description: {description}
Category: {category_name}

Internal Knowledge Base:
{context_docs or 'No internal documentation found.'}

Historical Incidents:
{context_hist or 'No similar past tickets found.'}

Respond ONLY with a valid JSON object adhering to this schema:
{{
  "issue_summary": "Concise 1-2 sentence statement of the technical problem",
  "possible_causes": ["Cause 1", "Cause 2", "Cause 3"],
  "recommended_steps": ["Step 1: Check ...", "Step 2: Run ...", "Step 3: Verify ..."],
  "preventative_actions": ["Action 1 to prevent recurrence"],
  "escalation_recommended": false,
  "confidence_score": 0.90
}}
"""
        for model_name in GEMINI_MODELS:
            try:
                url = f"{BASE_API_URL}/{model_name}:generateContent?key={api_key}"
                payload = {
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "responseMimeType": "application/json",
                        "temperature": 0.2
                    }
                }

                resp = requests.post(url, json=payload, timeout=12)
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
                                "preventative_actions": parsed.get("preventative_actions", []),
                                "escalation_recommended": bool(parsed.get("escalation_recommended", False)),
                                "confidence_score": float(parsed.get("confidence_score", 0.88)),
                                "model_used": f"Google {model_name.replace('-', ' ').title()}"
                            }
                else:
                    logger.warning(f"[LLMService] Model {model_name} JSON generation returned HTTP {resp.status_code}")
            except Exception as e:
                logger.warning(f"[LLMService] Model {model_name} JSON generation failed: {e}")

        return None
