# AI-Powered Multilingual Personalized Tour Guide

Flask + vanilla JS + SQLite. An LLM (Google Gemini) personalizes historical explanations by
**age group, interests, language and available time**, with a follow-up chatbot and an interest-based tour planner.

## Structure
```
app.py            Flask routes, validation, prompt building, LLM calls, SQLite
destinations.py   Sample destinations (used for suggestions and planning)
templates/        index.html
static/           style.css, app.js
.env.example      Environment template
```

## Run locally
```bash
python -m venv venv && source venv/bin/activate     # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                 # then add your API key
python app.py                                        # open http://127.0.0.1:5000
```
Get a free Gemini key at https://aistudio.google.com/apikey and paste it into `.env`. If you hit a rate limit on the free tier, wait a minute, or change `GEMINI_MODEL`. If you get a 404 model error, set `GEMINI_MODEL` in `.env` to a current model name from https://ai.google.dev/gemini-api/docs/models.

## How personalization works
`system_prompt()` in `app.py` combines the visitor's name, age-group tone (child → playful and simple, enthusiast → scholarly),
interests, language, and a word budget (~8 words per available minute). The same prompt is reused for chat, so follow-ups stay personalized.
Chat history is stored in SQLite per browser session.

## Notes
- API keys live only in `.env` on the server; the frontend never sees them.
- All input is validated server-side; API failures (missing key, timeout, quota, blocked output) return friendly messages.
- `/api/plan` works without any API key. Tour and chat need one.
- Accuracy: the prompt forbids inventing facts, but LLMs can err, so verify critical details, especially in lower-resource languages.
- Add photos by replacing the gradient cards in `static/app.js` with images in `static/img/`.
- For production, run behind gunicorn (`gunicorn app:app`) and add rate limiting.
