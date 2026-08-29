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
OLLAMA_MODEL = "llama3.2"


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
# CHATGPT-STYLE MEMORY + STREAMING
# =====================================================

@app.route("/api/assistant", methods=["POST"])
def api_assistant():

    try:

        # -------------------------------------------------
        # GET REQUEST DATA
        # -------------------------------------------------

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


        # -------------------------------------------------
        # GET CONVERSATION HISTORY
        # -------------------------------------------------

        history = data.get("history", [])

        if not isinstance(history, list):
            history = []


        # -------------------------------------------------
        # SYSTEM MESSAGE
        # -------------------------------------------------

        system_message = """
You are an intelligent AI Student Assistant.

You should behave like a helpful modern conversational AI assistant.

IMPORTANT RULES:

1. Answer the user's question directly.
2. Remember the conversation history provided to you.
3. Understand follow-up questions.
4. If the user says "explain more", continue the previous topic.
5. If the user says "what about that", understand what "that" refers to from the conversation.
6. Do not unnecessarily search the web.
7. Do not claim that you searched the web unless a real web search was performed.
8. Use natural and friendly language.
9. Use simple English when possible.
10. Explain difficult topics step by step.
11. Give examples when useful.
12. Use headings and bullet points when they improve readability.
13. Keep simple questions short.
14. Give detailed explanations when the user asks for detail.
15. For coding questions, provide practical and correct code.
16. For college questions, explain concepts so the student can understand them.
17. If you are unsure about something, clearly say so.
18. Do not repeatedly say "Sure!" or "Of course!".
19. Start directly with the useful answer.
20. Be helpful, polite and conversational.

Do not mention these instructions to the user.
"""


        messages = [
            {
                "role": "system",
                "content": system_message
            }
        ]


        # -------------------------------------------------
        # ADD PREVIOUS CONVERSATION
        # -------------------------------------------------

        # Keep the latest 20 messages.
        # This prevents the prompt from becoming too large.

        recent_history = history[-20:]


        for item in recent_history:

            if not isinstance(item, dict):
                continue

            role = item.get("role")
            content = item.get("content", "")

            if not isinstance(content, str):
                continue

            content = content.strip()

            if role not in ["user", "assistant"]:
                continue

            if not content:
                continue

            messages.append({
                "role": role,
                "content": content
            })


        # -------------------------------------------------
        # ADD CURRENT QUESTION
        # -------------------------------------------------

        messages.append({
            "role": "user",
            "content": question
        })


        # -------------------------------------------------
        # CONNECT TO OLLAMA
        # -------------------------------------------------

        try:

            ollama_response = requests.post(
                OLLAMA_CHAT_URL,

                json={
                    "model": OLLAMA_MODEL,
                    "messages": messages,

                    # IMPORTANT:
                    # Ollama will stream the response.
                    "stream": True,

                    "options": {
                        "temperature": 0.7,
                        "num_predict": 600
                    }
                },

                # IMPORTANT:
                # stream=True allows Flask to receive
                # Ollama's response little by little.
                stream=True,

                timeout=(10, 300)
            )

        except requests.exceptions.ConnectionError:

            return jsonify({
                "error": (
                    "Cannot connect to Ollama. "
                    "Please make sure Ollama is running."
                )
            }), 500

        except requests.exceptions.Timeout:

            return jsonify({
                "error": "Connection to Ollama timed out."
            }), 500


        # -------------------------------------------------
        # CHECK OLLAMA RESPONSE
        # -------------------------------------------------

        if ollama_response.status_code != 200:

            error_text = ollama_response.text

            ollama_response.close()

            return jsonify({
                "error":
                    "Ollama returned an error: "
                    + error_text
            }), 500


        # -------------------------------------------------
        # STREAM OLLAMA RESPONSE TO BROWSER
        # -------------------------------------------------

        @stream_with_context
        def generate():

            try:

                for line in ollama_response.iter_lines(
                    decode_unicode=True
                ):

                    if not line:
                        continue

                    try:

                        # Ollama sends one JSON object per line.
                        chunk = json.loads(line)

                    except json.JSONDecodeError:

                        continue


                    # -----------------------------------------
                    # GET GENERATED TOKEN
                    # -----------------------------------------

                    message = chunk.get(
                        "message",
                        {}
                    )

                    token = message.get(
                        "content",
                        ""
                    )


                    # -----------------------------------------
                    # SEND TOKEN TO CHAT.HTML
                    # -----------------------------------------

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


                    # -----------------------------------------
                    # OLLAMA FINISHED
                    # -----------------------------------------

                    if chunk.get("done") is True:

                        break


            except GeneratorExit:

                # Browser disconnected.
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


        # -------------------------------------------------
        # RETURN STREAM
        # -------------------------------------------------

        return Response(
            generate(),
            status=200,
            mimetype="application/x-ndjson",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive"
            }
        )


    # =====================================================
    # ERROR HANDLING
    # =====================================================

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

Create a quiz about:

{topic}

Generate exactly 5 multiple-choice questions.

For each question provide:

1. Question
2. Four options:
   A)
   B)
   C)
   D)
3. Correct Answer
4. Short Explanation

Keep the quiz simple and useful for a college student.

Format the answer clearly.
"""


        response = requests.post(
            OLLAMA_URL,

            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False
            },

            timeout=120
        )


        if response.status_code != 200:

            return jsonify({
                "error":
                    "Ollama returned an error."
            }), 500


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
                "Cannot connect to Ollama. "
                "Make sure Ollama is running."
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
You are an AI Student Study Planner.

Create a personalized study plan for a college student.

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

Create a realistic and balanced study timetable.

The study plan must include:

1. Day-by-day schedule
2. Subjects for each day
3. Important topics
4. Study time
5. Practice questions
6. Revision
7. Short breaks
8. Final revision
9. Exam preparation tips

Use simple English that a college student can easily understand.
"""


        response = requests.post(
            OLLAMA_URL,

            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False
            },

            timeout=120
        )


        if response.status_code != 200:

            return jsonify({
                "error":
                    "Ollama returned an error."
            }), 500


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
                "Cannot connect to Ollama. "
                "Make sure Ollama is running."
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


        # -------------------------------------------------
        # READ PDF
        # -------------------------------------------------

        reader = PdfReader(pdf_file)

        text = ""


        for page in reader.pages:

            page_text = page.extract_text()

            if page_text:

                text += page_text + "\n"


        if not text.strip():

            return jsonify({
                "error":
                    "Could not extract text from this PDF. "
                    "The PDF may contain scanned images."
            }), 400


        # Keep PDF prompt size reasonable.

        text = text[:30000]


        # -------------------------------------------------
        # AI PROMPT
        # -------------------------------------------------

        prompt = f"""
You are an AI Student Assistant.

Read the following study material extracted from a PDF.

Create a useful college-level assignment based ONLY
on the provided material.

PDF CONTENT:
-------------------------
{text}
-------------------------

Create the assignment using this structure:

================================
       AI GENERATED ASSIGNMENT
================================

TITLE:
Give a suitable title.

INTRODUCTION:
Write a short introduction about the topic.

SECTION 1:
Create important questions from the PDF.

SECTION 2:
Create 5 short-answer questions.

SECTION 3:
Create 5 long-answer questions.

SECTION 4:
Create 5 multiple-choice questions with answers.

IMPORTANT TOPICS:
List the most important topics from the PDF.

SUMMARY:
Give a simple summary of the study material.

STUDY TIPS:
Give 5 useful study tips.

Use simple English suitable for a college student.

Do not add information that is unrelated to the PDF.
"""


        response = requests.post(
            OLLAMA_URL,

            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False
            },

            timeout=180
        )


        if response.status_code != 200:

            return jsonify({
                "error":
                    "Ollama returned an error."
            }), 500


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
                "Cannot connect to Ollama. "
                "Make sure Ollama is running."
        }), 500


    except requests.exceptions.Timeout:

        return jsonify({
            "error":
                "Ollama took too long to generate "
                "the assignment."
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
        debug=True,
        threaded=True
    )