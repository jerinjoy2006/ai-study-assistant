import os
import re
import random
from datetime import datetime, timezone, timedelta

from fastapi import FastAPI, Request, Response, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.security import OAuth2PasswordBearer
from groq import Groq
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from passlib.context import CryptContext
from jose import JWTError, jwt

load_dotenv()

GROQ_API_KEY  = os.getenv("GROQ_API_KEY")
MONGO_URI     = os.getenv("MONGO_URI", "mongodb://localhost:27017")
SECRET_KEY    = os.getenv("SECRET_KEY", "change-this-secret-in-production-please")
ALGORITHM     = "HS256"
TOKEN_EXPIRE_DAYS = 30

groq_client  = Groq(api_key=GROQ_API_KEY)
mongo_client = AsyncIOMotorClient(MONGO_URI)
db           = mongo_client["studymind"]

users_col = db["users"]
chat_col  = db["chat_sessions"]
quiz_col  = db["quiz_results"]

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

SYSTEM_PROMPT = (
    "You are StudyMind, an expert AI study assistant. "
    "Always format responses clearly: use **bold** for key terms, "
    "numbered lists for steps, bullet points for related items, "
    "and blank lines between sections."
)

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

user_states: dict[str, dict] = {}

def new_user_state() -> dict:
    return {
        "messages":        [{"role": "system", "content": SYSTEM_PROMPT}],
        "mode":            "normal",
        "quiz_active":     False,
        "quiz_topic":      "",
        "quiz_total":      0,
        "quiz_count":      0,
        "score":           0,
        "correct_answer":  "",
        "asked_questions": [],
        "quiz_start_time": None,
        "quiz_answers":    [],
    }

def get_user_state(user_id: str) -> dict:
    if user_id not in user_states:
        user_states[user_id] = new_user_state()
    return user_states[user_id]

def hash_password(plain: str) -> str:
    return pwd_ctx.hash(plain)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_ctx.verify(plain, hashed)

def create_token(data: dict) -> str:
    payload = data.copy()
    payload["exp"] = datetime.now(timezone.utc) + timedelta(days=TOKEN_EXPIRE_DAYS)
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None

async def get_current_user(request: Request):
    token = request.cookies.get("sm_token")
    if not token:
        return None
    payload = decode_token(token)
    if not payload:
        return None
    user = await users_col.find_one({"username": payload.get("sub")}, {"_id": 1, "username": 1, "email": 1})
    return user

async def require_user(request: Request):
    user = await get_current_user(request)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user

async def save_chat_message(user_id: str, role: str, content: str, mode: str):
    await chat_col.update_one(
        {"user_id": user_id},
        {
            "$push": {"messages": {
                "role": role, "content": content,
                "mode": mode, "timestamp": datetime.now(timezone.utc),
            }},
            "$setOnInsert": {"user_id": user_id, "created_at": datetime.now(timezone.utc)},
            "$set":          {"updated_at": datetime.now(timezone.utc)},
        },
        upsert=True,
    )

async def save_quiz_result(user_id: str, state: dict):
    await quiz_col.insert_one({
        "user_id":    user_id,
        "topic":      state["quiz_topic"],
        "score":      state["score"],
        "total":      state["quiz_total"],
        "percentage": round(state["score"] / state["quiz_total"] * 100, 1) if state["quiz_total"] else 0,
        "answers":    state["quiz_answers"],
        "started_at": state.get("quiz_start_time"),
        "finished_at": datetime.now(timezone.utc),
    })

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
    topic = state["quiz_topic"]
    asked = state["asked_questions"]
    q_num = state["quiz_count"] + 1
    total = state["quiz_total"]

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
    raw   = response.choices[0].message.content.strip()
    match = re.search(r"ANSWER:\s*([A-D])", raw, re.IGNORECASE)

    if match:
        state["correct_answer"] = match.group(1).upper()
        state["quiz_count"]    += 1
        q_m = re.search(r"QUESTION:\s*(.+)", raw)
        if q_m:
            state["asked_questions"].append(q_m.group(1).strip()[:120])
        lines = [l for l in raw.split("\n") if "ANSWER:" not in l.upper() and l.strip()]
        return {"ok": True, "question": "\n".join(lines), "number": state["quiz_count"]}
    else:
        return generate_question(state)

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse(request, "index.html", {"username": user["username"]})

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    user = await get_current_user(request)
    if user:
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse(request, "auth.html", {"mode": "login", "error": None})

@app.get("/signup", response_class=HTMLResponse)
async def signup_page(request: Request):
    user = await get_current_user(request)
    if user:
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse(request, "auth.html", {"mode": "signup", "error": None})

@app.post("/api/signup")
async def api_signup(request: Request):
    body     = await request.json()
    username = body.get("username", "").strip().lower()
    email    = body.get("email", "").strip().lower()
    password = body.get("password", "")

    if not username or not email or not password:
        return {"ok": False, "error": "All fields are required."}
    if len(username) < 3:
        return {"ok": False, "error": "Username must be at least 3 characters."}
    if len(password) < 6:
        return {"ok": False, "error": "Password must be at least 6 characters."}

    existing = await users_col.find_one({"$or": [{"username": username}, {"email": email}]})
    if existing:
        if existing.get("username") == username:
            return {"ok": False, "error": "Username already taken."}
        return {"ok": False, "error": "Email already registered."}

    await users_col.insert_one({
        "username":        username,
        "email":           email,
        "hashed_password": hash_password(password),
        "created_at":      datetime.now(timezone.utc),
    })

    token    = create_token({"sub": username})
    response = Response(content='{"ok":true}', media_type="application/json")
    response.set_cookie("sm_token", token, max_age=TOKEN_EXPIRE_DAYS * 86400, httponly=True, samesite="lax")
    return response

@app.post("/api/login")
async def api_login(request: Request):
    body     = await request.json()
    username = body.get("username", "").strip().lower()
    password = body.get("password", "")

    user = await users_col.find_one({"username": username})
    if not user or not verify_password(password, user["hashed_password"]):
        return {"ok": False, "error": "Invalid username or password."}

    token    = create_token({"sub": username})
    response = Response(content='{"ok":true}', media_type="application/json")
    response.set_cookie("sm_token", token, max_age=TOKEN_EXPIRE_DAYS * 86400, httponly=True, samesite="lax")
    return response

@app.post("/api/logout")
async def api_logout():
    response = Response(content='{"ok":true}', media_type="application/json")
    response.delete_cookie("sm_token")
    return response

@app.get("/api/me")
async def api_me(request: Request):
    user = await get_current_user(request)
    if not user:
        return {"ok": False}
    return {"ok": True, "username": user["username"], "email": user.get("email", "")}

@app.post("/set_mode")
async def set_mode(request: Request, body: dict, user=Depends(require_user)):
    state = get_user_state(str(user["_id"]))
    state["mode"] = body.get("mode", "normal")
    state["quiz_active"] = False
    return {"ok": True, "mode": state["mode"]}

@app.post("/chat")
async def chat(request: Request, body: dict, user=Depends(require_user)):
    user_id    = str(user["_id"])
    state      = get_user_state(user_id)
    user_input = body.get("message", "").strip()
    mode       = state["mode"]

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
            res   = groq_client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[state["messages"][0], {"role": "user", "content": summary_prompt}],
            )
            reply = res.choices[0].message.content
            await save_chat_message(user_id, "assistant", reply, "summarize")
            return {"ok": True, "reply": reply}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    prompt = build_prompt(mode, user_input)
    state["messages"].append({"role": "user", "content": prompt})
    await save_chat_message(user_id, "user", user_input, mode)

    try:
        res   = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=state["messages"],
        )
        reply = res.choices[0].message.content
        state["messages"].append({"role": "assistant", "content": reply})
        await save_chat_message(user_id, "assistant", reply, mode)
        return {"ok": True, "reply": reply}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.post("/clear")
async def clear(request: Request, user=Depends(require_user)):
    user_id = str(user["_id"])
    user_states[user_id] = new_user_state()
    return {"ok": True}

@app.post("/quiz/start")
async def quiz_start(request: Request, body: dict, user=Depends(require_user)):
    state = get_user_state(str(user["_id"]))
    state.update({
        "quiz_topic":      body.get("topic", ""),
        "quiz_total":      body.get("total", 5),
        "quiz_count":      0,
        "score":           0,
        "quiz_active":     True,
        "correct_answer":  "",
        "asked_questions": [],
        "quiz_answers":    [],
        "quiz_start_time": datetime.now(timezone.utc),
    })
    return generate_question(state)

@app.post("/quiz/answer")
async def quiz_answer(request: Request, body: dict, user=Depends(require_user)):
    user_id = str(user["_id"])
    state   = get_user_state(user_id)
    if not state["quiz_active"]:
        return {"ok": False, "error": "No active quiz"}

    choice     = body.get("choice", "").upper()
    correct    = state["correct_answer"]
    is_correct = choice == correct
    if is_correct:
        state["score"] += 1

    state["quiz_answers"].append({
        "question_number": state["quiz_count"],
        "chosen":           choice,
        "correct":          correct,
        "is_correct":       is_correct,
    })

    finished      = state["quiz_count"] >= state["quiz_total"]
    analysis_text = None

    if finished:
        state["quiz_active"] = False
        await save_quiz_result(user_id, state)
        ap = (
            f"The student completed a quiz on '{state['quiz_topic']}' "
            f"and scored {state['score']} out of {state['quiz_total']}.\n\n"
            f"**Knowledge Level:** Beginner / Intermediate / Advanced (pick one, justify briefly)\n\n"
            f"**Strengths:** What they likely know well\n\n"
            f"**Gaps to Address:** Specific areas to review\n\n"
            f"**Study Tip:** One concrete, actionable recommendation\n\nKeep it encouraging but honest."
        )
        ar            = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": ap}],
        )
        analysis_text = ar.choices[0].message.content

    next_question = None if finished else generate_question(state)
    return {
        "ok": True, "correct": is_correct, "correct_answer": correct,
        "score": state["score"], "quiz_count": state["quiz_count"],
        "quiz_total": state["quiz_total"], "finished": finished,
        "analysis": analysis_text, "next_question": next_question,
    }

@app.get("/history/chat")
async def history_chat(request: Request, user=Depends(require_user), limit: int = 50):
    user_id = str(user["_id"])
    doc     = await chat_col.find_one({"user_id": user_id})
    if not doc:
        return {"ok": True, "messages": []}
    messages = doc.get("messages", [])[-limit:]
    for m in messages:
        if "timestamp" in m:
            m["timestamp"] = m["timestamp"].isoformat()
    return {"ok": True, "messages": messages}

@app.get("/history/quizzes")
async def history_quizzes(request: Request, user=Depends(require_user)):
    user_id = str(user["_id"])
    results = []
    async for doc in quiz_col.find({"user_id": user_id}, {"_id": 0}, sort=[("finished_at", -1)]):
        for k in ("started_at", "finished_at"):
            if doc.get(k):
                doc[k] = doc[k].isoformat()
        results.append(doc)
    return {"ok": True, "quizzes": results}

@app.get("/stats")
async def stats(request: Request, user=Depends(require_user)):
    user_id    = str(user["_id"])
    chat_doc   = await chat_col.find_one({"user_id": user_id})
    quiz_count = await quiz_col.count_documents({"user_id": user_id})
    total_msgs = len(chat_doc.get("messages", [])) if chat_doc else 0
    pipeline   = [
        {"$match": {"user_id": user_id}},
        {"$group": {"_id": None, "avg_pct": {"$avg": "$percentage"}, "best_pct": {"$max": "$percentage"}}},
    ]
    agg = await quiz_col.aggregate(pipeline).to_list(1)
    return {
        "ok":                               True,
        "username":            user["username"],
        "total_messages":      total_msgs,
        "quizzes_taken":       quiz_count,
        "avg_quiz_score_pct":  round(agg[0]["avg_pct"],  1) if agg else None,
        "best_quiz_score_pct": round(agg[0]["best_pct"], 1) if agg else None,
    }

@app.get("/state")
async def get_state_route(request: Request, user=Depends(require_user)):
    state = get_user_state(str(user["_id"]))
    return {
        "mode":           state["mode"],
        "quiz_active":    state["quiz_active"],
        "quiz_topic":     state["quiz_topic"],
        "quiz_count":     state["quiz_count"],
        "quiz_total":     state["quiz_total"],
        "score":          state["score"],
        "history_length": len(state["messages"]) - 1,
    }