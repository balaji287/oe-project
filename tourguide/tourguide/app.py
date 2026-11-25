import os, sqlite3, requests
from flask import Flask, jsonify, request, render_template
from dotenv import load_dotenv
from destinations import DESTINATIONS

load_dotenv()
app = Flask(__name__)
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tourguide.db")

AGE_GROUPS = {
 "child": "a child (under 12). Use very simple words, short sentences, fun comparisons, a playful tone and one small quiz question at the end.",
 "teen": "a teenager (13-19). Be engaging and relatable, with vivid stories and interesting 'wow' facts.",
 "adult": "an adult (20-59). Give detailed, well-structured historical context with dates, rulers, and architectural terms.",
 "senior": "a senior visitor (60+). Use a calm, respectful pace, clear language, and rich historical and cultural background.",
 "enthusiast": "a history enthusiast. Give in-depth, scholarly detail: chronology, sources, debates among historians, and architectural analysis.",
}
INTERESTS = ["history","architecture","culture","mythology","food","nature","adventure"]
LANGUAGES = ["English","Hindi","Tamil","Telugu","Kannada","Malayalam","Bengali","Marathi","Gujarati","Punjabi","Spanish","French","German","Japanese"]


class LLMError(Exception):
    def __init__(self, msg, status=502):
        super().__init__(msg); self.status = status


def db():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row; return c


def init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS visitors(session_id TEXT PRIMARY KEY, name TEXT, age_group TEXT,
          interests TEXT, language TEXT, minutes INT, destination TEXT, created TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT,
          role TEXT, content TEXT, created TIMESTAMP DEFAULT CURRENT_TIMESTAMP);""")


def validate_profile(d):
    """Returns (clean_profile, error)."""
    name = str(d.get("name", "")).strip()
    age = d.get("age_group")
    interests = d.get("interests") or []
    lang = d.get("language")
    dest = str(d.get("destination", "")).strip()
    try: minutes = int(d.get("minutes"))
    except (TypeError, ValueError): return None, "Available time must be a number of minutes."
    if not 1 <= len(name) <= 50: return None, "Please enter your name (max 50 characters)."
    if age not in AGE_GROUPS: return None, "Please select a valid age group."
    if not isinstance(interests, list) or not interests or any(i not in INTERESTS for i in interests):
        return None, "Select at least one valid interest."
    if lang not in LANGUAGES: return None, "Please select a supported language."
    if not 10 <= minutes <= 600: return None, "Time must be between 10 and 600 minutes."
    if not 2 <= len(dest) <= 100: return None, "Enter a destination (2-100 characters)."
    return dict(name=name, age_group=age, interests=interests, language=lang, minutes=minutes, destination=dest), None


def system_prompt(p):
    words = max(120, min(1200, p["minutes"] * 8))  # ~8 words per available minute, capped
    return (
     f"You are an expert, friendly tour guide. The visitor is {p['name']}, {AGE_GROUPS[p['age_group']]}\n"
     f"Interests: {', '.join(p['interests'])}. Emphasise these themes. Destination: {p['destination']}.\n"
     f"They have {p['minutes']} minutes, so keep a full tour explanation to about {words} words.\n"
     f"Respond ENTIRELY in {p['language']} (native script). Keep proper nouns, dates and facts exactly accurate "
     "when translating; never invent facts. If unsure of something, say so honestly. "
     "If the place is not a real tourist attraction, say so and suggest alternatives.")


def call_llm(system, messages, max_tokens=1800):
    """Call Google Gemini (free tier works). Messages: [{'role': 'user'|'assistant', 'content': str}]."""
    key = os.getenv("GEMINI_API_KEY")
    if not key: raise LLMError("GEMINI_API_KEY is not set. Add it to your .env file and restart.", 500)
    model = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
    try:
        r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            headers={"x-goog-api-key": key}, timeout=60,
            json={"system_instruction": {"parts": [{"text": system}]},
                  "contents": [{"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]} for m in messages],
                  "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.7}})
    except requests.Timeout: raise LLMError("Gemini timed out. Please try again.", 504)
    except requests.RequestException: raise LLMError("Could not reach the Gemini API. Check your internet connection.", 503)
    if r.status_code == 404: raise LLMError(f"Model '{model}' is unavailable. Set GEMINI_MODEL in .env to a current model (see https://ai.google.dev/gemini-api/docs/models).", 500)
    if r.status_code == 429: raise LLMError("Gemini free-tier rate limit reached. Wait a minute and try again.", 429)
    if r.status_code in (400, 403) and "API key" in r.text: raise LLMError("Invalid Gemini API key. Check GEMINI_API_KEY in .env.", 500)
    if r.status_code != 200:
        try: msg = r.json().get("error", {}).get("message", "")
        except ValueError: msg = ""
        raise LLMError(f"Gemini error {r.status_code}: {msg}")
    try:
        parts = r.json()["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts).strip()
    except (KeyError, IndexError, ValueError):
        raise LLMError("Gemini returned no text (the response may have been blocked). Try rephrasing.")


@app.errorhandler(LLMError)
def llm_err(e): return jsonify(error=str(e)), e.status


@app.route("/")
def index(): return render_template("index.html", interests=INTERESTS, languages=LANGUAGES)


@app.route("/api/destinations")
def destinations(): return jsonify(DESTINATIONS)


@app.route("/api/tour", methods=["POST"])
def tour():
    d = request.get_json(silent=True) or {}
    sid = str(d.get("session_id", ""))[:64]
    p, err = validate_profile(d)
    if err or not sid: return jsonify(error=err or "Missing session."), 400
    prompt = ("Create a personalized tour explanation. Format it in markdown with exactly these sections, each starting with "
              "'## ' (translate the headings): Overview, The Story, What To Look For, Insider Tip, Quick Facts. No other preamble.")
    text = call_llm(system_prompt(p), [{"role": "user", "content": prompt}])
    with db() as c:
        c.execute("REPLACE INTO visitors(session_id,name,age_group,interests,language,minutes,destination) VALUES(?,?,?,?,?,?,?)",
                  (sid, p["name"], p["age_group"], ",".join(p["interests"]), p["language"], p["minutes"], p["destination"]))
        c.execute("DELETE FROM messages WHERE session_id=?", (sid,))
        c.execute("INSERT INTO messages(session_id,role,content) VALUES(?,?,?)", (sid, "assistant", text))
    return jsonify(tour=text)


@app.route("/api/chat", methods=["POST"])
def chat():
    d = request.get_json(silent=True) or {}
    sid, q = str(d.get("session_id", ""))[:64], str(d.get("message", "")).strip()
    if not 1 <= len(q) <= 600: return jsonify(error="Message must be 1-600 characters."), 400
    with db() as c:
        v = c.execute("SELECT * FROM visitors WHERE session_id=?", (sid,)).fetchone()
        if not v: return jsonify(error="Generate a tour first so I know your preferences."), 400
        hist = [dict(role=r["role"], content=r["content"]) for r in
                c.execute("SELECT role,content FROM messages WHERE session_id=? ORDER BY id DESC LIMIT 12", (sid,))][::-1]
    p = dict(name=v["name"], age_group=v["age_group"], interests=v["interests"].split(","),
             language=v["language"], minutes=v["minutes"], destination=v["destination"])
    sys_p = system_prompt(p) + "\nNow you are answering follow-up questions conversationally. Keep answers concise (under 150 words) unless asked for more."
    msgs = hist + [{"role": "user", "content": q}]
    if msgs[0]["role"] != "user": msgs.insert(0, {"role": "user", "content": "Give me a tour."})
    reply = call_llm(sys_p, msgs, 900)
    with db() as c:
        c.executemany("INSERT INTO messages(session_id,role,content) VALUES(?,?,?)", [(sid, "user", q), (sid, "assistant", reply)])
    return jsonify(reply=reply)


@app.route("/api/plan", methods=["POST"])
def plan():
    """Interest-ranked itinerary that fits the time budget (works without the LLM)."""
    d = request.get_json(silent=True) or {}
    interests = d.get("interests") or []
    try: minutes = int(d.get("minutes"))
    except (TypeError, ValueError): return jsonify(error="Invalid time."), 400
    if not interests or any(i not in INTERESTS for i in interests) or not 10 <= minutes <= 1440:
        return jsonify(error="Select valid interests and a time of 10-1440 minutes."), 400
    ranked = sorted(DESTINATIONS, key=lambda x: (-len(set(x["tags"]) & set(interests)), x["minutes"]))
    stops, used = [], 0
    for x in ranked:
        if set(x["tags"]) & set(interests) and used + x["minutes"] <= minutes:
            stops.append({**x, "match": sorted(set(x["tags"]) & set(interests))}); used += x["minutes"]
    kind = "Short" if minutes <= 120 else "Medium" if minutes <= 360 else "Detailed"
    return jsonify(kind=kind, total_minutes=used, stops=stops)


init_db()
if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG") == "1", port=5000)
