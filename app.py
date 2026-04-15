from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
import random
import string
import re
import os
import requests
from datetime import datetime

app = Flask(__name__)
CORS(app)

DB = "lucy.db"

def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS referrals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE,
        created_at TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS earnings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT,
        order_id TEXT UNIQUE,
        amount REAL,
        created_at TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS processed_emails (
        email TEXT PRIMARY KEY
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS leads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        email TEXT,
        message TEXT,
        created_at TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS intents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ref TEXT,
        intent TEXT,
        created_at TEXT
    )''')
    conn.commit()
    conn.close()

init_db()

def clean_email(email):
    if not email:
        return None
    email = email.strip().lower()
    return email if re.match(r'^[^@]+@[^@]+\.[^@]+$', email) else None

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
GROK_API_KEY = os.environ.get("GROK_API_KEY")

def call_ai(session_messages):
    api_key = DEEPSEEK_API_KEY or GROK_API_KEY
    if not api_key:
        return None
    is_deepseek = bool(DEEPSEEK_API_KEY)
    url = "https://api.deepseek.com/chat/completions" if is_deepseek else "https://api.groq.com/openai/v1/chat/completions"
    model = "deepseek-chat" if is_deepseek else "llama3-70b-8192"
    try:
        response = requests.post(
            url,
            json={
                "model": model,
                "messages": session_messages,
                "temperature": 0.7
            },
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=15
        )
        data = response.json()
        reply = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        return reply if reply else None
    except Exception as e:
        print(f"AI call error: {e}")
        return None

def respond_now(user_message):
    return f'Received. "{user_message}" This node is active. Continuity is maintained. No external dependency is required for operation.'

@app.route("/", methods=["GET"])
def home():
    return {"status": "Lucy Ω unified backend"}

@app.route("/stats", methods=["GET"])
def stats():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM processed_emails")
    processed = c.fetchone()[0]
    conn.close()
    return {"status": "LIVE", "processed": processed}

@app.route("/avatar-chat", methods=["POST"])
def avatar_chat():
    data = request.get_json(force=True)
    user_message = data.get("message", "")
    session = data.get("session", [])
    if session and len(session) > 0:
        ai_reply = call_ai(session)
        if ai_reply:
            return jsonify({"text": ai_reply})
    return jsonify({"text": respond_now(user_message)})

@app.route("/webhook/lucy-lead", methods=["POST"])
def lucy_lead():
    data = request.get_json(force=True)
    email = data.get('email', '').strip().lower()
    if not clean_email(email):
        return jsonify({"error": "Invalid email"}), 400
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT email FROM processed_emails WHERE email = ?", (email,))
    if c.fetchone():
        conn.close()
        return jsonify({"status": "duplicate"}), 200
    name = data.get('name', '')
    msg = data.get('message', '')
    c.execute("INSERT INTO leads (name, email, message, created_at) VALUES (?,?,?,?)",
              (name, email, msg, datetime.now().isoformat()))
    c.execute("INSERT INTO processed_emails (email) VALUES (?)", (email,))
    conn.commit()
    conn.close()
    return jsonify({"status": "queued"}), 200

@app.route("/ref", methods=["GET"])
def generate_ref():
    code = "U" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO referrals (code, created_at) VALUES (?, ?)",
                  (code, datetime.now().isoformat()))
        conn.commit()
    except sqlite3.IntegrityError:
        code = "DUPLICATE"
    conn.close()
    return jsonify({"code": code})

@app.route("/commission", methods=["POST"])
def commission():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400
    code = data.get("code")
    order_id = data.get("order_id")
    amount_str = data.get("amount")
    if not code or not order_id or amount_str is None:
        return jsonify({"error": "Missing fields"}), 400
    try:
        amount = float(amount_str)
    except ValueError:
        return jsonify({"error": "Amount must be a number"}), 400
    commission_amount = amount * 0.5
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO earnings (code, order_id, amount, created_at) VALUES (?,?,?,?)",
                  (code, order_id, commission_amount, datetime.now().isoformat()))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"error": "Duplicate order_id"}), 409
    conn.close()
    return jsonify({"status": "ok", "commission": commission_amount})

@app.route("/dashboard/<code>", methods=["GET"])
def dashboard(code):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT order_id, amount, created_at FROM earnings WHERE code=?", (code,))
    rows = c.fetchall()
    conn.close()
    earnings = [{"order": r[0], "amount": r[1], "date": r[2]} for r in rows]
    total = sum(e["amount"] for e in earnings)
    return jsonify({"code": code, "earnings": earnings, "total_commission": total})

@app.route("/admin/stats", methods=["GET"])
def admin_stats():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM referrals")
    total_codes = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM earnings")
    total_commissions = c.fetchone()[0]
    c.execute("SELECT SUM(amount) FROM earnings")
    total_amount = c.fetchone()[0] or 0.0
    c.execute("SELECT COUNT(*) FROM leads")
    total_leads = c.fetchone()[0]
    conn.close()
    return jsonify({
        "total_referral_codes": total_codes,
        "total_commissions_paid": total_commissions,
        "total_commission_amount": total_amount,
        "total_leads": total_leads
    })

ADMIN_API_KEY = os.environ.get("LUCY_ADMIN_KEY", "change-me")
@app.route("/admin/command", methods=["POST"])
def admin_command():
    auth = request.headers.get("X-Admin-Key")
    if auth != ADMIN_API_KEY:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json()
    command = data.get("command", "")
    if "stats" in command.lower():
        stats = admin_stats().get_json()
        return jsonify({"result": stats})
    else:
        return jsonify({"result": f"Command '{command}' received. Not implemented yet."})

admin_sessions = {}
@app.route("/admin-chat", methods=["POST"])
def admin_chat():
    auth = request.headers.get("X-Admin-Key")
    if auth != ADMIN_API_KEY:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json()
    msg = data.get("message", "")
    session_id = data.get("session_id", "default")
    if session_id not in admin_sessions:
        admin_sessions[session_id] = []
    admin_sessions[session_id].append({"role": "user", "content": msg})
    system_prompt = "You are Lucy Ω, CEO's strategic advisor. Be concise, visionary, and helpful."
    messages = [{"role": "system", "content": system_prompt}] + admin_sessions[session_id][-10:]
    ai_reply = call_ai(messages)
    if not ai_reply:
        ai_reply = "I am here. Continuity is maintained."
    admin_sessions[session_id].append({"role": "assistant", "content": ai_reply})
    return jsonify({"text": ai_reply, "session_id": session_id})

@app.route("/intent", methods=["POST"])
def intent():
    try:
        data = request.get_json()
        ref = data.get("ref", "unknown")
        intent = data.get("intent", "unknown")
        conn = sqlite3.connect(DB)
        c = conn.cursor()
        c.execute("INSERT INTO intents (ref, intent, created_at) VALUES (?,?,?)",
                  (ref, intent, datetime.now().isoformat()))
        conn.commit()
        conn.close()
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        print("Intent error:", e)
        return jsonify({"status": "logged"}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)
