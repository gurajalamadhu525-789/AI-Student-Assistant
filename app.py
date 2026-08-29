from flask import Flask, render_template, request, jsonify, Response, stream_with_context
import requests
import json
from pypdf import PdfReader

app = Flask(__name__, template_folder="templates")


# =====================================================
# OLLAMA SETTINGS
# =====================================================

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"

# Your installed model
OLLAMA_MODEL = "llama3.2:latest"


# =====================================================
# HOME PAGE
# =====================================================

@app.route("/")
def home():
    return render_template("index.html")


# =====================================================
# AI ASSISTANT PAGE
# =====================================================

@app.route("/assistant")
def assistant_page():
    return render_template("chat.html")


@app.route("/chat")
def chat_page():
    return render_template("chat.html")


# =====================================================
# PDF ASSISTANT PAGE
# =====================================================

@app.route("/pdf-assistant")
def pdf_assistant_page():
    return render_template("pdf_assistant.html")


@app.route("/pdf")
def pdf_page():
    return render_template("pdf_assistant.html")


# =====================================================
# QUIZ PAGE
# =====================================================

@app.route("/quiz")
def quiz_page():
    return render_template("quiz.html")


# =====================================================
# STUDY PLANNER PAGE
# =====================================================

@app.route("/planner")
def planner_page():
    return render_template("planner.html")


# =====================================================
# AI ASSISTANT API
# FAST CHATGPT-STYLE STREAMING
# =====================================================

@app.route("/api/assistant", methods=["POST"])
def api_assistant():

    try:

        data = request.get_json(silent=True)

        if not data:
            return jsonify({
                "error": "No data received."
            }), 400


        question = str(
            data.get("question", "")
        ).strip()


        if not question:
            return jsonify({
                "error": "Please enter a question."
            }), 400


        # =================================================
        # CONVERSATION HISTORY
        # =================================================

        history = data.get("history", [])

        if not isinstance(history, list):
            history = []


        # =================================================
        # SYSTEM MESSAGE
        # Keep this shorter for faster responses
        # =================================================

        system_message = """
You are a helpful AI Student Assistant.

Help students with programming, CSE subjects, DBMS,
Operating Systems, Software Engineering, mathematics,
projects and exam preparation.

Rules:
- Answer directly and naturally.
- Understand previous conversation context.
- Keep simple answers short.
- Explain difficult topics step by step.
- Use examples when useful.
- Use headings and bullet points when helpful.
- For programming questions, provide correct working code.
- Use simple English.
- Do not repeat unnecessary information.
"""


        messages = [
            {
                "role": "system",
                "content": system_message
            }
        ]


        # =================================================
        # ADD ONLY RECENT HISTORY
        # Smaller history = faster response
        # =================================================

        recent_history = history[-10:]


        for item in recent_history:

            if not isinstance(item, dict):
                continue


            role = item.get("role")
            content = str(
                item.get("content", "")
            ).strip()


            if role in ["user", "assistant"] and content:

                messages.append({
                    "role": role,
                    "content": content
                })


        # =================================================
        # ADD CURRENT QUESTION
        # =================================================

        messages.append({
            "role": "user",
            "content": question
        })


        # =================================================
        # CONNECT TO OLLAMA
        # =================================================

        try:

            ollama_response = requests.post(

                OLLAMA_CHAT_URL,

                json={
                    "model": OLLAMA_MODEL,

                    "messages": messages,

                    "stream": True,

                    "options": {

                        # Lower temperature = faster/more focused
                        "temperature": 0.5,

                        # Shorter default answers
                        "num_predict": 400,

                        # Smaller context = faster processing
                        "num_ctx": 4096
                    }
                },

                stream=True,

                # 10 sec connection + 5 min response
                timeout=(10, 300)
            )


        except requests.exceptions.ConnectionError:

            return jsonify({
                "error":
                "Cannot connect to Ollama. "
                "Please make sure Ollama is running."
            }), 500


        except requests.exceptions.Timeout:

            return jsonify({
                "error":
                "Connection to Ollama timed out."
            }), 500


        # =================================================
        # CHECK RESPONSE
        # =================================================

        if ollama_response.status_code != 200:

            error_text = ollama_response.text

            ollama_response.close()

            return jsonify({
                "error":
                "Ollama returned an error: "
                + error_text
            }), 500


        # =================================================
        # STREAM RESPONSE TO BROWSER
        # =================================================

        @stream_with_context
        def generate():

            try:

                for line in ollama_response.iter_lines(
                    decode_unicode=True
                ):

                    if not line:
                        continue


                    try:

                        chunk = json.loads(line)

                    except json.JSONDecodeError:

                        continue


                    # Get streaming token

                    message = chunk.get(
                        "message",
                        {}
                    )

                    token = message.get(
                        "content",
                        ""
                    )


                    # Send immediately to browser

                    if token:

                        yield (
                            json.dumps(
                                {
                                    "token": token
                                },
                                ensure_ascii=False
                            )
                            + "\n"
                        )


                    # Stop when finished

                    if chunk.get("done"):

                        break


            except GeneratorExit:

                pass


            except Exception as e:

                yield (
                    json.dumps(
                        {
                            "error": str(e)
                        },
                        ensure_ascii=False
                    )
                    + "\n"
                )


            finally:

                ollama_response.close()


        # =================================================
        # RETURN STREAMING RESPONSE
        # =================================================

        return Response(

            generate(),

            mimetype="application/x-ndjson",

            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive"
            }
        )


    except Exception as e:

        print(
            "Assistant API Error:",
            str(e)
        )

        return jsonify({
            "error": str(e)
        }), 500


# =====================================================
# QUIZ API
# =====================================================

@app.route("/api/quiz", methods=["POST"])
def api_quiz():

    try:

        data = request.get_json(silent=True)

        if not data:
            return jsonify({
                "error": "No data received."
            }), 400


        topic = str(
            data.get("topic", "")
        ).strip()


        if not topic:
            return jsonify({
                "error": "Please enter a topic."
            }), 400


        prompt = f"""
You are an AI Student Assistant.

Create exactly 5 multiple-choice questions about:

{topic}

For each question provide:

Question
A) option
B) option
C) option
D) option

Correct Answer
Explanation

Keep the quiz useful for a college student.
"""


        response = requests.post(

            OLLAMA_URL,

            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,

                "options": {
                    "temperature": 0.5,
                    "num_predict": 700
                }
            },

            timeout=180
        )


        response.raise_for_status()


        result = response.json()

        answer = result.get(
            "response",
            ""
        )


        if not answer:

            return jsonify({
                "error":
                "Ollama did not return an answer."
            }), 500


        return jsonify({
            "answer": answer
        })


    except requests.exceptions.ConnectionError:

        return jsonify({
            "error":
            "Cannot connect to Ollama."
        }), 500


    except requests.exceptions.Timeout:

        return jsonify({
            "error":
            "Ollama took too long to respond."
        }), 500


    except Exception as e:

        return jsonify({
            "error": str(e)
        }), 500


# =====================================================
# STUDY PLANNER API
# =====================================================

@app.route("/api/study-plan", methods=["POST"])
def study_plan():

    try:

        data = request.get_json(silent=True)

        if not data:
            return jsonify({
                "error": "No data received."
            }), 400


        subjects = str(
            data.get("subjects", "")
        ).strip()

        days = data.get("days", "")
        hours = data.get("hours", "")

        level = data.get(
            "level",
            "Beginner"
        )

        exam = data.get(
            "exam",
            "Regular Study"
        )


        if not subjects:

            return jsonify({
                "error":
                "Please enter your subjects."
            }), 400


        if not days:

            return jsonify({
                "error":
                "Please enter the number of days."
            }), 400


        if not hours:

            return jsonify({
                "error":
                "Please enter study hours per day."
            }), 400


        prompt = f"""
Create a personalized study plan.

Subjects:
{subjects}

Number of Days:
{days}

Study Hours Per Day:
{hours}

Student Level:
{level}

Exam Type:
{exam}

Include:

1. Day-by-day schedule
2. Subject allocation
3. Important topics
4. Practice time
5. Revision
6. Short breaks
7. Final exam preparation

Make it realistic and easy for a college student.
"""


        response = requests.post(

            OLLAMA_URL,

            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,

                "options": {
                    "temperature": 0.5,
                    "num_predict": 900
                }
            },

            timeout=180
        )


        response.raise_for_status()


        result = response.json()

        plan = result.get(
            "response",
            ""
        )


        if not plan:

            return jsonify({
                "error":
                "Ollama did not generate a study plan."
            }), 500


        return jsonify({
            "plan": plan
        })


    except requests.exceptions.ConnectionError:

        return jsonify({
            "error":
            "Cannot connect to Ollama."
        }), 500


    except requests.exceptions.Timeout:

        return jsonify({
            "error":
            "Ollama took too long to respond."
        }), 500


    except Exception as e:

        return jsonify({
            "error": str(e)
        }), 500


# =====================================================
# PDF ASSIGNMENT API
# =====================================================

@app.route("/api/pdf-assignment", methods=["POST"])
def pdf_assignment():

    try:

        if "pdf" not in request.files:

            return jsonify({
                "error":
                "No PDF file was uploaded."
            }), 400


        pdf_file = request.files["pdf"]


        if pdf_file.filename == "":

            return jsonify({
                "error":
                "Please select a PDF file."
            }), 400


        if not pdf_file.filename.lower().endswith(".pdf"):

            return jsonify({
                "error":
                "Please upload a PDF file only."
            }), 400


        # Read PDF

        reader = PdfReader(pdf_file)

        text = ""


        for page in reader.pages:

            page_text = page.extract_text()

            if page_text:
                text += page_text + "\n"


        if not text.strip():

            return jsonify({
                "error":
                "Could not extract text from this PDF."
            }), 400


        # Limit PDF size

        text = text[:30000]


        prompt = f"""
You are an AI Student Assistant.

Create a college-level assignment using ONLY
the following PDF material.

PDF CONTENT:

{text}

Create:

TITLE

INTRODUCTION

SECTION 1:
Important questions

SECTION 2:
5 short-answer questions

SECTION 3:
5 long-answer questions

SECTION 4:
5 multiple-choice questions with answers

IMPORTANT TOPICS

SUMMARY

STUDY TIPS

Use simple English.
Do not add unrelated information.
"""


        response = requests.post(

            OLLAMA_URL,

            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,

                "options": {
                    "temperature": 0.5,
                    "num_predict": 1200
                }
            },

            timeout=240
        )


        response.raise_for_status()


        result = response.json()

        answer = result.get(
            "response",
            ""
        )


        if not answer:

            return jsonify({
                "error":
                "Ollama did not generate an assignment."
            }), 500


        return jsonify({
            "answer": answer
        })


    except requests.exceptions.ConnectionError:

        return jsonify({
            "error":
            "Cannot connect to Ollama."
        }), 500


    except requests.exceptions.Timeout:

        return jsonify({
            "error":
            "Ollama took too long to generate the assignment."
        }), 500


    except Exception as e:

        return jsonify({
            "error": str(e)
        }), 500


# =====================================================
# START FLASK SERVER
# =====================================================

if __name__ == "__main__":

    app.run(
        host="127.0.0.1",
        port=5002,
        debug=False,
        threaded=True
    )