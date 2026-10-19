
import os
import json
import logging
from urllib.parse import urlparse

import requests
from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    Response,
)
from pypdf import PdfReader
from werkzeug.exceptions import RequestEntityTooLarge

app = Flask(__name__, template_folder="templates")
app.config["MAX_CONTENT_LENGTH"] = 15 * 1024 * 1024

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

# Ollama configuration
OLLAMA_BASE_URL = os.getenv(
    "OLLAMA_BASE_URL", ""
).strip().rstrip("/")

OLLAMA_MODEL = os.getenv(
    "OLLAMA_MODEL", "qwen3:0.6b"
).strip()

OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "").strip()

CONNECT_TIMEOUT = 10
READ_TIMEOUT = 180
MAX_HISTORY_MESSAGES = 12
MAX_PROMPT_LENGTH = 12000
MAX_PDF_TEXT_LENGTH = 30000

SYSTEM_PROMPT = """
You are an AI Student Assistant, similar to a helpful coding tutor.

Help students with:
- Python and other programming languages
- College subjects and concepts
- Coding errors and debugging
- Interview preparation
- Projects and study planning

Give clear, direct answers. Start with the answer, then explain
important details. Use short examples when helpful. For simple
questions, keep answers short. For complex questions, explain
step by step. Ask a clarifying question when necessary.
Do not invent facts when you are unsure.
"""


class AIServiceError(Exception):
    """An expected error communicating with the AI service."""


def get_ollama_chat_url():
    if not OLLAMA_BASE_URL:
        raise AIServiceError(
            "AI is not configured. Set OLLAMA_BASE_URL."
        )

    parsed = urlparse(OLLAMA_BASE_URL)

    if parsed.scheme not in ("https", "http") or not parsed.netloc:
        raise AIServiceError(
            "OLLAMA_BASE_URL must be a valid HTTP or HTTPS URL."
        )

    if parsed.hostname in ("localhost", "127.0.0.1", "::1"):
        raise AIServiceError(
            "The configured Ollama URL points to localhost. "
            "Use a reachable Ollama server URL."
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
    if not isinstance(history, list):
        return []

    messages = []

    for item in history[-MAX_HISTORY_MESSAGES:]:
        if not isinstance(item, dict):
            continue

        role = item.get("role")
        content = item.get("content", item.get("text", ""))

        if role == "model":
            role = "assistant"

        if role not in ("user", "assistant"):
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


def build_payload(messages, max_output_tokens=500, stream=False):
    return {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            *messages,
        ],
        "stream": stream,
        "keep_alive": "10m",
        "think": False,
        "options": {
            "temperature": 0.5,
            "num_predict": max_output_tokens,
        },
    }


def ollama_chat(messages, max_output_tokens=1200):
    """Generate a complete answer for quiz, PDF and planner APIs."""

    url = get_ollama_chat_url()

    try:
        with requests.post(
            url,
            headers=ollama_headers(),
            json=build_payload(
                messages,
                max_output_tokens=max_output_tokens,
                stream=False,
            ),
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
        ) as response:

            if response.status_code in (401, 403):
                raise AIServiceError(
                    "The AI server rejected the request. "
                    "Check its authentication settings."
                )

            if response.status_code == 404:
                raise AIServiceError(
                    "Ollama endpoint or model not found. "
                    "Check OLLAMA_BASE_URL and OLLAMA_MODEL."
                )

            if response.status_code == 429:
                raise AIServiceError(
                    "The AI server is busy. Please try again."
                )

            if not response.ok:
                logger.error(
                    "Ollama returned HTTP %s: %s",
                    response.status_code,
                    response.text[:300],
                )
                raise AIServiceError(
                    f"The AI server returned HTTP {response.status_code}."
                )

            try:
                data = response.json()
            except ValueError as exc:
                raise AIServiceError(
                    "The AI server returned invalid JSON."
                ) from exc

            if data.get("error"):
                raise AIServiceError(str(data["error"]))

            message = data.get("message", {})
            answer = (
                message.get("content", "")
                if isinstance(message, dict)
                else ""
            )

            if not isinstance(answer, str) or not answer.strip():
                raise AIServiceError(
                    "The AI returned an empty answer. Please try again."
                )

            return answer.strip()

    except AIServiceError:
        raise

    except requests.exceptions.Timeout as exc:
        raise AIServiceError(
            "The AI took too long to respond. Please try again."
        ) from exc

    except requests.exceptions.RequestException as exc:
        logger.warning("Ollama request failed: %s", exc)
        raise AIServiceError(
            "Cannot reach the AI server. Check Ollama and the tunnel."
        ) from exc


def ask_ai(prompt, max_output_tokens=1200):
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
    # Preserve support for either existing PDF template.
    try:
        return render_template("pdf_assistant.html")
    except Exception:
        return render_template("pdf.html")


@app.route("/quiz")
def quiz_page():
    return render_template("quiz.html")


@app.route("/planner")
def planner_page():
    return render_template("planner.html")


# --------------------------------------------------
# Streaming AI chat API
# --------------------------------------------------

@app.route("/api/assistant", methods=["POST"])
def api_assistant():
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({"error": "Send a valid JSON request."}), 400

    question = data.get("question", data.get("message", ""))

    if not isinstance(question, str) or not question.strip():
        return jsonify({"error": "Please enter a question."}), 400

    question = question.strip()

    if len(question) > MAX_PROMPT_LENGTH:
        return jsonify({"error": "Your question is too long."}), 400

    history = normalize_history(data.get("history", []))
    messages = history + [{"role": "user", "content": question}]

    try:
        url = get_ollama_chat_url()

        upstream = requests.post(
            url,
            headers=ollama_headers(),
            json=build_payload(
                messages,
                max_output_tokens=500,
                stream=True,
            ),
            stream=True,
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
        )

        if not upstream.ok:
            status = upstream.status_code
            details = upstream.text[:300]
            upstream.close()

            logger.error(
                "Ollama streaming returned HTTP %s: %s",
                status,
                details,
            )

            return jsonify({
                "error": f"The AI server returned HTTP {status}."
            }), 502

    except AIServiceError as exc:
        return jsonify({"error": str(exc)}), 502

    except requests.exceptions.RequestException as exc:
        logger.warning("Could not start AI stream: %s", exc)
        return jsonify({
            "error": "Could not connect to the AI server."
        }), 502

    def generate():
        try:
            for line in upstream.iter_lines():
                if not line:
                    continue

                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if item.get("error"):
                    yield json.dumps({
                        "error": str(item["error"])
                    }) + "\n"
                    break

                message = item.get("message", {})
                token = (
                    message.get("content", "")
                    if isinstance(message, dict)
                    else ""
                )

                if token:
                    yield json.dumps(
                        {"token": token},
                        ensure_ascii=False,
                    ) + "\n"

                if item.get("done"):
                    break

        except requests.exceptions.RequestException:
            logger.exception("AI stream was interrupted.")
            yield json.dumps({
                "error": "The AI connection was interrupted."
            }) + "\n"

        finally:
            upstream.close()

    return Response(
        generate(),
        content_type="application/x-ndjson; charset=utf-8",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


# --------------------------------------------------
# Quiz API
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

Generate 5 multiple-choice questions. For each question include:
- The question
- Four options labelled A, B, C, and D
- The correct answer
- A short explanation

Keep the questions clear and appropriate for a student.
"""

    try:
        return jsonify({
            "answer": ask_ai(prompt, max_output_tokens=1800)
        })
    except AIServiceError as exc:
        logger.warning("Quiz generation failed: %s", exc)
        return jsonify({"error": str(exc)}), 502


# --------------------------------------------------
# Study planner API
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
            str(item).strip()
            for item in subjects
            if str(item).strip()
        )

    if not isinstance(subjects, str) or not subjects.strip():
        return jsonify({"error": "Please enter your subjects."}), 400

    try:
        days = int(days)
        hours = float(hours)
    except (ValueError, TypeError):
        return jsonify({
            "error": "Days and study hours must be numbers."
        }), 400

    if not 1 <= days <= 90:
        return jsonify({"error": "Days must be between 1 and 90."}), 400

    if not 0.5 <= hours <= 16:
        return jsonify({
            "error": "Study hours must be between 0.5 and 16."
        }), 400

    prompt = f"""
Create a practical study plan.

Subjects: {subjects[:3000]}
Duration: {days} days
Available study time: {hours:g} hours per day

Include a day-by-day schedule, subject time allocation, short breaks,
revision, practice, and a final review. Keep it realistic.
"""

    try:
        return jsonify({
            "plan": ask_ai(prompt, max_output_tokens=2000)
        })
    except AIServiceError as exc:
        logger.warning("Study planner failed: %s", exc)
        return jsonify({"error": str(exc)}), 502


# --------------------------------------------------
# PDF assistant API
# --------------------------------------------------

@app.route("/api/pdf-assignment", methods=["POST"])
def api_pdf_assignment():
    uploaded_file = request.files.get("pdf")

    if uploaded_file is None or not uploaded_file.filename:
        return jsonify({"error": "Please choose a PDF file."}), 400

    if not uploaded_file.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Only PDF files are supported."}), 400

    try:
        reader = PdfReader(uploaded_file.stream)

        if reader.is_encrypted:
            try:
                decrypted = reader.decrypt("")
            except Exception:
                decrypted = 0

            if not decrypted:
                return jsonify({
                    "error": "This PDF is password-protected."
                }), 400

        pages = []

        for page in reader.pages:
            try:
                text = page.extract_text() or ""
                if text:
                    pages.append(text)
            except Exception:
                logger.warning("Could not extract a PDF page.")

        pdf_text = "\n".join(pages).strip()

        if not pdf_text:
            return jsonify({
                "error": "No readable text was found in this PDF."
            }), 400

        pdf_text = pdf_text[:MAX_PDF_TEXT_LENGTH]

    except Exception:
        logger.exception("PDF reading failed.")
        return jsonify({
            "error": "Unable to read this PDF. Try another PDF."
        }), 400

    instruction = request.form.get(
        "question",
        "Summarize this document and explain its important points.",
    )

    if not isinstance(instruction, str) or not instruction.strip():
        instruction = (
            "Summarize this document and explain its important points."
        )

    prompt = f"""
Student request:
{instruction.strip()[:2000]}

Document text:
--- DOCUMENT START ---
{pdf_text}
--- DOCUMENT END ---

Answer using the document as your source. Explain clearly and do not
invent information that is not in the document.
"""

    try:
        return jsonify({
            "answer": ask_ai(prompt, max_output_tokens=2000)
        })
    except AIServiceError as exc:
        logger.warning("PDF assistant failed: %s", exc)
        return jsonify({"error": str(exc)}), 502


# --------------------------------------------------
# Health and error handlers
# --------------------------------------------------

@app.route("/health")
def health():
    configured = bool(OLLAMA_BASE_URL and OLLAMA_MODEL)

    return jsonify({
        "status": "ok",
        "ai_configured": configured,
        "model": OLLAMA_MODEL if configured else None,
    })


@app.errorhandler(RequestEntityTooLarge)
def handle_large_upload(_error):
    return jsonify({
        "error": "Upload too large. Maximum size is 15 MB."
    }), 413


@app.errorhandler(404)
def handle_not_found(_error):
    if request.path.startswith("/api/"):
        return jsonify({"error": "API endpoint not found."}), 404
    return "Page not found", 404


@app.errorhandler(500)
def handle_server_error(error):
    logger.error("Unhandled Flask error: %s", error)

    if request.path.startswith("/api/"):
        return jsonify({"error": "Internal server error."}), 500

    return "An internal server error occurred.", 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False)
