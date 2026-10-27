import json
import os

import requests
from flask import (
    Flask,
    Response,
    jsonify,
    render_template,
    request,
    stream_with_context,
)
from pypdf import PdfReader

app = Flask(__name__, template_folder="templates")
app.config["MAX_CONTENT_LENGTH"] = 15 * 1024 * 1024

# Ollama configuration
OLLAMA_BASE_URL = os.getenv(
    "OLLAMA_BASE_URL", "http://localhost:11434"
).rstrip("/")

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:latest")

OLLAMA_GENERATE_URL = f"{OLLAMA_BASE_URL}/api/generate"
OLLAMA_CHAT_URL = f"{OLLAMA_BASE_URL}/api/chat"


def ollama_generate(prompt, timeout=180):
    response = requests.post(
        OLLAMA_GENERATE_URL,
        json={
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
        },
        timeout=timeout,
    )
    response.raise_for_status()

    answer = response.json().get("response", "").strip()

    if not answer:
        raise RuntimeError("Ollama returned an empty response.")

    return answer


def ollama_error_message(error):
    if isinstance(error, requests.exceptions.ConnectionError):
        return (
            "Cannot connect to Ollama. Check that Ollama is running "
            "and OLLAMA_BASE_URL is correct."
        )

    if isinstance(error, requests.exceptions.Timeout):
        return "Ollama took too long to respond. Please try again."

    if isinstance(error, requests.exceptions.HTTPError):
        status = (
            error.response.status_code
            if error.response is not None
            else "unknown"
        )
        return f"Ollama returned HTTP {status}. Check the URL and model."

    if isinstance(error, requests.exceptions.RequestException):
        return f"Could not contact Ollama: {error}"

    return str(error)


# ---------------- HOME PAGE ----------------

@app.route("/")
def home():
    return render_template("index.html")


# ---------------- ASSISTANT PAGE ----------------

@app.route("/assistant")
def assistant_page():
    return render_template("chat.html")


@app.route("/chat")
def chat_page():
    return render_template("chat.html")


# ---------------- PDF ASSISTANT PAGE ----------------

@app.route("/pdf-assistant")
def pdf_assistant_page():
    return render_template("pdf_assistant.html")


@app.route("/pdf")
def pdf_page():
    return render_template("pdf_assistant.html")


# ---------------- QUIZ PAGE ----------------

@app.route("/quiz")
def quiz_page():
    return render_template("quiz.html")


# ---------------- STUDY PLANNER PAGE ----------------

@app.route("/planner")
def planner_page():
    return render_template("planner.html")


# ---------------- AI ASSISTANT API ----------------

@app.route("/api/assistant", methods=["POST"])
def api_assistant():
    data = request.get_json(silent=True) or {}
    question = str(data.get("question", "")).strip()

    if not question:
        return jsonify({"error": "Please enter a question."}), 400

    history = data.get("history", [])

    if not isinstance(history, list):
        history = []

    system_message = """
You are an intelligent AI Student Assistant.
Answer directly using natural, friendly, simple English.
Understand follow-up questions using conversation history.
Explain difficult topics step by step.
Give examples when useful.
For coding questions, provide practical and correct code.
Keep simple answers short and provide details when requested.
If unsure, clearly say so.
Do not claim you searched the web unless you actually did.
"""

    messages = [
        {"role": "system", "content": system_message}
    ]

    for item in history[-20:]:
        if not isinstance(item, dict):
            continue

        role = item.get("role")
        content = item.get("content", "")

        if (
            role in ("user", "assistant")
            and isinstance(content, str)
            and content.strip()
        ):
            messages.append({
                "role": role,
                "content": content.strip(),
            })

    messages.append({
        "role": "user",
        "content": question,
    })

    try:
        ollama_response = requests.post(
            OLLAMA_CHAT_URL,
            json={
                "model": OLLAMA_MODEL,
                "messages": messages,
                "stream": True,
                "options": {
                    "temperature": 0.7,
                    "num_predict": 600,
                },
            },
            stream=True,
            timeout=(10, 300),
        )

        ollama_response.raise_for_status()

    except requests.exceptions.RequestException as error:
        return jsonify({
            "error": ollama_error_message(error)
        }), 502

    @stream_with_context
    def stream_tokens():
        try:
            for line in ollama_response.iter_lines(
                decode_unicode=True
            ):
                if not line:
                    continue

                try:
                    chunk = json.loads(line)
                except (json.JSONDecodeError, TypeError):
                    continue

                token = chunk.get("message", {}).get(
                    "content", ""
                )

                if token:
                    yield (
                        json.dumps(
                            {"token": token},
                            ensure_ascii=False,
                        ) + "\n"
                    )

                if chunk.get("done") is True:
                    break

        except GeneratorExit:
            pass

        except Exception as error:
            yield json.dumps({
                "error": str(error)
            }, ensure_ascii=False) + "\n"

        finally:
            ollama_response.close()

    return Response(
        stream_tokens(),
        mimetype="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------- QUIZ API ----------------

@app.route("/api/quiz", methods=["POST"])
def api_quiz():
    data = request.get_json(silent=True) or {}
    topic = str(data.get("topic", "")).strip()

    if not topic:
        return jsonify({"error": "Please enter a topic."}), 400

    prompt = f"""
Create a quiz about: {topic}

Generate exactly 5 multiple-choice questions.
For each question include:
1. The question
2. Four options labelled A, B, C and D
3. The correct answer
4. A short explanation

Keep it simple and useful for a college student.
Format the answer clearly.
"""

    try:
        answer = ollama_generate(prompt, timeout=150)
        return jsonify({"answer": answer})

    except Exception as error:
        app.logger.exception("Quiz API error")
        return jsonify({
            "error": ollama_error_message(error)
        }), 502


# ---------------- STUDY PLANNER API ----------------

@app.route("/api/study-plan", methods=["POST"])
def study_plan():
    data = request.get_json(silent=True) or {}

    subjects = str(data.get("subjects", "")).strip()
    days = data.get("days", "")
    hours = data.get("hours", "")
    level = str(data.get("level", "Beginner")).strip()
    exam = str(data.get("exam", "Regular Study")).strip()

    if not subjects:
        return jsonify({
            "error": "Please enter your subjects."
        }), 400

    if not str(days).strip():
        return jsonify({
            "error": "Please enter the number of days."
        }), 400

    if not str(hours).strip():
        return jsonify({
            "error": "Please enter study hours per day."
        }), 400

    prompt = f"""
Create a realistic and balanced study plan for a college student.

Subjects: {subjects}
Number of days: {days}
Study hours per day: {hours}
Student level: {level}
Exam type: {exam}

Include:
1. A day-by-day timetable
2. Subjects and important topics
3. Study time
4. Practice questions
5. Revision and short breaks
6. Final revision
7. Exam preparation tips

Use simple English.
"""

    try:
        plan = ollama_generate(prompt, timeout=150)
        return jsonify({"plan": plan})

    except Exception as error:
        app.logger.exception("Study planner API error")
        return jsonify({
            "error": ollama_error_message(error)
        }), 502


# ---------------- PDF ASSIGNMENT API ----------------

@app.route("/api/pdf-assignment", methods=["POST"])
def pdf_assignment():
    if "pdf" not in request.files:
        return jsonify({
            "error": "Please upload a PDF file."
        }), 400

    pdf_file = request.files["pdf"]

    if not pdf_file.filename:
        return jsonify({
            "error": "Please select a PDF file."
        }), 400

    if not pdf_file.filename.lower().endswith(".pdf"):
        return jsonify({
            "error": "Please upload a PDF file only."
        }), 400

    question = request.form.get("question", "").strip()

    try:
        reader = PdfReader(pdf_file)
        extracted_pages = []

        for page in reader.pages:
            page_text = page.extract_text() or ""

            if page_text:
                extracted_pages.append(page_text)

        pdf_text = "\n".join(extracted_pages).strip()

        if not pdf_text:
            return jsonify({
                "error": (
                    "Could not extract text from this PDF. "
                    "It may be a scanned PDF containing images."
                )
            }), 400

        pdf_text = pdf_text[:30000]

        user_request = question or (
            "Create an assignment and study guide from this material."
        )

        prompt = f"""
You are an AI Student Assistant.
Use ONLY the PDF material below as the source.

User request: {user_request}

Include when suitable:
1. A suitable title and introduction
2. Important questions
3. Five short-answer questions
4. Five long-answer questions
5. Five multiple-choice questions with answers
6. Important topics
7. A simple summary
8. Five study tips

Answer specific questions using the PDF content.
Do not add unrelated information.

PDF CONTENT:
-------------------------
{pdf_text}
-------------------------
"""

        answer = ollama_generate(prompt, timeout=240)

        return jsonify({"answer": answer})

    except Exception as error:
        app.logger.exception("PDF assistant error")
        return jsonify({
            "error": ollama_error_message(error)
        }), 502


# ---------------- FILE SIZE ERROR ----------------

@app.errorhandler(413)
def file_too_large(_error):
    return jsonify({
        "error": "The PDF is too large. Maximum file size is 15 MB."
    }), 413


# ---------------- START FLASK SERVER ----------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5002"))

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        threaded=True,
    )