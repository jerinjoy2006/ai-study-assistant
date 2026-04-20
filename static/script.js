document.addEventListener("DOMContentLoaded", function () {

/* ── State ── */
let currentMode  = "normal";
let quizActive   = false;
let quizTotalRef = 0;
let quizTopicRef = "";
let historyTab   = "chat";

const chatArea     = document.getElementById("chatArea");
const userInput    = document.getElementById("userInput");
const inputBar     = document.getElementById("inputBar");
const quizInputBar = document.getElementById("quizInputBar");
const modePill     = document.getElementById("modePill");
const topbarSub    = document.getElementById("topbarSub");
const quizHud      = document.getElementById("quizHud");
const hudTopic     = document.getElementById("hudTopic");
const hudProgress  = document.getElementById("hudProgress");
const hudScore     = document.getElementById("hudScore");

const MODE_CONFIG = {
  normal:    { label: "💬 General Chat",   sub: "Ask me anything",                hint: "Press Enter to send · Shift+Enter for new line" },
  explain:   { label: "💡 Explain Mode",   sub: "Enter a concept to explain",      hint: "I'll break it down with analogies & key points" },
  deep_dive: { label: "🔬 Deep Dive Mode", sub: "Enter a topic for deep analysis",  hint: "In-depth academic breakdown" },
  flashcard: { label: "🃏 Flashcard Mode", sub: "Enter a topic for flashcards",    hint: "I'll generate 5 study cards" },
};

function renderMarkdown(text) {
  const div   = document.createElement("div");
  const lines = text.split("\n");
  let html    = "";
  for (const line of lines) {
    if (/^\*\*[^*]+\*\*[:\s]*$/.test(line.trim())) {
      html += `<div class="md-h3">${line.trim().replace(/\*\*/g, "")}</div>`;
      continue;
    }
    const numM = line.match(/^(\d+)\.\s+(.+)/);
    if (numM) { html += `<div class="md-num"><span class="num">${numM[1]}.</span><span>${fmt(numM[2])}</span></div>`; continue; }
    const bulM = line.match(/^[-*]\s+(.+)/);
    if (bulM) { html += `<div class="md-li"><span>${fmt(bulM[1])}</span></div>`; continue; }
    if (/^---+$/.test(line.trim())) { html += `<div class="md-sep"></div>`; continue; }
    if (!line.trim()) { html += "<br>"; continue; }
    html += `<span>${fmt(line)}</span><br>`;
  }
  div.innerHTML = html;
  return div;
}
function fmt(t) {
  return t
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g,     "<em>$1</em>")
    .replace(/`(.+?)`/g,       '<span class="md-code">$1</span>');
}

function hideWelcome() {
  const w = document.getElementById("welcomeState");
  if (w) w.style.display = "none";
}
function scrollBottom() { chatArea.scrollTop = chatArea.scrollHeight; }

function addMsg(type, text, label = "") {
  hideWelcome();
  const wrap = document.createElement("div");
  wrap.className = `msg ${type}`;
  if (label) {
    const lbl = document.createElement("div");
    lbl.className   = "msg-label";
    lbl.textContent = label;
    wrap.appendChild(lbl);
  }
  const bubble = document.createElement("div");
  bubble.className = "msg-bubble";
  if (type === "bot" || type === "analysis") bubble.appendChild(renderMarkdown(text));
  else bubble.textContent = text;
  wrap.appendChild(bubble);
  chatArea.appendChild(wrap);
  scrollBottom();
  return wrap;
}

function addTyping() {
  hideWelcome();
  const wrap = document.createElement("div");
  wrap.className = "msg bot";
  wrap.id = "typing";
  wrap.innerHTML = `<div class="msg-bubble"><div class="typing-dots"><span></span><span></span><span></span></div></div>`;
  chatArea.appendChild(wrap);
  scrollBottom();
}
function removeTyping() { document.getElementById("typing")?.remove(); }

function setModeUI(mode) {
  currentMode = mode;
  const cfg   = MODE_CONFIG[mode] || MODE_CONFIG.normal;
  if (modePill)  modePill.textContent  = cfg.label;
  if (topbarSub) topbarSub.textContent = cfg.sub;
  const hint = document.getElementById("inputHint");
  if (hint) hint.textContent = cfg.hint;
  document.querySelectorAll(".nav-btn[data-mode]").forEach(b =>
    b.classList.toggle("active", b.dataset.mode === mode)
  );
}

function updateQuizHUD(topic, count, total, score) {
  if (!quizHud) return;
  quizHud.style.display   = "flex";
  hudTopic.textContent    = "📚 " + topic;
  hudProgress.textContent = `Q ${count} / ${total}`;
  hudScore.textContent    = `✓ ${score}`;
}

window.setMode = async function(mode) {
  if (quizActive) { addMsg("system", "Finish the quiz before switching modes."); return; }
  await post("/set_mode", { mode });
  setModeUI(mode);
  addMsg("system", `Switched to ${MODE_CONFIG[mode]?.label || mode}`);
  if (userInput) userInput.focus();
};

window.quickStart = function(mode) { window.setMode(mode); if (userInput) userInput.focus(); };

window.summarizeSession = async function() {
  if (quizActive) { addMsg("system", "Finish the quiz first."); return; }
  const prevMode = currentMode;
  await post("/set_mode", { mode: "summarize" });
  addMsg("system", "Generating session summary…");
  addTyping();
  const data = await post("/chat", { message: "" });
  removeTyping();
  await post("/set_mode", { mode: prevMode });
  if (data.ok) addMsg("bot", data.reply, "📋 Session Summary");
  else addMsg("system", "Error: " + (data.error || "Unknown"));
};

window.clearMemory = async function() {
  await post("/clear", {});
  chatArea.innerHTML = "";
  const w = document.createElement("div");
  w.id = "welcomeState"; w.className = "welcome-state";
  w.innerHTML = `<div class="welcome-icon">✦</div>
    <h2>Session cleared!</h2>
    <p>Start a new study session below.</p>
    <div class="quick-actions">
      <button onclick="quickStart('explain')" class="quick-btn">💡 Explain a concept</button>
      <button onclick="quickStart('deep_dive')" class="quick-btn">🔬 Deep dive</button>
      <button onclick="quickStart('flashcard')" class="quick-btn">🃏 Flashcards</button>
      <button onclick="openQuizModal()" class="quick-btn">🎯 Quiz me</button>
    </div>`;
  chatArea.appendChild(w);
  quizActive = false;
  if (quizHud) quizHud.style.display = "none";
  if (inputBar)     inputBar.style.display     = "flex";
  if (quizInputBar) quizInputBar.style.display = "none";
  setModeUI("normal");
};

window.sendMessage = async function() {
  const text = userInput.value.trim();
  if (!text || quizActive) return;
  addMsg("user", text, "You");
  userInput.value = "";
  autoResize(userInput);
  addTyping();
  const data = await post("/chat", { message: text });
  removeTyping();
  if (data.ok) addMsg("bot", data.reply, "StudyMind");
  else addMsg("system", "Error: " + (data.error || "Unknown"));
};

window.handleKey = function(e) {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); window.sendMessage(); }
};
window.autoResize = function(el) {
  el.style.height = "auto";
  el.style.height = Math.min(el.scrollHeight, 130) + "px";
};

window.logout = async function() {
  try { await fetch("/api/logout", { method: "POST" }); } catch(_) {}
  window.location.href = "/login";
};

window.closeAllModals = function() {
  document.getElementById("modalOverlay")?.classList.remove("open");
  document.getElementById("quizModal")?.classList.remove("open");
};
window.openQuizModal = function() {
  document.getElementById("modalOverlay")?.classList.add("open");
  document.getElementById("quizModal")?.classList.add("open");
  setTimeout(() => document.getElementById("quizTopic")?.focus(), 80);
};
window.closeQuizModal = window.closeAllModals;

window.adjustCount = function(delta) {
  const el = document.getElementById("quizCount");
  if (el) el.value = Math.max(1, Math.min(20, parseInt(el.value || 5) + delta));
};

window.startQuiz = async function() {
  const topicEl = document.getElementById("quizTopic");
  const countEl = document.getElementById("quizCount");
  const topic   = topicEl?.value.trim();
  const total   = parseInt(countEl?.value);
  if (!topic) { topicEl?.focus(); return; }
  if (!total || total < 1) return;

  window.closeAllModals();
  quizActive   = true;
  quizTotalRef = total;
  quizTopicRef = topic;
  if (inputBar)     inputBar.style.display     = "none";
  if (quizInputBar) quizInputBar.style.display = "flex";

  addMsg("system", `Starting ${total}-question quiz on "${topic}"…`);
  updateQuizHUD(topic, 0, total, 0);

  const data = await post("/quiz/start", { topic, total });
  if (data.ok) {
    addMsg("quiz-q", `Q${data.number})\n\n${data.question}`, "Question");
    updateQuizHUD(topic, data.number, total, 0);
  } else {
    addMsg("system", "Failed to generate question.");
  }
};

window.sendQuizAnswer = async function(choice) {
  if (!quizActive) return;
  document.querySelectorAll(".opt-btn").forEach(b => b.disabled = true);
  addMsg("user", `Answer: ${choice}`, "You");

  const data = await post("/quiz/answer", { choice });
  if (!data.ok) {
    addMsg("system", "Error processing answer.");
    document.querySelectorAll(".opt-btn").forEach(b => b.disabled = false);
    return;
  }

  if (data.correct) addMsg("correct", "✓ Correct!", "Result");
  else              addMsg("wrong",   `✗ Wrong — correct answer was ${data.correct_answer}`, "Result");

  updateQuizHUD(quizTopicRef, data.quiz_count, data.quiz_total, data.score);

  if (data.finished) {
    quizActive = false;
    if (inputBar)     inputBar.style.display     = "flex";
    if (quizInputBar) quizInputBar.style.display = "none";
    addMsg("system", `Quiz complete! 🎉 Final score: ${data.score} / ${data.quiz_total}`);
    if (data.analysis) addMsg("analysis", data.analysis, "📊 Performance Analysis");
    if (quizHud) quizHud.style.display = "none";
  } else {
    if (data.next_question?.ok) {
      const nq = data.next_question;
      addMsg("quiz-q", `Q${nq.number})\n\n${nq.question}`, "Question");
      updateQuizHUD(quizTopicRef, nq.number, data.quiz_total, data.score);
    }
    document.querySelectorAll(".opt-btn").forEach(b => b.disabled = false);
  }
};

window.openHistory = function() {
  document.getElementById("historyPanel")?.classList.add("open");
  loadHistory(historyTab);
};
window.closeHistory = function() {
  document.getElementById("historyPanel")?.classList.remove("open");
};
window.switchHistoryTab = function(tab) {
  historyTab = tab;
  document.querySelectorAll(".htab").forEach((b, i) =>
    b.classList.toggle("active", (tab === "chat" && i === 0) || (tab === "quiz" && i === 1))
  );
  loadHistory(tab);
};

async function loadHistory(tab) {
  const body = document.getElementById("historyBody");
  if (!body) return;
  body.innerHTML = `<div class="history-loading">Loading…</div>`;
  try {
    if (tab === "chat") {
      const res  = await fetch("/history/chat");
      const data = await res.json();
      renderChatHistory(data.messages || []);
    } else {
      const res  = await fetch("/history/quizzes");
      const data = await res.json();
      renderQuizHistory(data.quizzes || []);
    }
  } catch (e) {
    body.innerHTML = `<div class="history-empty">Failed to load history.</div>`;
  }
}

function renderChatHistory(messages) {
  const body = document.getElementById("historyBody");
  if (!messages.length) {
    body.innerHTML = `<div class="history-empty">No chat history yet.<br>Start a conversation!</div>`;
    return;
  }
  body.innerHTML = "";
  [...messages].reverse().forEach(m => {
    const isUser = m.role === "user";
    const time   = m.timestamp
      ? new Date(m.timestamp).toLocaleString([], { month:"short", day:"numeric", hour:"2-digit", minute:"2-digit" })
      : "";
    const badge  = m.mode && m.mode !== "normal"
      ? `<span class="mode-badge">${m.mode}</span>` : "";
    const preview = (m.content || "").length > 280
      ? esc(m.content.slice(0, 280)) + "…"
      : esc(m.content || "");
    const div = document.createElement("div");
    div.className = `h-msg${isUser ? " user-msg" : ""}`;
    div.innerHTML = `
      <div class="h-msg-meta">
        <span class="h-msg-role">${isUser ? "You" : "StudyMind"}${badge}</span>
        <span class="h-msg-time">${time}</span>
      </div>
      <div class="h-msg-text">${preview}</div>`;
    body.appendChild(div);
  });
}

function renderQuizHistory(quizzes) {
  const body = document.getElementById("historyBody");
  if (!quizzes.length) {
    body.innerHTML = `<div class="history-empty">No quizzes taken yet.<br>Hit "Quiz Me" to start!</div>`;
    return;
  }
  body.innerHTML = "";
  quizzes.forEach(q => {
    const pct   = q.percentage ?? 0;
    const date  = q.finished_at
      ? new Date(q.finished_at).toLocaleString([], { month:"short", day:"numeric", hour:"2-digit", minute:"2-digit" })
      : "";
    const fill  = pct >= 70 ? "good" : pct >= 40 ? "" : "bad";
    const div   = document.createElement("div");
    div.className = "quiz-card";
    div.innerHTML = `
      <div class="quiz-card-header">
        <span class="quiz-card-topic">${esc(q.topic)}</span>
        <span class="quiz-card-date">${date}</span>
      </div>
      <div class="quiz-score-bar">
        <div class="quiz-score-fill ${fill}" style="width:${pct}%"></div>
      </div>
      <div class="quiz-card-stats">
        <span><strong>${q.score}/${q.total}</strong> correct</span>
        <span><strong>${pct}%</strong></span>
      </div>`;
    body.appendChild(div);
  });
}

function esc(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

async function post(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return res.json();
}

});