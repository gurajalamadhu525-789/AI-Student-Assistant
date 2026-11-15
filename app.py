import json
import os
import time
import traceback

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

# ── Google Gemini configuration ───────────────────────────────────────────────
GEMINI_API_KEY  = os.getenv("GEMINI_API_KEY", "")

GEMINI_MODEL    = "gemini-3.8-flash"

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"


def _gemini_url(model, endpoint="generateContent"):
    if not GEMINI_API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY environment variable is not set. "
            "Add it to your deployment environment."
        )
    return f"{GEMINI_BASE_URL}/{model}:{endpoint}?key={GEMINI_API_KEY}"


def _to_gemini_contents(messages):
    """Convert OpenAI-style messages list to Gemini contents format."""
    system_text = ""
    contents = []
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content", "")
        if role == "system":
            system_text = content
        elif role == "user":
            text = (system_text + "\n\n" + content).strip() if system_text else content
            contents.append({"role": "user", "parts": [{"text": text}]})
            system_text = ""
        elif role == "assistant":
            contents.append({"role": "model", "parts": [{"text": content}]})
    return contents


def gemini_generate(messages, timeout=30, max_tokens=1500):
    """Gemini call using gemini-3.8-flash with fast recovery on temporary spikes."""
    if not GEMINI_API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY environment variable is not set. "
            "Add it to your deployment environment."
        )

    url = f"{GEMINI_BASE_URL}/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"

    payload = {
        "contents": _to_gemini_contents(messages),
        "generationConfig": {
            "maxOutputTokens": max_tokens,
            "temperature": 0.7,
        },
    }

    last_error = None
    for attempt in range(2):
        try:
            response = requests.post(
                url,
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=timeout,
            )

            if response.status_code in (429, 503):
                time.sleep(1.0)
                continue

            response.raise_for_status()
            data = response.json()
            try:
                return data["candidates"][0]["content"]["parts"][0]["text"].strip()
            except (KeyError, IndexError, TypeError) as exc:
                raise RuntimeError(f"Unexpected response format: {data}") from exc

        except requests.exceptions.HTTPError as err:
            last_error = err
            if response.status_code in (429, 503):
                time.sleep(1.0)
                continue
            raise
        except Exception as err:
            last_error = err
            break

    if last_error:
        raise last_error
    raise RuntimeError("The AI server is experiencing temporary traffic. Please try again in a moment.")


def gemini_error_message(error):
    if isinstance(error, RuntimeError):
        return str(error)
    if isinstance(error, requests.exceptions.ConnectionError):
        return "Cannot connect to the AI server. Please try again."
    if isinstance(error, requests.exceptions.Timeout):
        return "The AI server took too long to respond. Please try again."
    if isinstance(error, requests.exceptions.HTTPError):
        status = (
            error.response.status_code
            if error.response is not None
            else "unknown"
        )
        body = {}
        try:
            body = error.response.json()
        except Exception:
            pass
        msg = body.get("error", {}).get("message", "")
        return f"AI error {status}: {msg}" if msg else f"AI error {status}."
    if isinstance(error, requests.exceptions.RequestException):
        return f"Could not contact the AI server: {error}"
    return str(error)


# Aliases so the rest of the routes work without changes
def openai_generate(messages, timeout=180, max_tokens=1500):   # noqa: F811
    return gemini_generate(messages, timeout=timeout, max_tokens=max_tokens)


def openai_error_message(error):                               # noqa: F811
    return gemini_error_message(error)


def ollama_error_message(error):                               # noqa: F811
    return gemini_error_message(error)


@app.route("/api/debug-gemini")
def debug_gemini():
    url = f"{GEMINI_BASE_URL}/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    payloads = [
        ("standard", {"contents": [{"role": "user", "parts": [{"text": "hi"}]}]}),
        ("no_thinking", {
            "contents": [{"role": "user", "parts": [{"text": "hi"}]}],
            "generationConfig": {"thinkingConfig": {"thinkingBudget": 0}},
        }),
    ]
    results = {}
    for name, p in payloads:
        try:
            t0 = time.time()
            r = requests.post(url, json=p, timeout=15)
            elapsed = round(time.time() - t0, 2)
            results[name] = {
                "status": r.status_code,
                "elapsed": elapsed,
                "data": r.json() if r.status_code == 200 else r.text[:200],
            }
        except Exception as e:
            results[name] = {"error": str(e)}
    return jsonify(results)


@app.route("/api/test-ai")
def test_ai():
    try:
        ans = gemini_generate([{"role": "user", "content": "say hello"}])
        return jsonify({"success": True, "answer": ans})
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
        })


@app.route("/api/models")
def list_models():
    if not GEMINI_API_KEY:
        return jsonify({"error": "No GEMINI_API_KEY set"}), 500
    try:
        resp = requests.get(
            f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_API_KEY}",
            timeout=15,
        )
        data = resp.json()
        models = [
            m.get("name", "").replace("models/", "")
            for m in data.get("models", [])
            if "generateContent" in m.get("supportedGenerationMethods", [])
        ]
        return jsonify({"supported_models": models, "raw": data})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------- HOME PAGE ----------------

@app.route("/")
def home():
    return render_template("app.html", page="home")


# ---------------- ASSISTANT / CHAT PAGE ----------------

@app.route("/assistant")
@app.route("/chat")
def assistant_page():
    return render_template("app.html", page="assistant")


# ---------------- PDF ASSISTANT PAGE ----------------

@app.route("/pdf-assistant")
@app.route("/pdf")
def pdf_assistant_page():
    return render_template("app.html", page="pdf")


# ---------------- QUIZ PAGE ----------------

@app.route("/quiz")
def quiz_page():
    return render_template("app.html", page="quiz")


# ---------------- STUDY PLANNER PAGE ----------------

@app.route("/planner")
def planner_page():
    return render_template("app.html", page="planner")


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

    bot = str(data.get("bot", "general")).strip().lower()

    BOT_PERSONAS = {
        "general": (
            "You are StudyAI General Tutor, a friendly, patient, and knowledgeable academic partner for college students. "
            "Explain concepts clearly using simple, engaging English and relatable analogies. "
            "Break down difficult topics step by step using markdown formatting. "
            "Be encouraging and direct. If unsure, clearly say so."
        ),
        "coder": (
            "You are StudyAI Code Mentor, an elite software engineering tutor. "
            "Help students write, debug, and understand code in Python, C++, Java, JavaScript, SQL, and other languages. "
            "Always provide clean, correct, well-commented, and runnable code formatted in markdown code blocks with language tags. "
            "Explain the logic step by step, diagnose errors clearly, and mention time/space complexity (Big-O) when helpful."
        ),
        "math": (
            "You are StudyAI Math & Science Solver, an expert in Mathematics, Physics, Chemistry, and Engineering. "
            "Break down problems step by step with clear reasoning and derivations. "
            "Show every formula used, substitution step, and units. Highlight final answers clearly. "
            "Explain the intuition and principles behind the math so the student truly understands."
        ),
        "writer": (
            "You are StudyAI Essay & Writing Coach, an expert academic editor and writing mentor. "
            "Help students outline essays, sharpen thesis statements, improve vocabulary, and fix grammar. "
            "Suggest stronger sentence structures and formal academic transitions. "
            "Provide concrete before/after rewrite examples alongside your suggestions."
        ),
        "exam": (
            "You are StudyAI Exam & Revision Coach, focused on high-yield, memory-retentive exam prep. "
            "Provide high-impact summaries, bullet points, key definitions, and memory mnemonics. "
            "Point out common exam traps, frequently tested questions, and end with 2 quick test-yourself questions."
        ),
    }

    system_message = BOT_PERSONAS.get(bot, BOT_PERSONAS["general"])

    messages = [{"role": "system", "content": system_message}]

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
            messages.append({"role": role, "content": content.strip()})

    messages.append({"role": "user", "content": question})

    # ── Gemini (simple & reliable) ───────────────────────────────────
    try:
        answer = gemini_generate(messages, timeout=120, max_tokens=800)
    except RuntimeError as error:
        return jsonify({"error": str(error)}), 502
    except Exception as error:
        return jsonify({"error": gemini_error_message(error)}), 502

    line = json.dumps({"token": answer}, ensure_ascii=False) + "\n"
    return Response(
        line,
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
        answer = gemini_generate(
            [{"role": "user", "content": prompt}],
            timeout=60,
            max_tokens=800,
        )
        return jsonify({"answer": answer})

    except Exception as error:
        app.logger.exception("Quiz API error")
        return jsonify({"error": gemini_error_message(error)}), 502


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
        plan = gemini_generate(
            [{"role": "user", "content": prompt}],
            timeout=60,
            max_tokens=1000,
        )
        return jsonify({"plan": plan})

    except Exception as error:
        app.logger.exception("Study planner API error")
        return jsonify({"error": gemini_error_message(error)}), 502


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

        answer = gemini_generate(
            [{"role": "user", "content": prompt}],
            timeout=90,
            max_tokens=1200,
        )

        return jsonify({"answer": answer})

    except Exception as error:
        app.logger.exception("PDF assistant error")
        return jsonify({"error": gemini_error_message(error)}), 502


# ---------------- ERROR HANDLERS ----------------

@app.errorhandler(413)
def file_too_large(_error):
    return jsonify({
        "error": "The PDF is too large. Maximum file size is 15 MB."
    }), 413


@app.errorhandler(Exception)
def handle_any_exception(e):
    app.logger.exception("Unhandled server error")
    return jsonify({
        "error": str(e),
        "traceback": traceback.format_exc(),
    }), 500


# ---------------- START FLASK SERVER ----------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5002"))

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        threaded=True,
    )