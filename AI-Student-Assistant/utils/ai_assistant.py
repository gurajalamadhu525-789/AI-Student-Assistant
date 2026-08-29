from ollama import chat


def ask_ai(question):
    if not question or not question.strip():
        return "Please enter a question."

    try:
        response = chat(
            model="qwen3:0.6b",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an AI Student Assistant. "
                        "Explain study topics clearly and simply. "
                        "Use examples when helpful. "
                        "Help students understand their studies."
                    )
                },
                {
                    "role": "user",
                    "content": question
                }
            ]
        )

        return response.message.content

    except Exception as e:
        return f"AI Error: {e}"