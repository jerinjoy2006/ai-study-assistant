import os
from groq import Groq
from dotenv import load_dotenv
import re

load_dotenv()

api_key = os.getenv("GROQ_API_KEY")
client = Groq(api_key=api_key)

print("AI Study Assistant (type 'exit' to quit)")
print("Commands: /explain /summarize /ask /quiz /clear\n")

messages = [
    {"role": "system", "content": "You are a strict assistant. Follow format exactly."}
]

mode = "normal"
quiz_active = False
quiz_topic = ""
quiz_total = 0
quiz_count = 0
score = 0
current_question = ""
correct_answer = ""

def generate_question():
    global current_question, correct_answer, quiz_count
    
    prompt = f"""
    Generate one MCQ on {quiz_topic}.
    
    STRICT FORMAT:
    QUESTION: <text>
    A) <option>
    B) <option>
    C) <option>
    D) <option>
    ANSWER: <A/B/C/D>
    
    Do not include any other text or explanations.
    """
    
    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5
    )
    
    raw = response.choices[0].message.content
    match = re.search(r"ANSWER:\s*([A-D])", raw, re.IGNORECASE)
    
    if match:
        correct_answer = match.group(1).upper()
        quiz_count += 1
        
        print(f"\n{quiz_count})")
        for line in raw.split("\n"):
            if "ANSWER:" not in line.upper():
                print(line)
        
        current_question = raw
        return True
    else:
        print("Bot: Format error from AI. Retrying...")
        return generate_question()

while True:
    user_input = input("You: ")
    
    if user_input.lower() == "exit":
        print("Bot: Goodbye")
        break
        
    if user_input == "/clear":
        messages = [messages[0]]
        quiz_active = False
        print("Memory cleared")
        continue
        
    if user_input == "/explain":
        mode = "explain"
        quiz_active = False
        print("Mode: Explain")
        continue
        
    if user_input == "/summarize":
        mode = "summarize"
        quiz_active = False
        print("Mode: Summarize")
        continue
        
    if user_input == "/ask":
        mode = "ask"
        quiz_active = False
        print("Mode: Q&A")
        continue
        
    if user_input == "/quiz":
        quiz_topic = input("Bot: Enter topic: ")
        
        try:
            quiz_total = int(input("Bot: Number of questions: "))
        except ValueError:
            print("Invalid number")
            continue
            
        quiz_count = 0
        score = 0
        quiz_active = True
        current_question = ""
        
        print(f"\nMCQ on {quiz_topic}")
        generate_question()
        continue

    if quiz_active:
        user_choice = user_input.strip().upper()
        if user_choice not in ["A", "B", "C", "D"]:
            print("Please enter A, B, C, or D")
            continue
            
        if user_choice == correct_answer:
            print("Correct")
            score += 1
        else:
            print(f"Wrong. Correct answer is {correct_answer}")
            
        if quiz_count >= quiz_total:
            quiz_active = False
            print("\nQuiz Completed")
            print(f"Score: {score}/{quiz_total}")
            
            analysis_prompt = f"""
            The user took a factual knowledge quiz on the topic of '{quiz_topic}' and scored {score} out of {quiz_total}. 
            
            Provide a strict, study-focused analysis of their trivia and factual knowledge. Do NOT give physical, practical, or sports coaching advice.
            
            Give:
            Knowledge Level (Beginner/Intermediate/Advanced)
            Factual Strengths
            Knowledge Gaps
            One specific tip to study or learn more about the history, facts, or details of this topic.
            """
            
            analysis = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": analysis_prompt}]
            )
            
            print("\nAnalysis:\n")
            print(analysis.choices[0].message.content)
            continue
            
        generate_question()
        continue

    if mode == "explain":
        prompt = f"Explain simply: {user_input}"
    elif mode == "summarize":
        prompt = f"Summarize: {user_input}"
    elif mode == "ask":
        prompt = f"Answer clearly: {user_input}"
    else:
        prompt = user_input
        
    messages.append({"role": "user", "content": prompt})
    
    try:
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=messages
        )
        reply = response.choices[0].message.content
        print("\nBot:", reply, "\n")
        messages.append({"role": "assistant", "content": reply})
    except Exception as e:
        print("Error:", e)