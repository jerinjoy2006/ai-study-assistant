import os
import re
import random
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))
app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

state = {
    "messages": [{"role": "system", "content": (
        "You are StudyMind, an expert AI study assistant. "
        "Always format responses clearly: use **bold** for key terms, "
        "numbered lists for steps, bullet points for related items, "
        "and blank lines between sections."
    )}],
    "mode": "normal",
    "quiz_active": False,
    "quiz_topic": "",
    "quiz_total": 0,
    "quiz_count": 0,
    "score": 0,
    "correct_answer": "",
    "asked_questions": [],   # track previously asked questions to avoid repeats
}


def get_chat_history_text():
    lines = []
    for m in state["messages"][1:]:
        role = "Student" if m["role"] == "user" else "StudyMind"
        lines.append(f"{role}: {m['content']}")
    return "\n".join(lines) if lines else "No conversation yet."


def build_prompt(mode, user_input):
    if mode == "explain":
        return (
            f"Explain the following concept clearly and simply.\n\n"
            f"Structure your response:\n"
            f"1. **What it is** - one sentence definition\n"
            f"2. **How it works** - key mechanism or idea\n"
            f"3. **Simple analogy** - a real-world comparison\n"
            f"4. **Key points to remember** - 3-4 bullet points\n\n"
            f"Concept: {user_input}"
        )
    elif mode == "deep_dive":
        return (
            f"Give an in-depth, thorough analysis of the following topic.\n\n"
            f"Structure your response:\n"
            f"1. **Overview** - definition and scope\n"
            f"2. **Core principles** - fundamental ideas with detail\n"
            f"3. **Components / Subtopics** - break it into parts\n"
            f"4. **Real-world applications** - where and how it is used\n"
            f"5. **Common misconceptions** - what people get wrong\n"
            f"6. **Further study** - what to explore next\n\n"
            f"Topic: {user_input}"
        )
    elif mode == "flashcard":
        return (
            f"Generate 5 flashcards for studying the following topic.\n\n"
            f"Format each card exactly like this:\n\n"
            f"**Card 1**\nQ: [question]\nA: [concise answer]\n\n"
            f"Continue for all 5 cards.\n\nTopic: {user_input}"
        )
    else:
        return user_input


def generate_question():
    topic = state["quiz_topic"]
    asked = state["asked_questions"]
    question_num = state["quiz_count"] + 1
    total = state["quiz_total"]

    # Build avoidance instruction from previously asked questions
    avoid_text = ""
    if asked:
        avoid_text = (
            f"\n\nIMPORTANT: You have already asked these questions — do NOT repeat or ask anything similar:\n"
            + "\n".join(f"- {q}" for q in asked)
            + "\n\nGenerate a COMPLETELY DIFFERENT question on a different aspect or subtopic."
        )

    # Inject randomness via varied angle instructions
    angles = [
        "Focus on a historical fact or date.",
        "Focus on a definition or terminology.",
        "Focus on a cause-and-effect relationship.",
        "Focus on a key person, inventor, or figure.",
        "Focus on a process or sequence of steps.",
        "Focus on a comparison between two things.",
        "Focus on an application or real-world example.",
        "Focus on an exception, anomaly, or surprising fact.",
        "Focus on a consequence or impact.",
        "Focus on a specific number, measurement, or statistic.",
    ]
    angle = angles[(question_num - 1) % len(angles)]

    prompt = (
        f"Generate question {question_num} of {total} for a quiz on: {topic}\n\n"
        f"Angle for this question: {angle}\n"
        f"{avoid_text}\n\n"
        f"STRICT FORMAT — output ONLY this, nothing else:\n"
        f"QUESTION: <question text>\n"
        f"A) <option>\n"
        f"B) <option>\n"
        f"C) <option>\n"
        f"D) <option>\n"
        f"ANSWER: <A or B or C or D>\n"
    )

    # High temperature for variety
    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}],
        temperature=1.0,
        seed=random.randint(0, 99999),
    )
    raw = response.choices[0].message.content.strip()
    match = re.search(r"ANSWER:\s*([A-D])", raw, re.IGNORECASE)

    if match:
        state["correct_answer"] = match.group(1).upper()
        state["quiz_count"] += 1

        # Extract just the question stem for dedup tracking
        q_match = re.search(r"QUESTION:\s*(.+)", raw)
        if q_match:
            state["asked_questions"].append(q_match.group(1).strip()[:120])

        lines = [l for l in raw.split("\n") if "ANSWER:" not in l.upper() and l.strip()]
        return {"ok": True, "question": "\n".join(lines), "number": state["quiz_count"]}
    else:
        # Retry once on bad format
        return generate_question()


# ── Routes ──

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.post("/set_mode")
async def set_mode(body: dict):
    mode = body.get("mode", "normal")
    state["mode"] = mode
    state["quiz_active"] = False
    return {"ok": True, "mode": mode}


@app.post("/chat")
async def chat(body: dict):
    user_input = body.get("message", "").strip()
    mode = state["mode"]

    if mode == "summarize":
        if len(state["messages"]) <= 1:
            return {"ok": True, "reply": "No conversation to summarize yet. Chat with me first!"}
        history = get_chat_history_text()
        summary_prompt = (
            f"Summarize this study session.\n\n"
            f"**Topics Covered:**\n- list each topic\n\n"
            f"**Key Takeaways:**\n- most important facts or answers\n\n"
            f"**What Was Learned:**\n- insights gained\n\n"
            f"Conversation:\n{history}"
        )
        try:
            res = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[state["messages"][0], {"role": "user", "content": summary_prompt}],
            )
            return {"ok": True, "reply": res.choices[0].message.content}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    prompt = build_prompt(mode, user_input)
    state["messages"].append({"role": "user", "content": prompt})
    try:
        res = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=state["messages"],
        )
        reply = res.choices[0].message.content
        state["messages"].append({"role": "assistant", "content": reply})
        return {"ok": True, "reply": reply}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/clear")
async def clear():
    state["messages"] = [state["messages"][0]]
    state["quiz_active"] = False
    state["mode"] = "normal"
    state["asked_questions"] = []
    return {"ok": True}


@app.post("/quiz/start")
async def quiz_start(body: dict):
    state["quiz_topic"] = body.get("topic", "")
    state["quiz_total"] = body.get("total", 5)
    state["quiz_count"] = 0
    state["score"] = 0
    state["quiz_active"] = True
    state["correct_answer"] = ""
    state["asked_questions"] = []   # reset tracking for new quiz
    return generate_question()


@app.post("/quiz/answer")
async def quiz_answer(body: dict):
    if not state["quiz_active"]:
        return {"ok": False, "error": "No active quiz"}

    choice = body.get("choice", "").upper()
    correct = state["correct_answer"]
    is_correct = choice == correct
    if is_correct:
        state["score"] += 1

    finished = state["quiz_count"] >= state["quiz_total"]
    analysis_text = None

    if finished:
        state["quiz_active"] = False
        ap = (
            f"The student completed a quiz on '{state['quiz_topic']}' "
            f"and scored {state['score']} out of {state['quiz_total']}.\n\n"
            f"**Knowledge Level:** Beginner / Intermediate / Advanced (pick one, justify briefly)\n\n"
            f"**Strengths:** What they likely know well\n\n"
            f"**Gaps to Address:** Specific areas to review\n\n"
            f"**Study Tip:** One concrete, actionable recommendation\n\nKeep it encouraging but honest."
        )
        ar = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": ap}],
        )
        analysis_text = ar.choices[0].message.content

    next_question = None if finished else generate_question()

    return {
        "ok": True, "correct": is_correct, "correct_answer": correct,
        "score": state["score"], "quiz_count": state["quiz_count"],
        "quiz_total": state["quiz_total"], "finished": finished,
        "analysis": analysis_text, "next_question": next_question,
    }


@app.get("/state")
async def get_state():
    return {
        "mode": state["mode"], "quiz_active": state["quiz_active"],
        "quiz_topic": state["quiz_topic"], "quiz_count": state["quiz_count"],
        "quiz_total": state["quiz_total"], "score": state["score"],
        "history_length": len(state["messages"]) - 1,
    }