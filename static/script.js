let currentMode = "normal";
let quizActive  = false;
let quizTotalRef = 0;
let quizTopicRef = "";

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
  normal:    { label: "💬 General Chat",   sub: "Ask me anything",               hint: "Press Enter to send · Shift+Enter for new line" },
  explain:   { label: "💡 Explain Mode",   sub: "Enter a concept to explain",     hint: "I'll break it down with analogies & key points" },
  deep_dive: { label: "🔬 Deep Dive Mode", sub: "Enter a topic for deep analysis", hint: "In-depth academic breakdown" },
  flashcard: { label: "🃏 Flashcard Mode", sub: "Enter a topic for flashcards",   hint: "I'll generate 5 study cards" },
};

/* ── Markdown renderer ── */
function renderMarkdown(text) {
  const div = document.createElement("div");
  const lines = text.split("\n");
  let html = "";

  for (const line of lines) {
    // Bold-only heading line e.g. **Key Points:**
    if (/^\*\*[^*]+\*\*[:\s]*$/.test(line.trim())) {
      html += `<div class="md-h3">${line.trim().replace(/\*\*/g, "")}</div>`;
      continue;
    }
    // Numbered list
    const numM = line.match(/^(\d+)\.\s+(.+)/);
    if (numM) {
      html += `<div class="md-num"><span class="num">${numM[1]}.</span><span>${inline(numM[2])}</span></div>`;
      continue;
    }
    // Bullet
    const bulM = line.match(/^[-*]\s+(.+)/);
    if (bulM) {
      html += `<div class="md-li"><span>${inline(bulM[1])}</span></div>`;
      continue;
    }
    // HR
    if (/^---+$/.test(line.trim())) { html += `<div class="md-sep"></div>`; continue; }
    // Empty
    if (!line.trim()) { html += "<br>"; continue; }
    // Normal
    html += `<span>${inline(line)}</span><br>`;
  }
  div.innerHTML = html;
  return div;
}

function inline(t) {
  return t
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g,     "<em>$1</em>")
    .replace(/`(.+?)`/g,       '<span class="md-code">$1</span>');
}

/* ── Helpers ── */
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
    lbl.className = "msg-label";
    lbl.textContent = label;
    wrap.appendChild(lbl);
  }
  const bubble = document.createElement("div");
  bubble.className = "msg-bubble";
  if (type === "bot" || type === "analysis") {
    bubble.appendChild(renderMarkdown(text));
  } else {
    bubble.textContent = text;
  }
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
  const cfg = MODE_CONFIG[mode] || MODE_CONFIG.normal;
  modePill.textContent = cfg.label;
  topbarSub.textContent = cfg.sub;
  document.getElementById("inputHint").textContent = cfg.hint;
  document.querySelectorAll(".nav-btn[data-mode]").forEach(b =>
    b.classList.toggle("active", b.dataset.mode === mode)
  );
}

function updateQuizHUD(topic, count, total, score) {
  quizHud.style.display = "flex";
  hudTopic.textContent    = "📚 " + topic;
  hudProgress.textContent = `Q ${count} / ${total}`;
  hudScore.textContent    = `✓ ${score}`;
}

/* ── Mode switch ── */
async function setMode(mode) {
  if (quizActive) { addMsg("system", "Finish the quiz before switching modes."); return; }
  await post("/set_mode", { mode });
  setModeUI(mode);
  addMsg("system", `Switched to ${MODE_CONFIG[mode]?.label || mode}`);
  userInput.focus();
}

function quickStart(mode) { setMode(mode); userInput.focus(); }

/* ── Summarize session ── */
async function summarizeSession() {
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
}

/* ── Clear ── */
async function clearMemory() {
  await post("/clear", {});
  chatArea.innerHTML = "";
  const w = document.createElement("div");
  w.id = "welcomeState"; w.className = "welcome-state";
  w.innerHTML = `
    <div class="welcome-icon">✦</div>
    <h2>Welcome to StudyMind</h2>
    <p>Your AI-powered study companion. Choose a mode from the sidebar or just start chatting.</p>
    <div class="quick-actions">
      <button onclick="quickStart('explain')" class="quick-btn">💡 Explain a concept</button>
      <button onclick="quickStart('deep_dive')" class="quick-btn">🔬 Deep dive a topic</button>
      <button onclick="quickStart('flashcard')" class="quick-btn">🃏 Make flashcards</button>
      <button onclick="openQuizModal()" class="quick-btn">🎯 Take a quiz</button>
    </div>`;
  chatArea.appendChild(w);
  quizActive = false;
  quizHud.style.display = "none";
  inputBar.style.display    = "flex";
  quizInputBar.style.display = "none";
  setModeUI("normal");
}

/* ── Chat ── */
async function sendMessage() {
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
}

function handleKey(e) {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); }
}
function autoResize(el) {
  el.style.height = "auto";
  el.style.height = Math.min(el.scrollHeight, 130) + "px";
}

/* ── Quiz modal ── */
function openQuizModal() {
  document.getElementById("modalOverlay").classList.add("open");
  document.getElementById("quizModal").classList.add("open");
  setTimeout(() => document.getElementById("quizTopic").focus(), 80);
}
function closeQuizModal() {
  document.getElementById("modalOverlay").classList.remove("open");
  document.getElementById("quizModal").classList.remove("open");
}
function adjustCount(delta) {
  const el = document.getElementById("quizCount");
  el.value = Math.max(1, Math.min(20, parseInt(el.value || 5) + delta));
}

async function startQuiz() {
  const topic = document.getElementById("quizTopic").value.trim();
  const total = parseInt(document.getElementById("quizCount").value);
  if (!topic) { document.getElementById("quizTopic").focus(); return; }
  if (!total || total < 1) return;
  closeQuizModal();
  quizActive = true; quizTotalRef = total; quizTopicRef = topic;
  inputBar.style.display    = "none";
  quizInputBar.style.display = "flex";
  addMsg("system", `Starting ${total}-question quiz on "${topic}"…`);
  updateQuizHUD(topic, 0, total, 0);
  const data = await post("/quiz/start", { topic, total });
  if (data.ok) {
    addMsg("quiz-q", `Q${data.number})\n\n${data.question}`, "Question");
    updateQuizHUD(topic, data.number, total, 0);
  } else {
    addMsg("system", "Failed to generate question.");
  }
}

/* ── Quiz answer ── */
async function sendQuizAnswer(choice) {
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
  else addMsg("wrong", `✗ Wrong — correct answer was ${data.correct_answer}`, "Result");

  updateQuizHUD(quizTopicRef, data.quiz_count, data.quiz_total, data.score);

  if (data.finished) {
    quizActive = false;
    inputBar.style.display    = "flex";
    quizInputBar.style.display = "none";
    addMsg("system", `Quiz complete! 🎉 Final score: ${data.score} / ${data.quiz_total}`);
    if (data.analysis) addMsg("analysis", data.analysis, "📊 Performance Analysis");
    quizHud.style.display = "none";
  } else {
    if (data.next_question?.ok) {
      const nq = data.next_question;
      addMsg("quiz-q", `Q${nq.number})\n\n${nq.question}`, "Question");
      updateQuizHUD(quizTopicRef, nq.number, data.quiz_total, data.score);
    }
    document.querySelectorAll(".opt-btn").forEach(b => b.disabled = false);
  }
}

/* ── Fetch helper ── */
async function post(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return res.json();
}