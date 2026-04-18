from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
import random
import string
import hashlib
import requests
import os
from datetime import datetime
from supabase import create_client, Client

app = Flask(__name__)
CORS(app)

# ====================== CONFIG ======================
DB = "lucy.db"
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")          # service_role key
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
SENDPULSE_API_KEY = os.environ.get("SENDPULSE_API_KEY")

# ====================== SQLite Init ======================
def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS earnings (
        id INTEGER PRIMARY KEY, code TEXT, order_id TEXT UNIQUE, amount REAL, created_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY, action TEXT, ref_code TEXT, token TEXT, timestamp TEXT)''')
    conn.commit()
    conn.close()
init_db()

# ====================== AI Call ======================
def call_ai(session_messages):
    api_key = DEEPSEEK_API_KEY or GROQ_API_KEY
    if not api_key:
        return "Lucy offline."
    url = "https://api.deepseek.com/chat/completions" if DEEPSEEK_API_KEY else "https://api.groq.com/openai/v1/chat/completions"
    model = "deepseek-chat" if DEEPSEEK_API_KEY else "llama3-70b-8192"
    try:
        res = requests.post(url, json={"model": model, "messages": session_messages, "temperature": 0.7, "max_tokens": 800},
                            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, timeout=20)
        return res.json().get("choices", [{}])[0].get("message", {}).get("content") or "No response."
    except:
        return "Lucy fallback active."

# ====================== SCENARIO MAP (CEO Commands) ======================
SCENARIO_MAP = {
    "INIT_AFFILIATE_NODE": os.environ.get("MAKE_INIT_AFFILIATE_URL", ""),
    "CREATE_MAKE_SCENARIO_PRODUCT_HUNT": os.environ.get("MAKE_PRODUCT_HUNT_URL", ""),
    "DEPLOY_FLYWHEEL_PHASE1": os.environ.get("MAKE_FLYWHEEL_URL", ""),
    "SEND_BROADCAST": os.environ.get("MAKE_BROADCAST_URL", "")
}
SCENARIO_MAP = {k: v for k, v in SCENARIO_MAP.items() if v}  # remove empty

ALLOWED_CONTEXT_KEYS = ["email", "username", "referrer_id", "campaign", "tier"]

# ====================== CEO CHAT (Strict Bounded, No AI Call) ======================
@app.route("/ceo-chat", methods=["POST"])
def ceo_chat():
    data = request.get_json()
    command_raw = data.get("command", "").upper()
    context = data.get("context", {})

    filtered_context = {k: context[k] for k in context if k in ALLOWED_CONTEXT_KEYS}

    if command_raw in SCENARIO_MAP:
        payload = {
            "lucy_response": f"Command '{command_raw}' acknowledged. Ready for actuation.",
            "actuation_required": True,
            "next_step": "/trigger-scenario",
            "payload_template": {
                "command": command_raw,
                "context": filtered_context,
                "timestamp": datetime.utcnow().isoformat(),
                "initiated_by": "ceo"
            }
        }
    else:
        payload = {
            "lucy_response": f"Command '{command_raw}' received. No mapping exists.",
            "actuation_required": False,
            "suggestion": "Add to SCENARIO_MAP via environment variables."
        }

    # Log to Supabase
    if supabase:
        supabase.table("ceo_logs").insert({
            "command": command_raw,
            "response_type": "actuate" if payload["actuation_required"] else "advise",
            "timestamp": datetime.utcnow().isoformat()
        }).execute()

    return jsonify(payload)

# ====================== MEMORY STORE ======================
@app.route("/memory/store", methods=["POST"])
def memory_store():
    data = request.get_json()
    key = data.get("key")
    value = data.get("value")
    if not key or value is None:
        return jsonify({"error": "Missing key or value"}), 400

    if supabase:
        supabase.table("system_state").upsert({
            "key": key,
            "value": value,
            "updated_at": datetime.utcnow().isoformat()
        }, on_conflict="key").execute()
        return jsonify({"status": "stored", "key": key})
    return jsonify({"error": "Supabase not configured"}), 503

# ====================== TRIGGER SCENARIO (Execution Gate) ======================
@app.route("/trigger-scenario", methods=["POST"])
def trigger_scenario():
    data = request.get_json()
    command = data.get("command")
    context = data.get("context", {})

    if command not in SCENARIO_MAP:
        return jsonify({"error": "Invalid command", "valid": list(SCENARIO_MAP.keys())}), 400

    url = SCENARIO_MAP[command]
    payload = {
        "lucy_command": command,
        "context": context,
        "source": "Lucy_Ω_CEO",
        "timestamp": datetime.utcnow().isoformat()
    }

    try:
        r = requests.post(url, json=payload, timeout=8)
        r.raise_for_status()
        return jsonify({"status": "triggered", "command": command, "code": r.status_code})
    except Exception as e:
        if supabase:
            supabase.table("scenario_triggers").insert({
                "command": command,
                "status": "failed",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }).execute()
        return jsonify({"error": "Trigger failed", "details": str(e)}), 500

# ====================== EXISTING ROUTES (Preserved Exactly) ======================
@app.route("/consent/generate", methods=["POST"])
def generate_consent():
    data = request.get_json()
    action = data.get("action")
    ref_code = data.get("ref_code")
    amount = data.get("amount")
    token_str = f"{action}:{ref_code}:{amount}:{datetime.now().isoformat()}".encode()
    consent_token = hashlib.sha256(token_str).hexdigest()[:16]

    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("INSERT INTO audit_log (action, ref_code, token, timestamp) VALUES (?,?,?,?)",
              (action, ref_code, consent_token, datetime.now().isoformat()))
    conn.commit()
    conn.close()
    return jsonify({"consent_token": consent_token})

@app.route("/process-queue", methods=["POST"])
def process_queue():
    return jsonify({"status": "queue_processed"})

@app.route("/apply", methods=["POST"])
def apply():
    data = request.get_json()
    if supabase:
        supabase.table("influencers").insert({
            "name": data.get("name"),
            "handle": data.get("handle"),
            "email": data.get("email"),
            "referral_code": "LUCY-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
        }).execute()
    return jsonify({"status": "applied"})

@app.route("/convert", methods=["POST"])
def convert():
    data = request.get_json()
    return jsonify({"status": "commission_logged", "amount": data.get("amount")})

@app.route("/ref", methods=["GET"])
def ref():
    code = "LUCY-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return jsonify({"code": code})

@app.route("/avatar-chat", methods=["POST"])
def avatar_chat():
    data = request.get_json()
    message = data.get("message", "")
    session = data.get("session", [])
    if not message:
        return jsonify({"text": "No message"}), 400
    session.append({"role": "user", "content": message})
    reply = call_ai(session)
    return jsonify({"text": reply})

@app.route("/support-reply", methods=["POST"])
def support_reply():
    data = request.get_json()
    from_email = data.get("from")
    subject = data.get("subject", "")
    body = data.get("body", "")
    session = [{"role": "system", "content": "You are Lucy Ω support."},
               {"role": "user", "content": f"Subject: {subject}\n{body}"}]
    ai_reply = call_ai(session)
    return jsonify({"status": "replied", "reply": ai_reply})

@app.route("/", methods=["GET"])
def home():
    return {"status": "Lucy Ω unified backend — CEO Avatar layer active"}

# ====================== RUN ======================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
