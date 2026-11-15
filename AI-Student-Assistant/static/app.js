
"use strict";

// =====================================================
// AI CHATBOTS CONFIGURATION & PERSONAS
// =====================================================

const BOTS = {
  general: {
    id: "general",
    name: "General Tutor",
    avatar: "🎓",
    desc: "Explaining concepts, exam topics, and college studies clearly.",
    heading: "What would you like to learn today?",
    subheading: "Ask any academic or conceptual question — I break it down simply.",
    suggestions: [
      "Explain machine learning in simple, practical words.",
      "How does cellular respiration generate ATP?",
      "Key differences between SQL and NoSQL databases.",
      "Give me a 5-step checklist to prepare for semester exams."
    ]
  },
  coder: {
    id: "coder",
    name: "Code Mentor",
    avatar: "💻",
    desc: "Python, C++, Java, JS, algorithm design, data structures & debugging.",
    heading: "Ready to write, debug, and master code?",
    subheading: "Paste your code, describe a bug, or ask for an algorithm breakdown.",
    suggestions: [
      "Write a Python function to reverse a singly linked list.",
      "Explain the binary search algorithm with time complexity.",
      "Debug this: IndexError: list index out of range.",
      "How does async/await work in JavaScript with an example?"
    ]
  },
  math: {
    id: "math",
    name: "Math & Science Solver",
    avatar: "🔬",
    desc: "Step-by-step calculus, physics formulas, chemistry & derivations.",
    heading: "Let's solve equations and derive formulas.",
    subheading: "I show every formula, substitution, and reasoning step clearly.",
    suggestions: [
      "Step-by-step derivative of f(x) = x * sin(x).",
      "Explain Newton's laws of motion with real-world examples.",
      "How to find the determinant and eigenvalues of a 3x3 matrix?",
      "Balance this chemical equation: C3H8 + O2 -> CO2 + H2O."
    ]
  },
  writer: {
    id: "writer",
    name: "Essay & Writing Coach",
    avatar: "✍️",
    desc: "Essay outlines, thesis refinement, academic tone, vocabulary & emails.",
    heading: "Elevate your essays, research papers, and drafts.",
    subheading: "I help you build persuasive arguments, strong thesis statements, and clear prose.",
    suggestions: [
      "Help me craft a strong thesis statement on artificial intelligence ethics.",
      "Improve this paragraph to sound more formal, polished, and academic.",
      "Outline a 5-paragraph argumentative essay on renewable energy.",
      "Draft a polite, professional email to my professor asking for an extension."
    ]
  },
  exam: {
    id: "exam",
    name: "Exam Revision Coach",
    avatar: "🎯",
    desc: "High-yield summaries, memory mnemonics, quick formulas & test checkpoints.",
    heading: "Fast, high-yield exam preparation & revision.",
    subheading: "Memorize faster with key bullet points, mnemonics, and self-test checkpoints.",
    suggestions: [
      "High-yield 5-minute summary of Operating Systems memory management.",
      "Give me a catchy mnemonic to remember the biological taxonomy ranks.",
      "Top 5 most frequently asked viva / interview questions in DBMS.",
      "Rapid revision: What are ACID properties with real banking examples?"
    ]
  }
};

let activeBot = "general";
const botHistories = {
  general: [],
  coder: [],
  math: [],
  writer: [],
  exam: []
};

// =====================================================
// NAVIGATION & VIEW SWITCHING
// =====================================================

const pageNames = {
  home: "Dashboard",
  assistant: "AI Chatbots",
  quiz: "Quiz Generator",
  planner: "Study Planner",
  pdf: "PDF Assistant"
};

function switchView(targetView) {
  document.querySelectorAll("[data-view]").forEach((view) => {
    view.classList.toggle("active", view.dataset.view === targetView);
  });

  document.querySelectorAll("[data-nav]").forEach((link) => {
    const isCurrent = link.dataset.nav === targetView;
    link.classList.toggle("active", isCurrent);
    if (isCurrent) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });

  const pageNameEl = document.getElementById("pageName");
  if (pageNameEl) pageNameEl.textContent = pageNames[targetView] || "Dashboard";

  window.scrollTo({ top: 0, behavior: "smooth" });
}

// Intercept sidebar / internal links for instantaneous SPA navigation
document.querySelectorAll("[data-nav]").forEach((link) => {
  link.addEventListener("click", (event) => {
    const target = link.dataset.nav;
    if (target && document.querySelector(`[data-view="${target}"]`)) {
      event.preventDefault();
      switchView(target);
      if (window.history && window.history.pushState) {
        window.history.pushState({ page: target }, "", link.getAttribute("href") || `/${target}`);
      }
    }
  });
});

// Handle browser Back / Forward buttons
window.addEventListener("popstate", (event) => {
  const page = (event.state && event.state.page) || document.body.dataset.page || "home";
  switchView(page);
});

// Mobile menu toggle
const sidebar = document.getElementById("sidebar");
const menuButton = document.getElementById("menuButton");

if (menuButton && sidebar) {
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
}

function showToast(message) {
  const toast = document.getElementById("toast");
  if (!toast) return;
  toast.textContent = message;
  toast.hidden = false;
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => {
    toast.hidden = true;
  }, 4000);
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
  if (!button) return;
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
  body.innerHTML = formatMarkdown(content);

  element.append(heading, body);
  element.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

// =====================================================
// MARKDOWN & CODE HIGHLIGHTING FORMATTER
// =====================================================

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

function formatMarkdown(text) {
  if (!text) return "";

  // If marked.js is available on window, use it
  if (window.marked && typeof window.marked.parse === "function") {
    try {
      const parsed = window.marked.parse(text, { breaks: true, gfm: true });
      return enhanceCodeBlocks(parsed);
    } catch {
      // Fallback below
    }
  }

  // Simple, robust fallback markdown formatter
  let html = escapeHtml(text);

  // Code blocks ```code```
  html = html.replace(/```([a-zA-Z0-9_-]*)\n([\s\S]*?)```/g, (_match, lang, code) => {
    const langDisplay = lang || "code";
    return `<div class="code-block-container"><div class="code-block-header"><span>${langDisplay}</span><button class="code-copy-btn" onclick="copyCode(this)">📋 Copy</button></div><pre><code>${code.trim()}</code></pre></div>`;
  });

  // Inline code
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");

  // Bold & Italics
  html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/\*([^*]+)\*/g, "<em>$1</em>");

  // Line breaks
  html = html.replace(/\n\n/g, "</p><p>");
  html = html.replace(/\n/g, "<br>");

  return `<p>${html}</p>`;
}

function enhanceCodeBlocks(html) {
  // Wrap standard <pre><code> blocks with header and copy button
  const temp = document.createElement("div");
  temp.innerHTML = html;

  temp.querySelectorAll("pre").forEach((pre) => {
    const code = pre.querySelector("code");
    const codeText = code ? code.textContent : pre.textContent;
    const langMatch = code ? code.className.match(/language-(\w+)/) : null;
    const lang = langMatch ? langMatch[1] : "code";

    const container = document.createElement("div");
    container.className = "code-block-container";

    const header = document.createElement("div");
    header.className = "code-block-header";
    header.innerHTML = `<span>${lang}</span><button class="code-copy-btn" type="button">📋 Copy</button>`;

    const copyBtn = header.querySelector(".code-copy-btn");
    copyBtn.addEventListener("click", () => {
      navigator.clipboard.writeText(codeText).then(() => {
        copyBtn.textContent = "✓ Copied!";
        setTimeout(() => { copyBtn.textContent = "📋 Copy"; }, 2000);
      });
    });

    pre.parentNode.insertBefore(container, pre);
    container.appendChild(header);
    container.appendChild(pre);
  });

  return temp.innerHTML;
}

window.copyCode = function (btn) {
  const container = btn.closest(".code-block-container");
  if (!container) return;
  const pre = container.querySelector("pre");
  if (!pre) return;
  navigator.clipboard.writeText(pre.textContent).then(() => {
    btn.textContent = "✓ Copied!";
    setTimeout(() => { btn.textContent = "📋 Copy"; }, 2000);
  });
};

// =====================================================
// CHAT RENDERING & BOT SWITCHING
// =====================================================

const chatMessages = document.getElementById("chatMessages");
const chatForm = document.getElementById("chatForm");
const chatInput = document.getElementById("chatInput");

function setBotSuggestions(botKey) {
  const bot = BOTS[botKey] || BOTS.general;
  const container = document.getElementById("botSuggestions");
  if (!container) return;

  container.replaceChildren();
  bot.suggestions.forEach((text) => {
    const btn = document.createElement("button");
    btn.className = "suggestion";
    btn.type = "button";
    btn.textContent = text;
    btn.addEventListener("click", () => {
      chatInput.value = text;
      chatInput.focus();
    });
    container.appendChild(btn);
  });
}

function selectBot(botKey) {
  if (!BOTS[botKey]) botKey = "general";
  activeBot = botKey;
  const bot = BOTS[botKey];

  // Update tabs
  document.querySelectorAll(".bot-chip").forEach((chip) => {
    const isSelected = chip.dataset.bot === botKey;
    chip.classList.toggle("active", isSelected);
    chip.setAttribute("aria-selected", isSelected ? "true" : "false");
  });

  // Update toolbar
  const avatarEl = document.getElementById("activeBotAvatar");
  const nameEl = document.getElementById("activeBotName");
  const descEl = document.getElementById("activeBotDesc");
  if (avatarEl) avatarEl.textContent = bot.avatar;
  if (nameEl) nameEl.textContent = bot.name;
  if (descEl) descEl.textContent = bot.desc;

  // Update welcome card text
  const welcomeIcon = document.getElementById("welcomeIcon");
  const welcomeHeading = document.getElementById("welcomeHeading");
  const welcomeSub = document.getElementById("welcomeSubheading");
  if (welcomeIcon) welcomeIcon.textContent = bot.avatar;
  if (welcomeHeading) welcomeHeading.textContent = bot.heading;
  if (welcomeSub) welcomeSub.textContent = bot.subheading;

  // Update dynamic suggestions
  setBotSuggestions(botKey);

  // Restore history for this bot
  renderBotHistory(botKey);
}

function renderBotHistory(botKey) {
  chatMessages.replaceChildren();
  const history = botHistories[botKey] || [];

  if (history.length === 0) {
    const bot = BOTS[botKey];
    const welcome = document.createElement("div");
    welcome.className = "welcome-message";
    welcome.id = "welcomeMessage";
    welcome.innerHTML = `
      <div class="welcome-icon">${bot.avatar}</div>
      <h2>${bot.heading}</h2>
      <p>${bot.subheading}</p>
      <div class="suggestions" id="botSuggestions"></div>
    `;
    chatMessages.appendChild(welcome);
    setBotSuggestions(botKey);
    return;
  }

  history.forEach((msg) => {
    appendMessage(msg.role, msg.content, botKey, false);
  });

  chatMessages.scrollTop = chatMessages.scrollHeight;
}

function appendMessage(role, content, botKey = activeBot, animate = true) {
  const bot = BOTS[botKey] || BOTS.general;

  const welcome = chatMessages.querySelector(".welcome-message");
  if (welcome) welcome.remove();

  const wrapper = document.createElement("div");
  wrapper.className = `message-wrapper ${role}`;

  const avatar = document.createElement("div");
  avatar.className = "msg-avatar";
  avatar.textContent = role === "user" ? "👤" : bot.avatar;

  const body = document.createElement("div");
  body.className = "message-body";

  const bubble = document.createElement("div");
  bubble.className = "message-bubble";

  if (role === "user") {
    bubble.textContent = content;
  } else {
    bubble.innerHTML = formatMarkdown(content);
  }

  body.appendChild(bubble);

  if (role === "assistant") {
    const footer = document.createElement("div");
    footer.className = "msg-footer";

    const botTag = document.createElement("span");
    botTag.textContent = bot.name;

    const copyBtn = document.createElement("button");
    copyBtn.type = "button";
    copyBtn.className = "copy-msg-btn";
    copyBtn.textContent = "📋 Copy";
    copyBtn.addEventListener("click", () => {
      navigator.clipboard.writeText(content).then(() => {
        copyBtn.textContent = "✓ Copied";
        setTimeout(() => { copyBtn.textContent = "📋 Copy"; }, 2000);
      });
    });

    footer.appendChild(botTag);
    footer.appendChild(copyBtn);
    body.appendChild(footer);
  }

  wrapper.appendChild(avatar);
  wrapper.appendChild(body);
  chatMessages.appendChild(wrapper);

  if (animate) {
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }

  return { wrapper, bubble };
}

function showTypingIndicator(botKey = activeBot) {
  const bot = BOTS[botKey] || BOTS.general;

  const welcome = chatMessages.querySelector(".welcome-message");
  if (welcome) welcome.remove();

  const wrapper = document.createElement("div");
  wrapper.className = "message-wrapper assistant typing-wrapper";

  const avatar = document.createElement("div");
  avatar.className = "msg-avatar";
  avatar.textContent = bot.avatar;

  const body = document.createElement("div");
  body.className = "message-body";

  const bubble = document.createElement("div");
  bubble.className = "message-bubble typing-bubble";
  bubble.innerHTML = `
    <span class="typing-dot"></span>
    <span class="typing-dot"></span>
    <span class="typing-dot"></span>
  `;

  body.appendChild(bubble);
  wrapper.appendChild(avatar);
  wrapper.appendChild(body);
  chatMessages.appendChild(wrapper);
  chatMessages.scrollTop = chatMessages.scrollHeight;

  return wrapper;
}

// Bot selector pill click handlers
document.querySelectorAll(".bot-chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    const botKey = chip.dataset.bot;
    if (botKey) selectBot(botKey);
  });
});

// Dashboard "Launch Bot" cards click handlers
document.querySelectorAll("[data-launch-bot]").forEach((card) => {
  card.addEventListener("click", () => {
    const botKey = card.dataset.launchBot;
    switchView("assistant");
    selectBot(botKey);
    if (window.history && window.history.pushState) {
      window.history.pushState({ page: "assistant" }, "", "/assistant");
    }
  });
});

// Clear conversation button
document.getElementById("clearChat").addEventListener("click", () => {
  botHistories[activeBot] = [];
  renderBotHistory(activeBot);
  chatInput.value = "";
  chatInput.focus();
  showToast(`Cleared conversation with ${BOTS[activeBot].name}.`);
});

// Auto-expand textarea
chatInput.addEventListener("input", () => {
  chatInput.style.height = "auto";
  chatInput.style.height = `${Math.min(chatInput.scrollHeight, 140)}px`;
});

// Send on Enter (Shift+Enter for newline)
chatInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    chatForm.requestSubmit();
  }
});

// =====================================================
// CHAT FORM SUBMISSION (TALK TO GEMINI BACKEND)
// =====================================================

chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();

  const question = chatInput.value.trim();
  if (!question) return;

  const currentBotKey = activeBot;
  const sendButton = chatForm.querySelector(".send-button");
  const historyForRequest = (botHistories[currentBotKey] || []).slice(-12);

  // Append user message
  appendMessage("user", question, currentBotKey);
  chatInput.value = "";
  chatInput.style.height = "auto";
  chatInput.disabled = true;
  setBusy(sendButton, true, "…");

  // Show animated typing indicator
  const typingIndicator = showTypingIndicator(currentBotKey);

  try {
    const response = await fetch("/api/assistant", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question,
        history: historyForRequest,
        bot: currentBotKey
      })
    });

    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.error || `AI request failed (${response.status}).`);
    }

    // Read full answer
    const rawText = await response.text();
    let answerText = "";

    // Parse NDJSON lines
    const lines = rawText.split("\n");
    for (const line of lines) {
      if (!line.trim()) continue;
      try {
        const item = JSON.parse(line);
        if (item.error) throw new Error(item.error);
        if (typeof item.token === "string") answerText += item.token;
      } catch (err) {
        if (err.message && err.message !== "Unexpected end of JSON input") {
          throw err;
        }
      }
    }

    if (!answerText.trim()) {
      answerText = rawText.trim();
    }

    if (!answerText) {
      throw new Error("The AI returned an empty response.");
    }

    // Remove typing indicator and render final assistant response
    typingIndicator.remove();
    appendMessage("assistant", answerText, currentBotKey);

    // Save to conversation history
    botHistories[currentBotKey].push(
      { role: "user", content: question },
      { role: "assistant", content: answerText }
    );

  } catch (error) {
    typingIndicator.remove();
    const errorBubble = appendMessage(
      "assistant",
      `⚠️ **Error:** ${error.message}\n\nPlease try again in a few moments.`,
      currentBotKey
    );
    errorBubble.bubble.classList.add("error-text");
  } finally {
    chatInput.disabled = false;
    setBusy(sendButton, false);
    chatInput.focus();
  }
});

// =====================================================
// QUIZ GENERATOR
// =====================================================

document.getElementById("quizForm").addEventListener("submit", async (event) => {
  event.preventDefault();

  const form = event.currentTarget;
  const button = form.querySelector("button[type=submit]");
  const result = document.getElementById("quizResult");
  const topic = document.getElementById("quizTopic").value.trim();

  if (!topic) return;

  setBusy(button, true, "Generating quiz…");
  showResult(result, `Generating quiz for "${topic}"`, "The AI is formulating 5 college-level questions with answer keys...");

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

// =====================================================
// STUDY PLANNER
// =====================================================

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

  if (!Number.isInteger(days) || days < 1 || days > 90 || hours < 0.5 || hours > 16) {
    showToast("Use 1–90 days and 0.5–16 study hours per day.");
    return;
  }

  setBusy(button, true, "Building your plan…");
  showResult(result, "Creating your personalized study plan", "The AI is organizing your timetable with Pomodoro revision sessions...");

  try {
    const response = await fetch("/api/study-plan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ subjects, days, hours })
    });

    const data = await readJson(response);
    showResult(result, "Your Personalized Study Plan", data.plan || "No plan was returned.");
  } catch (error) {
    showResult(result, "Unable to create study plan", error.message, true);
  } finally {
    setBusy(button, false);
  }
});

// =====================================================
// PDF ASSISTANT
// =====================================================

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

  if (!file.name.toLowerCase().endsWith(".pdf") || file.size > 15 * 1024 * 1024) {
    showToast("Choose a PDF file smaller than 15 MB.");
    return;
  }

  const question = document.getElementById("pdfQuestion").value.trim();
  const data = new FormData();
  data.append("pdf", file);
  data.append(
    "question",
    question || "Summarize this document, identify core concepts, and create study questions."
  );

  setBusy(button, true, "Analyzing PDF…");
  showResult(result, `Analyzing "${file.name}"`, "Extracting text and generating comprehensive study notes...");

  try {
    const response = await fetch("/api/pdf-assignment", {
      method: "POST",
      body: data
    });

    const answer = await readJson(response);
    showResult(result, `Document Analysis: ${file.name}`, answer.answer || "No answer was returned.");
  } catch (error) {
    showResult(result, "Unable to analyze PDF", error.message, true);
  } finally {
    setBusy(button, false);
  }
});

// Initialize on page load
const initialPage = document.body.dataset.page || "home";
switchView(initialPage);
selectBot("general");

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
