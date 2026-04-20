# StudyMind AI

An intelligent AI-powered study assistant that helps users learn, revise, and test their knowledge through interactive chat, flashcards, and quizzes.

**Live Demo:** https://ai-study-assistant-nbhu.onrender.com

## Features

### Authentication System

* Secure **user signup & login**
* Password hashing using `bcrypt`
* JWT-based authentication with cookies
* Protected routes for user-specific data

### AI Study Assistant

* Powered by Groq (LLaMA 3.1)
* Multiple learning modes:

  *  General Chat
  *  Explain Mode
  *  Deep Dive Mode
  *  Flashcard Generation
  *  Session Summarization

  
### Quiz System

* Generate quizzes on any topic
* Multiple-choice questions with:

  * Score tracking
  * Progress tracking
  * Performance analysis (AI-generated)
* Prevents repeated questions using smart tracking

### User Dashboard & History

* Chat history storage (MongoDB)
* Quiz history with:

  * Scores
  * Percentages
  * Performance trends
  
Real-Time UI

* Clean chat interface
* Typing indicators
* Markdown-style formatting
* Interactive quiz UI

## Tech Stack

### Backend

* FastAPI
* MongoDB (Motor - async driver)
* JWT Authentication (`python-jose`)
* Password hashing (`passlib`, `bcrypt`)

### AI Integration

* Groq API (LLaMA 3.1)

### Frontend

* HTML, CSS, JavaScript (Vanilla)
* Jinja2 Templates

### Deployment

* Render

## ⚙️ Environment Variables

Create a `.env` file:

```env
GROQ_API_KEY=your_groq_api_key
MONGO_URI=your_mongodb_uri
SECRET_KEY=your_secret_key
```

---

## Running Locally

```bash
# Clone the repository
git clone https://github.com/your-username/studymind-ai.git

# Navigate into project
cd studymind-ai

# Install dependencies
pip install -r requirements.txt

# Run server
uvicorn main:app --reload
```

---

## Security Practices

* API keys stored in environment variables
* `.env` file excluded using `.gitignore`
* Passwords hashed using bcrypt
* JWT tokens with expiration

## Future Improvements

* Rate limiting for API protection
* Email verification system
* Leaderboard for quizzes
* Mobile responsiveness improvements
* AI-powered personalized study plans


## Acknowledgements

* Groq API for fast AI inference
* FastAPI for backend framework
* MongoDB for database


##  Contact

Feel free to connect or give feedback!

---

⭐ If you like this project, consider giving it a star!
