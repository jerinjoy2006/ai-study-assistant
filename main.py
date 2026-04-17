import os
import re
import random
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, Request, Response, Cookie
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from groq import Groq
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv()

groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
mongo_client = AsyncIOMotorClient(MONGO_URI)
db = mongo_client["studymind"]

chat_col      = db["chat_sessions"]    
quiz_col      = db["quiz_results"]     
flashcard_col = db["flashcards"]       

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

SYSTEM_PROMPT = (
    "You are StudyMind, an expert AI study assistant. "
    "Always format responses clearly: use **bold** for key terms, "
    "numbered lists for steps, bullet points for related items, "
    "and blank lines between sections."
)

sessions: dict[str, dict] = {}


def new_session_state() -> dict:
    return {
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}],
        "mode": "normal",
        "quiz_active": False,
        "quiz_topic": "",
        "quiz_total": 0,
        "quiz_count": 0,
        "score": 0,
        "correct_answer": "",
        "asked_questions": [],
        "quiz_start_time": None,
        "quiz_answers": [],  
    }


def get_state(session_id: str) -> dict:
    if session_id not in sessions:
        sessions[session_id] = new_session_state()
    return sessions[session_id]

async def save_chat_message(session_id: str, role: str, content: str, mode: str):
    """Append a message to the chat session document (upsert)."""
    await chat_col.update_one(
        {"session_id": session_id},
        {
            "$push": {
                "messages": {
                    "role": role,
                    "content": content,
                    "mode": mode,
                    "timestamp": datetime.now(timezone.utc),
                }
            },
            "$setOnInsert": {
                "session_id": session_id,
                "created_at": datetime.now(timezone.utc),
            },
            "$set": {"updated_at": datetime.now(timezone.utc)},
        },
        upsert=True,
    )

async def save_quiz_result(session_id: str, state: dict):
    """Save a completed quiz to the quiz_results collection."""
    doc = {
        "session_id": session_id,
        "topic": state["quiz_topic"],
        "score": state["score"],
        "total": state["quiz_total"],
        "percentage": round(state["score"] / state["quiz_total"] * 100, 1) if state["quiz_total"] else 0,
        "answers": state["quiz_answers"],
        "started_at": state.get("quiz_start_time"),
        "finished_at": datetime.now(timezone.utc),
    }
    await quiz_col.insert_one(doc)

async def save_flashcards(session_id: str, topic: str, raw_text: str):
    """Parse and save flashcards generated for a topic."""
    cards = []
    blocks = re.split(r"\*\*Card\s*\d+\*\*", raw_text, flags=re.IGNORECASE)
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        q_m = re.search(r"Q:\s*(.+?)(?=A:|$)", block, re.DOTALL | re.IGNORECASE)
        a_m = re.search(r"A:\s*(.+)",           block, re.DOTALL | re.IGNORECASE)
        if q_m and a_m:
            cards.append({
                "question": q_m.group(1).strip(),
                "answer":   a_m.group(1).strip(),
            })

    if cards:
        await flashcard_col.update_one(
            {"session_id": session_id, "topic": topic},
            {
                "$set": {
                    "session_id": session_id,
                    "topic": topic,
                    "cards": cards,
                    "generated_at": datetime.now(timezone.utc),
                }
            },
            upsert=True,
        )

def build_prompt(mode: str, user_input: str) -> str:
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
    return user_input


def get_chat_history_text(state: dict) -> str:
    lines = []
    for m in state["messages"][1:]:
        role = "Student" if m["role"] == "user" else "StudyMind"
        lines.append(f"{role}: {m['content']}")
    return "\n".join(lines) if lines else "No conversation yet."


def generate_question(state: dict) -> dict:
    topic   = state["quiz_topic"]
    asked   = state["asked_questions"]
    q_num   = state["quiz_count"] + 1
    total   = state["quiz_total"]

    avoid_text = ""
    if asked:
        avoid_text = (
            "\n\nIMPORTANT: You have already asked these — do NOT repeat or ask anything similar:\n"
            + "\n".join(f"- {q}" for q in asked)
            + "\n\nGenerate a COMPLETELY DIFFERENT question on a different aspect or subtopic."
        )

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
    angle = angles[(q_num - 1) % len(angles)]

    prompt = (
        f"Generate question {q_num} of {total} for a quiz on: {topic}\n\n"
        f"Angle for this question: {angle}\n"
        f"{avoid_text}\n\n"
        f"STRICT FORMAT — output ONLY this, nothing else:\n"
        f"QUESTION: <question text>\n"
        f"A) <option>\nB) <option>\nC) <option>\nD) <option>\n"
        f"ANSWER: <A or B or C or D>\n"
    )

    response = groq_client.chat.completions.create(
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

        q_match = re.search(r"QUESTION:\s*(.+)", raw)
        if q_match:
            state["asked_questions"].append(q_match.group(1).strip()[:120])

        lines = [l for l in raw.split("\n") if "ANSWER:" not in l.upper() and l.strip()]
        return {"ok": True, "question": "\n".join(lines), "number": state["quiz_count"], "raw": raw}
    else:
        return generate_question(state)

SESSION_COOKIE = "sm_session"


def get_or_create_session(request: Request, response: Response) -> str:
    session_id = request.cookies.get(SESSION_COOKIE)
    if not session_id:
        session_id = str(uuid.uuid4())
        response.set_cookie(SESSION_COOKIE, session_id, max_age=60 * 60 * 24 * 30) 
    return session_id


@app.get("/", response_class=HTMLResponse)
async def root(request: Request, response: Response):
    session_id = get_or_create_session(request, response)
    get_state(session_id)   # initialise if new
    return templates.TemplateResponse(request, "index.html")


@app.post("/set_mode")
async def set_mode(request: Request, response: Response, body: dict):
    session_id = get_or_create_session(request, response)
    state = get_state(session_id)
    state["mode"] = body.get("mode", "normal")
    state["quiz_active"] = False
    return {"ok": True, "mode": state["mode"]}


@app.post("/chat")
async def chat(request: Request, response: Response, body: dict):
    session_id = get_or_create_session(request, response)
    state = get_state(session_id)
    user_input = body.get("message", "").strip()
    mode = state["mode"]

    if mode == "summarize":
        if len(state["messages"]) <= 1:
            return {"ok": True, "reply": "No conversation to summarize yet. Chat with me first!"}
        history = get_chat_history_text(state)
        summary_prompt = (
            f"Summarize this study session.\n\n"
            f"**Topics Covered:**\n- list each topic\n\n"
            f"**Key Takeaways:**\n- most important facts or answers\n\n"
            f"**What Was Learned:**\n- insights gained\n\n"
            f"Conversation:\n{history}"
        )
        try:
            res = groq_client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[state["messages"][0], {"role": "user", "content": summary_prompt}],
            )
            reply = res.choices[0].message.content
            await save_chat_message(session_id, "assistant", reply, "summarize")
            return {"ok": True, "reply": reply}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    prompt = build_prompt(mode, user_input)
    state["messages"].append({"role": "user", "content": prompt})
    await save_chat_message(session_id, "user", user_input, mode)

    try:
        res = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=state["messages"],
        )
        reply = res.choices[0].message.content
        state["messages"].append({"role": "assistant", "content": reply})
        await save_chat_message(session_id, "assistant", reply, mode)
        if mode == "flashcard":
            await save_flashcards(session_id, user_input, reply)

        return {"ok": True, "reply": reply}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/clear")
async def clear(request: Request, response: Response):
    session_id = get_or_create_session(request, response)
    state = get_state(session_id)
    state.update(new_session_state())
    return {"ok": True}


@app.post("/quiz/start")
async def quiz_start(request: Request, response: Response, body: dict):
    session_id = get_or_create_session(request, response)
    state = get_state(session_id)
    state["quiz_topic"]      = body.get("topic", "")
    state["quiz_total"]      = body.get("total", 5)
    state["quiz_count"]      = 0
    state["score"]           = 0
    state["quiz_active"]     = True
    state["correct_answer"]  = ""
    state["asked_questions"] = []
    state["quiz_answers"]    = []
    state["quiz_start_time"] = datetime.now(timezone.utc)
    return generate_question(state)


@app.post("/quiz/answer")
async def quiz_answer(request: Request, response: Response, body: dict):
    session_id = get_or_create_session(request, response)
    state = get_state(session_id)

    if not state["quiz_active"]:
        return {"ok": False, "error": "No active quiz"}

    choice  = body.get("choice", "").upper()
    correct = state["correct_answer"]
    is_correct = choice == correct
    if is_correct:
        state["score"] += 1
    state["quiz_answers"].append({
        "question_number": state["quiz_count"],
        "chosen":     choice,
        "correct":    correct,
        "is_correct": is_correct,
    })

    finished = state["quiz_count"] >= state["quiz_total"]
    analysis_text = None

    if finished:
        state["quiz_active"] = False
        await save_quiz_result(session_id, state)

        ap = (
            f"The student completed a quiz on '{state['quiz_topic']}' "
            f"and scored {state['score']} out of {state['quiz_total']}.\n\n"
            f"**Knowledge Level:** Beginner / Intermediate / Advanced (pick one, justify briefly)\n\n"
            f"**Strengths:** What they likely know well\n\n"
            f"**Gaps to Address:** Specific areas to review\n\n"
            f"**Study Tip:** One concrete, actionable recommendation\n\nKeep it encouraging but honest."
        )
        ar = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": ap}],
        )
        analysis_text = ar.choices[0].message.content

    next_question = None if finished else generate_question(state)

    return {
        "ok": True,
        "correct": is_correct,
        "correct_answer": correct,
        "score": state["score"],
        "quiz_count": state["quiz_count"],
        "quiz_total": state["quiz_total"],
        "finished": finished,
        "analysis": analysis_text,
        "next_question": next_question,
    }

@app.get("/history/chat")
async def history_chat(request: Request, response: Response, limit: int = 50):
    """Return recent chat messages for this session."""
    session_id = get_or_create_session(request, response)
    doc = await chat_col.find_one({"session_id": session_id})
    if not doc:
        return {"ok": True, "messages": []}
    messages = doc.get("messages", [])[-limit:]
    for m in messages:
        if "timestamp" in m:
            m["timestamp"] = m["timestamp"].isoformat()
    return {"ok": True, "session_id": session_id, "messages": messages}


@app.get("/history/quizzes")
async def history_quizzes(request: Request, response: Response):
    """Return all quiz results for this session."""
    session_id = get_or_create_session(request, response)
    cursor = quiz_col.find(
        {"session_id": session_id},
        {"_id": 0},
        sort=[("finished_at", -1)],
    )
    results = []
    async for doc in cursor:
        for key in ("started_at", "finished_at"):
            if doc.get(key):
                doc[key] = doc[key].isoformat()
        results.append(doc)
    return {"ok": True, "quizzes": results}


@app.get("/history/flashcards")
async def history_flashcards(request: Request, response: Response):
    """Return all flashcard sets for this session."""
    session_id = get_or_create_session(request, response)
    cursor = flashcard_col.find(
        {"session_id": session_id},
        {"_id": 0},
        sort=[("generated_at", -1)],
    )
    sets = []
    async for doc in cursor:
        if doc.get("generated_at"):
            doc["generated_at"] = doc["generated_at"].isoformat()
        sets.append(doc)
    return {"ok": True, "flashcard_sets": sets}


@app.get("/stats")
async def stats(request: Request, response: Response):
    """Quick stats for this session."""
    session_id = get_or_create_session(request, response)

    chat_doc   = await chat_col.find_one({"session_id": session_id})
    quiz_count = await quiz_col.count_documents({"session_id": session_id})
    fc_count   = await flashcard_col.count_documents({"session_id": session_id})

    total_messages = len(chat_doc.get("messages", [])) if chat_doc else 0

    pipeline = [
        {"$match": {"session_id": session_id}},
        {"$group": {"_id": None, "avg_pct": {"$avg": "$percentage"}, "best_pct": {"$max": "$percentage"}}},
    ]
    agg = await quiz_col.aggregate(pipeline).to_list(1)
    avg_score  = round(agg[0]["avg_pct"], 1) if agg else None
    best_score = round(agg[0]["best_pct"], 1) if agg else None

    return {
        "ok": True,
        "session_id": session_id,
        "total_messages": total_messages,
        "quizzes_taken": quiz_count,
        "flashcard_sets": fc_count,
        "avg_quiz_score_pct": avg_score,
        "best_quiz_score_pct": best_score,
    }


@app.get("/state")
async def get_state_route(request: Request, response: Response):
    session_id = get_or_create_session(request, response)
    state = get_state(session_id)
    return {
        "mode": state["mode"],
        "quiz_active": state["quiz_active"],
        "quiz_topic": state["quiz_topic"],
        "quiz_count": state["quiz_count"],
        "quiz_total": state["quiz_total"],
        "score": state["score"],
        "history_length": len(state["messages"]) - 1,
    }