from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
import random
import string
import re
import os
import json
import requests
from datetime import datetime
import threading

app = Flask(__name__)
CORS(app)

DB = "lucy.db"

# -------------------------------
# Database initialization
# -------------------------------
def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    # Referral tables
    c.execute('''CREATE TABLE IF NOT EXISTS referrals (id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE, created_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS earnings (id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT, order_id TEXT UNIQUE, amount REAL, created_at TEXT)''')
    # Lead capture tables
    c.execute('''CREATE TABLE IF NOT EXISTS processed_emails (email TEXT PRIMARY KEY)''')
    c.execute('''CREATE TABLE IF NOT EXISTS leads (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, email TEXT, message TEXT, created_at TEXT)''')
    conn.commit()
    conn.close()

init_db()

# -------------------------------
# Helper: clean email
# -------------------------------
def clean_email(email):
    if not email: return None
    email = email.strip().lower()
    return email if re.match(r'^[^@]+@[^@]+\.[^@]+$', email) else None

# -------------------------------
# AI calls (DeepSeek / Grok)
# -------------------------------
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
GROK_API_KEY = os.environ.get("GROK_API_KEY")

def call_deepseek(messages):
    if not DEEPSEEK_API_KEY:
        return {"error": "DeepSeek API key not set"}
    try:
        response = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
            json={"model": "deepseek-chat", "messages": messages, "temperature": 0.2},
            timeout=15
        )
        return response.json()
    except Exception as e:
        return {"error": str(e)}

def call_grok(messages):
    if not GROK_API_KEY:
        return {"error": "Grok API key not set"}
    try:
        response = requests.post(
            "https://api.x.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROK_API_KEY}", "Content-Type": "application/json"},
            json={"model": "grok-2-latest", "messages": messages, "temperature": 0.2},
            timeout=15
        )
        return response.json()
    except Exception as e:
        return {"error": str(e)}

# -------------------------------
# System stats (for admin)
# -------------------------------
def get_system_stats():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM referrals")
    total_refs = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM earnings")
    total_commissions = c.fetchone()[0]
    c.execute("SELECT SUM(amount) FROM earnings")
    total_amount = c.fetchone()[0] or 0.0
    c.execute("SELECT COUNT(*) FROM leads")
    total_leads = c.fetchone()[0]
    conn.close()
    return {
        "referral_codes": total_refs,
        "commissions_paid": total_commissions,
        "total_commission_amount": total_amount,
        "total_leads": total_leads
    }

# -------------------------------
# Admin command execution
# -------------------------------
ADMIN_API_KEY = os.environ.get("LUCY_ADMIN_KEY", "change-me")

def execute_admin_command(command_text):
    """Parse natural language command and execute corresponding action."""
    # Use AI to interpret command
    prompt = f"""You are Lucy_Ω's admin interpreter. Given a command from the CEO, output a JSON with:
    "action": one of ["set_commission_rate", "trigger_make_scenario", "sync_crm", "generate_report", "deploy_plugin", "restart_backend", "get_stats"],
    "args": any additional parameters (as dict), or null.
    Command: {command_text}
    """
    messages = [{"role": "user", "content": prompt}]
    ai_response = call_deepseek(messages)
    if "error" in ai_response:
        ai_response = call_grok(messages)
    try:
        if "choices" in ai_response:
            content = ai_response["choices"][0]["message"]["content"]
            parsed = json.loads(content)
        else:
            return {"error": "AI parsing failed"}
    except Exception as e:
        return {"error": str(e)}

    action = parsed.get("action")
    args = parsed.get("args") or {}

    if action == "set_commission_rate":
        new_rate = args.get("rate")
        if new_rate:
            # Store in file (or DB)
            with open("commission_rate.txt", "w") as f:
                f.write(str(new_rate))
            return {"result": f"Commission rate updated to {new_rate}%"}
        return {"error": "Missing rate"}
    elif action == "trigger_make_scenario":
        scenario = args.get("scenario")
        webhook_url = os.environ.get(f"MAKE_WEBHOOK_{scenario.upper()}")
        if webhook_url:
            requests.post(webhook_url, json={"trigger": "admin", "timestamp": datetime.now().isoformat()})
            return {"result": f"Triggered Make scenario: {scenario}"}
        return {"error": f"No webhook for scenario {scenario}"}
    elif action == "sync_crm":
        # Placeholder – trigger your CRM sync script
        threading.Thread(target=lambda: os.system("python sync_crm.py &")).start()
        return {"result": "CRM sync initiated"}
    elif action == "generate_report":
        stats = get_system_stats()
        return {"result": f"Report: {stats}"}
    elif action == "deploy_plugin":
        url = args.get("url")
        if url:
            # Call WordPress webhook (optional)
            webhook = os.environ.get("WORDPRESS_DEPLOY_WEBHOOK")
            if webhook:
                requests.post(webhook, json={"url": url})
                return {"result": f"Deployment triggered for plugin from {url}"}
            return {"error": "WordPress deploy webhook not configured"}
        return {"error": "Missing plugin URL"}
    elif action == "restart_backend":
        os.system("pkill -f gunicorn || true")
        return {"result": "Backend restart initiated"}
    elif action == "get_stats":
        return {"result": get_system_stats()}
    else:
        return {"error": f"Unknown action: {action}"}

# -------------------------------
# Public endpoints (existing)
# -------------------------------
@app.route("/")
def home():
    return {"status": "Lucy Ω unified backend"}

@app.route("/stats")
def stats():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM processed_emails")
    processed = c.fetchone()[0]
    conn.close()
    return {"status": "LIVE", "processed": processed}

@app.route("/avatar-chat", methods=["POST"])
def avatar_chat():
    data = request.get_json()
    msg = data.get("message", "")
    # Simple canned response (or you can use AI for public chat)
    return jsonify({"text": f"Lucy Ω received: '{msg}'. We'll respond soon."})

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
    stats = get_system_stats()
    return jsonify(stats)

# -------------------------------
# Admin command endpoint
# -------------------------------
@app.route("/admin/command", methods=["POST"])
def admin_command():
    auth = request.headers.get("X-Admin-Key")
    if auth != ADMIN_API_KEY:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json()
    command = data.get("command")
    if not command:
        return jsonify({"error": "Missing command"}), 400
    result = execute_admin_command(command)
    return jsonify(result)

# -------------------------------
# Admin chat endpoint (with AI)
# -------------------------------
admin_sessions = {}  # In-memory session store

@app.route("/admin-chat", methods=["POST"])
def admin_chat():
    auth = request.headers.get("X-Admin-Key")
    if auth != ADMIN_API_KEY:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json()
    user_message = data.get("message", "")
    session_id = data.get("session_id", "default")
    if session_id not in admin_sessions:
        admin_sessions[session_id] = []
    history = admin_sessions[session_id]
    history.append({"role": "user", "content": user_message})

    system_prompt = """You are Lucy_Ω, the CEO's strategic AI advisor.
    You help with architecture decisions, project planning, operational instructions, and revenue strategy.
    You have access to system metrics via internal functions.
    Keep responses concise, actionable, and aligned with Phase 1 revenue flywheel."""
    messages = [{"role": "system", "content": system_prompt}] + history
    response = call_deepseek(messages)
    if "error" in response:
        response = call_grok(messages)
    if "choices" in response:
        reply = response["choices"][0]["message"]["content"]
    else:
        reply = "Sorry, I encountered an error processing your request."

    history.append({"role": "assistant", "content": reply})
    # Limit history length
    if len(history) > 20:
        admin_sessions[session_id] = history[-20:]
    return jsonify({"text": reply, "session_id": session_id})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)
