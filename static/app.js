
"use strict";

const currentPage = document.body.dataset.page || "home";

const pageNames = {
  home: "Dashboard",
  assistant: "AI Assistant",
  quiz: "Quiz Generator",
  planner: "Study Planner",
  pdf: "PDF Assistant"
};

document.querySelectorAll("[data-view]").forEach((view) => {
  view.classList.toggle("active", view.dataset.view === currentPage);
});

document.querySelectorAll("[data-nav]").forEach((link) => {
  if (link.dataset.nav === currentPage) {
    link.classList.add("active");
    link.setAttribute("aria-current", "page");
  }
});

document.getElementById("pageName").textContent =
  pageNames[currentPage] || "Dashboard";

const sidebar = document.getElementById("sidebar");
const menuButton = document.getElementById("menuButton");

menuButton.addEventListener("click", () => {
  sidebar.classList.toggle("open");
});

document.addEventListener("click", (event) => {
  if (
    window.innerWidth <= 760 &&
    sidebar.classList.contains("open") &&
    !sidebar.contains(event.target) &&
    !menuButton.contains(event.target)
  ) {
    sidebar.classList.remove("open");
  }
});

function showToast(message) {
  const toast = document.getElementById("toast");
  toast.textContent = message;
  toast.hidden = false;
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => {
    toast.hidden = true;
  }, 4500);
}

async function readJson(response) {
  let data;
  try {
    data = await response.json();
  } catch {
    throw new Error(`The server returned HTTP ${response.status}.`);
  }

  if (!response.ok) {
    throw new Error(data.error || `Request failed (${response.status}).`);
  }

  return data;
}

function setBusy(button, busy, label) {
  if (!button.dataset.originalText) {
    button.dataset.originalText = button.textContent;
  }

  button.disabled = busy;
  button.textContent = busy ? label : button.dataset.originalText;
}

function showResult(element, title, content, isError = false) {
  element.hidden = false;
  element.replaceChildren();

  const heading = document.createElement("h2");
  heading.textContent = title;

  const body = document.createElement("div");
  body.className = isError ? "result-content error-text" : "result-content";
  body.textContent = content;

  element.append(heading, body);
  element.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function appendMessage(role, text) {
  const messages = document.getElementById("chatMessages");

  const welcome = messages.querySelector(".welcome-message");
  if (welcome) welcome.remove();

  const message = document.createElement("div");
  message.className = `message ${role}`;
  message.textContent = text;
  messages.appendChild(message);
  messages.scrollTop = messages.scrollHeight;

  return message;
}

// -----------------------------
// AI ASSISTANT - streaming chat
// -----------------------------

const chatForm = document.getElementById("chatForm");
const chatInput = document.getElementById("chatInput");
const chatMessages = document.getElementById("chatMessages");
const chatHistory = [];

document.querySelectorAll("[data-prompt]").forEach((button) => {
  button.addEventListener("click", () => {
    chatInput.value = button.dataset.prompt;
    chatInput.focus();
  });
});

document.getElementById("clearChat").addEventListener("click", () => {
  chatHistory.length = 0;
  chatMessages.replaceChildren();

  const welcome = document.createElement("div");
  welcome.className = "welcome-message";

  const icon = document.createElement("div");
  icon.className = "welcome-icon";
  icon.textContent = "✦";

  const heading = document.createElement("h2");
  heading.textContent = "What are we learning today?";

  const paragraph = document.createElement("p");
  paragraph.textContent = "Start a new conversation with your AI tutor.";

  welcome.append(icon, heading, paragraph);
  chatMessages.appendChild(welcome);
  chatInput.value = "";
});

chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();

  const question = chatInput.value.trim();
  if (!question) return;

  const sendButton = chatForm.querySelector(".send-button");
  const historyForRequest = chatHistory.slice(-12);

  appendMessage("user", question);
  chatInput.value = "";
  chatInput.disabled = true;
  setBusy(sendButton, true, "…");

  const reply = appendMessage("assistant", "Thinking…");
  reply.classList.add("loading");

  try {
    const response = await fetch("/api/assistant", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question,
        history: historyForRequest
      })
    });

    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.error || `AI request failed (${response.status}).`);
    }

    if (!response.body) {
      throw new Error("Your browser does not support streamed responses.");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let answer = "";
    let streamError = "";

    const processLine = (line) => {
      if (!line.trim()) return;

      let item;
      try {
        item = JSON.parse(line);
      } catch {
        return;
      }

      if (item.error) {
        streamError = item.error;
        return;
      }

      if (typeof item.token === "string") {
        answer += item.token;
        reply.textContent = answer;
        reply.classList.remove("loading");
        chatMessages.scrollTop = chatMessages.scrollHeight;
      }
    };

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      lines.forEach(processLine);
      if (streamError) break;
    }

    buffer += decoder.decode();
    if (buffer.trim()) processLine(buffer);

    if (streamError) throw new Error(streamError);
    if (!answer.trim()) throw new Error("The AI returned an empty response.");

    chatHistory.push(
      { role: "user", content: question },
      { role: "assistant", content: answer }
    );

    reply.classList.remove("loading");
  } catch (error) {
    reply.classList.remove("loading");
    reply.textContent = `Error: ${error.message}`;
    reply.classList.add("error-text");
  } finally {
    chatInput.disabled = false;
    setBusy(sendButton, false);
    chatInput.focus();
  }
});

// -----------------------------
// QUIZ GENERATOR
// -----------------------------

document.getElementById("quizForm").addEventListener("submit", async (event) => {
  event.preventDefault();

  const form = event.currentTarget;
  const button = form.querySelector("button[type=submit]");
  const result = document.getElementById("quizResult");
  const topic = document.getElementById("quizTopic").value.trim();

  if (!topic) return;

  setBusy(button, true, "Generating quiz…");
  showResult(result, "Generating your quiz", "Please wait while the AI prepares your questions.");

  try {
    const response = await fetch("/api/quiz", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ topic })
    });

    const data = await readJson(response);
    showResult(result, `Quiz: ${topic}`, data.answer || "No quiz was returned.");
  } catch (error) {
    showResult(result, "Unable to generate quiz", error.message, true);
  } finally {
    setBusy(button, false);
  }
});

// -----------------------------
// STUDY PLANNER
// -----------------------------

document.getElementById("plannerForm").addEventListener("submit", async (event) => {
  event.preventDefault();

  const form = event.currentTarget;
  const button = form.querySelector("button[type=submit]");
  const result = document.getElementById("plannerResult");

  const subjects = document.getElementById("subjects").value.trim();
  const days = Number(document.getElementById("days").value);
  const hours = Number(document.getElementById("hours").value);

  if (!subjects || !Number.isFinite(days) || !Number.isFinite(hours)) {
    showToast("Please complete all study plan fields.");
    return;
  }

  if (!Number.isInteger(days) || days < 1 || days > 90 ||
      hours < 0.5 || hours > 16) {
    showToast("Use 1–90 days and 0.5–16 study hours per day.");
    return;
  }

  setBusy(button, true, "Building your plan…");
  showResult(result, "Creating your study plan", "The AI is organizing your subjects.");

  try {
    const response = await fetch("/api/study-plan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ subjects, days, hours })
    });

    const data = await readJson(response);
    showResult(result, "Your personalized study plan", data.plan || "No plan was returned.");
  } catch (error) {
    showResult(result, "Unable to create study plan", error.message, true);
  } finally {
    setBusy(button, false);
  }
});

// -----------------------------
// PDF ASSISTANT
// -----------------------------

document.getElementById("pdfForm").addEventListener("submit", async (event) => {
  event.preventDefault();

  const form = event.currentTarget;
  const button = form.querySelector("button[type=submit]");
  const result = document.getElementById("pdfResult");
  const file = document.getElementById("pdfFile").files[0];

  if (!file) {
    showToast("Please select a PDF file.");
    return;
  }

  if (!file.name.toLowerCase().endsWith(".pdf") ||
      file.size > 15 * 1024 * 1024) {
    showToast("Choose a PDF file smaller than 15 MB.");
    return;
  }

  const question = document.getElementById("pdfQuestion").value.trim();
  const data = new FormData();
  data.append("pdf", file);
  data.append(
    "question",
    question || "Summarize this document and explain its important points."
  );

  setBusy(button, true, "Analyzing PDF…");
  showResult(result, "Reading your document", "Please wait while the AI analyzes the PDF.");

  try {
    const response = await fetch("/api/pdf-assignment", {
      method: "POST",
      body: data
    });

    const answer = await readJson(response);
    showResult(result, `Analysis: ${file.name}`, answer.answer || "No answer was returned.");
  } catch (error) {
    showResult(result, "Unable to analyze PDF", error.message, true);
  } finally {
    setBusy(button, false);
  }
});
