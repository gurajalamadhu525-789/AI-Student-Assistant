
import os
import json
import logging
from urllib.parse import urlparse

import requests
from flask import Flask, render_template, request, jsonify, Response
from pypdf import PdfReader
from werkzeug.exceptions import RequestEntityTooLarge

# --------------------------------------------------
# Flask configuration
# --------------------------------------------------

app = Flask(__name__, template_folder="templates")

app.config["MAX_CONTENT_LENGTH"] = 15 * 1024 * 1024

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

# --------------------------------------------------
# Remote Ollama configuration
# --------------------------------------------------
# Example:
# OLLAMA_BASE_URL=https://your-secure-ollama-server.example.com
# OLLAMA_MODEL=llama3.2
#
# Do NOT use localhost here for a remote Render deployment.
# OLLAMA_API_KEY is optional and is only useful if your
# remote server or proxy is configured to accept it.

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "").strip().rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2").strip()
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "").strip()

OLLAMA_TIMEOUT_CONNECT = 10
OLLAMA_TIMEOUT_READ = 180
MAX_HISTORY_MESSAGES = 12
MAX_PROMPT_LENGTH = 12000
MAX_PDF_TEXT_LENGTH = 30000

SYSTEM_PROMPT = """
You are an AI Student Assistant.
Help students understand programming, academic subjects, interview
preparation, project development, and study planning.

Use simple, clear explanations and practical examples when helpful.
For coding questions, provide correct code and explain the important parts.
If a question is unclear, ask for clarification.
Do not invent facts when you are unsure.
"""

# --------------------------------------------------
# Custom errors
# --------------------------------------------------


class AIServiceError(Exception):
    """An expected error communicating with the AI service."""


# --------------------------------------------------
# Utility functions
# --------------------------------------------------


def get_ollama_chat_url():
    """Build and validate the remote Ollama chat endpoint."""

    if not OLLAMA_BASE_URL:
        raise AIServiceError(
            "Remote AI is not configured. Set OLLAMA_BASE_URL "
            "in your deployment environment."
        )

    parsed = urlparse(OLLAMA_BASE_URL)

    if parsed.scheme not in ("https", "http") or not parsed.netloc:
        raise AIServiceError(
            "OLLAMA_BASE_URL is invalid. Use a complete server URL."
        )

    # Avoid sending prompts to an accidentally configured local endpoint
    # on a hosted deployment.
    if parsed.hostname in ("localhost", "127.0.0.1", "::1"):
        raise AIServiceError(
            "OLLAMA_BASE_URL points to localhost. Configure your "
            "reachable remote Ollama server instead."
        )

    if not OLLAMA_MODEL:
        raise AIServiceError("OLLAMA_MODEL is not configured.")

    return f"{OLLAMA_BASE_URL}/api/chat"


def ollama_headers():
    headers = {"Content-Type": "application/json"}

    if OLLAMA_API_KEY:
        headers["Authorization"] = f"Bearer {OLLAMA_API_KEY}"

    return headers


def normalize_history(history):
    """Keep only valid, recent user/assistant messages."""

    if not isinstance(history, list):
        return []

    messages = []

    for item in history[-MAX_HISTORY_MESSAGES:]:
        if not isinstance(item, dict):
            continue

        role = item.get("role")
        content = item.get("content", item.get("text", ""))

        # Support common frontend role names.
        if role == "assistant":
            role = "assistant"
        elif role in ("user",):
            role = "user"
        elif role in ("model",):
            role = "assistant"
        else:
            continue

        if not isinstance(content, str):
            continue

        content = content.strip()

        if content:
            messages.append({
                "role": role,
                "content": content[:MAX_PROMPT_LENGTH],
            })

    return messages


# --------------------------------------------------
# Ollama chat integration
# --------------------------------------------------


def ollama_chat(messages, max_output_tokens=1200):
    """
    Send a non-streaming chat request to remote Ollama.
    Return the assistant's text.
    """

    url = get_ollama_chat_url()

    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            *messages,
        ],
        "stream": False,
        "options": {
            "temperature": 0.5,
            "num_predict": max_output_tokens,
        },
    }

    try:
        response = requests.post(
            url,
            headers=ollama_headers(),
            json=payload,
            timeout=(OLLAMA_TIMEOUT_CONNECT, OLLAMA_TIMEOUT_READ),
        )

    except requests.exceptions.ConnectTimeout as exc:
        logger.warning("Ollama connection timed out.")
        raise AIServiceError(
            "Could not connect to the AI server in time. "
            "Check that the remote server is online."
        ) from exc

    except requests.exceptions.ReadTimeout as exc:
        logger.warning("Ollama response timed out.")
        raise AIServiceError(
            "The AI server took too long to respond. "
            "Try a shorter question or a faster model."
        ) from exc

    except requests.exceptions.SSLError as exc:
        logger.error("Ollama TLS connection failed: %s", exc)
        raise AIServiceError(
            "Secure connection to the AI server failed. "
            "Check its HTTPS certificate and server URL."
        ) from exc

    except requests.exceptions.RequestException as exc:
        logger.error("Ollama request failed: %s", exc)
        raise AIServiceError(
            "Unable to reach the AI server. Check its URL, network, "
            "and server status."
        ) from exc

    try:
        if response.status_code in (401, 403):
            raise AIServiceError(
                "The AI server rejected the request. Check its "
                "authentication configuration."
            )

        if response.status_code == 404:
            raise AIServiceError(
                "The Ollama endpoint or model was not found. "
                "Check OLLAMA_BASE_URL and OLLAMA_MODEL."
            )

        if response.status_code == 429:
            raise AIServiceError(
                "The AI server is busy or rate-limited. Please retry later."
            )

        if response.status_code >= 500:
            logger.error(
                "Ollama server error: HTTP %s",
                response.status_code,
            )
            raise AIServiceError(
                "The AI server is temporarily unavailable. Please retry."
            )

        if not response.ok:
            logger.warning(
                "Ollama returned HTTP %s: %s",
                response.status_code,
                response.text[:500],
            )
            raise AIServiceError(
                "The AI server rejected the request. Check the "
                "server configuration and model name."
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise AIServiceError(
                "The AI server returned an invalid response."
            ) from exc

        # Ollama /api/chat response structure:
        # {"message": {"role": "assistant", "content": "..."}}
        message = data.get("message", {})
        answer = message.get("content", "") if isinstance(message, dict) else ""

        if not isinstance(answer, str) or not answer.strip():
            logger.warning("Ollama returned an empty answer.")
            raise AIServiceError(
                "The AI server returned an empty answer. Please try again."
            )

        return answer.strip()

    finally:
        response.close()


def ask_ai(prompt, max_output_tokens=1200):
    """Convenience helper for single-prompt features."""

    if not isinstance(prompt, str) or not prompt.strip():
        raise AIServiceError("Please enter a question.")

    prompt = prompt.strip()[:MAX_PROMPT_LENGTH]

    return ollama_chat(
        [{"role": "user", "content": prompt}],
        max_output_tokens=max_output_tokens,
    )


# --------------------------------------------------
# Page routes
# --------------------------------------------------


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/assistant")
@app.route("/chat")
def assistant_page():
    return render_template("chat.html")


@app.route("/pdf-assistant")
@app.route("/pdf")
def pdf_assistant_page():
    return render_template("pdf_assistant.html")


@app.route("/quiz")
def quiz_page():
    return render_template("quiz.html")


@app.route("/planner")
def planner_page():
    return render_template("planner.html")


# --------------------------------------------------
# AI assistant API
# --------------------------------------------------


@app.route("/api/assistant", methods=["POST"])
def api_assistant():
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({"error": "Send a valid JSON request."}), 400

    question = data.get("question", data.get("message", ""))

    if not isinstance(question, str) or not question.strip():
        return jsonify({"error": "Please enter a question."}), 400

    if len(question) > MAX_PROMPT_LENGTH:
        return jsonify({
            "error": f"Your question is too long. Maximum: "
                     f"{MAX_PROMPT_LENGTH} characters."
        }), 400

    history = normalize_history(data.get("history", []))
    messages = history + [{
        "role": "user",
        "content": question.strip(),
    }]

    try:
        answer = ollama_chat(messages, max_output_tokens=1600)

        # Preserve the NDJSON format used by many streaming frontends.
        # This returns one complete response, not incremental token streaming.
        def generate():
            yield json.dumps(
                {"token": answer},
                ensure_ascii=False,
            ) + "\n"

        return Response(
            generate(),
            content_type="application/x-ndjson; charset=utf-8",
        )

    except AIServiceError as exc:
        logger.warning("Assistant request failed: %s", exc)
        return jsonify({"error": str(exc)}), 502

    except Exception:
        logger.exception("Unexpected assistant error.")
        return jsonify({
            "error": "An unexpected server error occurred. Please try again."
        }), 500


# --------------------------------------------------
# AI quiz API
# --------------------------------------------------


@app.route("/api/quiz", methods=["POST"])
def api_quiz():
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({"error": "Send a valid JSON request."}), 400

    topic = data.get("topic", "")

    if not isinstance(topic, str) or not topic.strip():
        return jsonify({"error": "Please enter a quiz topic."}), 400

    if len(topic) > 300:
        return jsonify({"error": "The topic is too long."}), 400

    prompt = f"""
Create a practice quiz about: {topic.strip()}

Generate 5 multiple-choice questions.
For each question, include:
- The question
- Four options labelled A, B, C, and D
- The correct answer
- A short explanation

Keep the questions clear and appropriate for a student.
Use a readable numbered format.
"""

    try:
        answer = ask_ai(prompt, max_output_tokens=1800)
        return jsonify({"answer": answer})

    except AIServiceError as exc:
        logger.warning("Quiz generation failed: %s", exc)
        return jsonify({"error": str(exc)}), 502

    except Exception:
        logger.exception("Unexpected quiz error.")
        return jsonify({"error": "Quiz generation failed."}), 500


# --------------------------------------------------
# AI study planner API
# --------------------------------------------------


@app.route("/api/study-plan", methods=["POST"])
def api_study_plan():
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({"error": "Send a valid JSON request."}), 400

    subjects = data.get("subjects", "")
    days = data.get("days", 7)
    hours = data.get("hours", 2)

    if isinstance(subjects, list):
        subjects = ", ".join(
            str(item).strip() for item in subjects if str(item).strip()
        )

    if not isinstance(subjects, str) or not subjects.strip():
        return jsonify({"error": "Please enter your subjects."}), 400

    try:
        days = int(days)
        hours = float(hours)
    except (ValueError, TypeError):
        return jsonify({
            "error": "Days and study hours must be valid numbers."
        }), 400

    if not 1 <= days <= 90:
        return jsonify({"error": "Days must be between 1 and 90."}), 400

    if not 0.5 <= hours <= 16:
        return jsonify({
            "error": "Daily study hours must be between 0.5 and 16."
        }), 400

    prompt = f"""
Create a practical study plan for a student.

Subjects: {subjects[:3000]}
Duration: {days} days
Available study time: {hours:g} hours per day

Include:
1. A day-by-day schedule
2. Time allocation for each subject
3. Short breaks and revision
4. Practice questions or project work where appropriate
5. A final revision plan

Make the plan realistic and easy to follow.
"""

    try:
        plan = ask_ai(prompt, max_output_tokens=2000)
        return jsonify({"plan": plan})

    except AIServiceError as exc:
        logger.warning("Study plan generation failed: %s", exc)
        return jsonify({"error": str(exc)}), 502

    except Exception:
        logger.exception("Unexpected study planner error.")
        return jsonify({"error": "Study plan generation failed."}), 500


# --------------------------------------------------
# PDF assistant API
# --------------------------------------------------


@app.route("/api/pdf-assignment", methods=["POST"])
def api_pdf_assignment():
    uploaded_file = request.files.get("pdf")

    if uploaded_file is None or not uploaded_file.filename:
        return jsonify({
            "error": "Please choose a PDF file to upload."
        }), 400

    if not uploaded_file.filename.lower().endswith(".pdf"):
        return jsonify({
            "error": "Only PDF files are supported."
        }), 400

    try:
        reader = PdfReader(uploaded_file.stream)

        if reader.is_encrypted:
            try:
                decrypted = reader.decrypt("")
            except Exception:
                decrypted = 0

            if not decrypted:
                return jsonify({
                    "error": "This PDF is password-protected. "
                             "Please upload an unlocked PDF."
                }), 400

        extracted_pages = []

        for page in reader.pages:
            try:
                page_text = page.extract_text() or ""
                if page_text:
                    extracted_pages.append(page_text)
            except Exception:
                logger.warning("Could not extract text from a PDF page.")

        pdf_text = "\n".join(extracted_pages).strip()

        if not pdf_text:
            return jsonify({
                "error": "No readable text was found. The PDF may contain "
                         "scanned images instead of selectable text."
            }), 400

        pdf_text = pdf_text[:MAX_PDF_TEXT_LENGTH]

    except Exception:
        logger.exception("PDF reading failed.")
        return jsonify({
            "error": "Unable to read this PDF. Try another valid PDF file."
        }), 400

    instruction = request.form.get(
        "question",
        "Summarize this document and explain its important points.",
    )

    if not isinstance(instruction, str) or not instruction.strip():
        instruction = (
            "Summarize this document and explain its important points."
        )

    instruction = instruction.strip()[:2000]

    prompt = f"""
A student has uploaded a PDF document.

Student request:
{instruction}

Document text:
--- DOCUMENT START ---
{pdf_text}
--- DOCUMENT END ---

Answer the student's request using the document as your source.
Explain important points clearly. If the document does not contain
the information requested, say so instead of inventing details.
"""

    try:
        answer = ask_ai(prompt, max_output_tokens=2000)
        return jsonify({"answer": answer})

    except AIServiceError as exc:
        logger.warning("PDF assistant request failed: %s", exc)
        return jsonify({"error": str(exc)}), 502

    except Exception:
        logger.exception("Unexpected PDF assistant error.")
        return jsonify({"error": "PDF processing failed."}), 500


# --------------------------------------------------
# Health and deployment diagnostics
# --------------------------------------------------


@app.route("/health")
def health():
    # This checks application configuration only.
    # It does not prove the remote Ollama server is reachable.
    configured = bool(OLLAMA_BASE_URL and OLLAMA_MODEL)

    return jsonify({
        "status": "ok",
        "ai_configured": configured,
        "model": OLLAMA_MODEL if configured else None,
    })


@app.errorhandler(RequestEntityTooLarge)
def handle_large_upload(_error):
    return jsonify({
        "error": "The upload is too large. Maximum file size is 15 MB."
    }), 413


@app.errorhandler(404)
def handle_not_found(_error):
    if request.path.startswith("/api/"):
        return jsonify({"error": "API endpoint not found."}), 404

    return "Page not found", 404


@app.errorhandler(500)
def handle_server_error(_error):
    logger.exception("Unhandled Flask server error.")
    if request.path.startswith("/api/"):
        return jsonify({"error": "Internal server error."}), 500

    return "An internal server error occurred.", 500


# --------------------------------------------------
# Local development and Render startup
# --------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
    )
