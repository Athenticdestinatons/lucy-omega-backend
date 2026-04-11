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

# ============================================================
# CEO OVERRIDE – Hardcoded Keys (Secure Terminal)
# ============================================================
DEEPSEEK_API_KEY = "sk-3a9ffec7537947e6a02bf33ad8c7faa9"
GROK_API_KEY = "xai-u9iR2wAT4sPespxIsnadBd6tc4F2sXTQOiIE6nDRWngLdXAxlqAOEbAvTXmueXzbQPU402WKjxYt5DmJ"
ADMIN_API_KEY = "4bd0c8ebc795a86e72856666d4aa9559ca635f1b9a21fd387a37acfc4751c81d"
MAILERLITE_API_KEY = "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9.eyJhdWQiOiI0IiwianRpIjoiZTFiZTYzNGJhNDZiYWY0ZDM2NDcxYWY2ZmVkMTZmNzkyN2I2NDE1OWUxNjY0YjkzMjdkNzMzOWFkNzg2YzI4MmU2NjM0ZjJmMWE4OGVlNTUiLCJpYXQiOjE3NzU5MjQxMTkuMzI2ODY5LCJuYmYiOjE3NzU5MjQxMTkuMzI2ODc0LCJleHAiOjQ5MzE1OTc3MTkuMzE5NjY3LCJzdWIiOiIxODM1ODE2Iiwic2NvcGVzIjpbXX0.bmWVsL90L_J7A3eqsK-TbWkbgjNZk9N3pr0CPM3Mj9L0-po8jeSIBkaF6wzmWsdz7B5TipR6t6pcxOh7AbpGnyfiuqg79gE5S4qSdz9FKnCtKRcajQ1X1MxslvLdOwIOTh2OA0VXSXp7hn5VfU_sQsxj3thnDoIWLV0b91F05AH0iq7x2k_HAJXrwMV38-YZsmXEQ8iMWW5amBaIlGWTwknEJW_WLVkXyJD0JKJzgu6uZ3pBlfbRCase2XZQ3Fi4Qqzbmsl1ffaCuu7eJKYlpXqChkIx5zg_CzMtoIC6va9RqgoW6HZVkKPldmvqCaKANBQ6eGKB9EftOHSQ4oxy_6PE9KITgd-cN7ygPlTw2HF2i7-kQZ1Ogy9boxeXxdZutBqCWXtziNHFvkDbFOtGZsPrVu1fzoyIUJpDQq5xbpo0RJIiIydzHyzO0vOyW-YrtIBt0HwDtDBEU6nU4zrwPNrmpRU0DmIQwDAWhmeXUlLJxXIY5ck_T82ezPQiD8-NThnLONiDi8UEnNzpNDLE1Gd0lGfa40GM7ucLhG7A8jfeJwtXtOGRzDhOojzcg2vQ3X733HZiXZ2SSAYVdPw_-6NPApp-rwXxtKlIzffcS_4CxQosmtPUQL_9_57W1m3WUnuLq1qcQ2Od5HKXYmXYolRiAdZxPOFkaDsfNYapVkQ"

# ============================================================
# Database initialization
# ============================================================
def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS referrals (id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE, created_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS earnings (id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT, order_id TEXT UNIQUE, amount REAL, created_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS processed_emails (email TEXT PRIMARY KEY)''')
    c.execute('''CREATE TABLE IF NOT EXISTS leads (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, email TEXT, message TEXT, created_at TEXT)''')
    conn.commit()
    conn.close()

init_db()

# ============================================================
# MailerLite Integration
# ============================================================
def add_to_mailerlite(email, name=""):
    """Add a subscriber to MailerLite group 'Lucy Influencers'"""
    try:
        response = requests.post(
            "https://connect.mailerlite.com/api/subscribers",
            headers={
                "Authorization": f"Bearer {MAILERLITE_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "email": email,
                "fields": {"name": name},
                "groups": ["Lucy Influencers"]  # You can change group name
            },
            timeout=10
        )
        if response.status_code in [200, 201]:
            print(f"✅ Added {email} to MailerLite")
            return True
        else:
            print(f"MailerLite error: {response.text}")
            return False
    except Exception as e:
        print(f"MailerLite exception: {e}")
        return False

def batch_import_to_mailerlite(emails):
    """Import multiple emails to MailerLite"""
    success = 0
    for email in emails:
        if add_to_mailerlite(email):
            success += 1
    return success

# ============================================================
# Helper functions
# ============================================================
def clean_email(email):
    if not email: return None
    email = email.strip().lower()
    return email if re.match(r'^[^@]+@[^@]+\.[^@]+$', email) else None

def call_deepseek(messages):
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

# ============================================================
# Public endpoints
# ============================================================
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
    
    # Auto-add to MailerLite
    add_to_mailerlite(email, name)
    
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
    return jsonify(get_system_stats())

# ============================================================
# Admin endpoints
# ============================================================
def admin_required(f):
    def wrapper(*args, **kwargs):
        auth = request.headers.get("X-Admin-Key")
        if auth != ADMIN_API_KEY:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper

@app.route("/admin/command", methods=["POST"])
@admin_required
def admin_command():
    data = request.get_json()
    command = data.get("command")
    if not command:
        return jsonify({"error": "Missing command"}), 400
    
    if "stats" in command.lower():
        return jsonify({"result": get_system_stats()})
    elif "import" in command.lower() and "email" in command.lower():
        # Example: import emails from CSV URL
        return jsonify({"result": "Batch import function ready. Provide CSV URL."})
    else:
        return jsonify({"result": f"Command '{command}' received."})

admin_sessions = {}

@app.route("/admin-chat", methods=["POST"])
@admin_required
def admin_chat():
    data = request.get_json()
    user_message = data.get("message", "")
    session_id = data.get("session_id", "default")
    
    if session_id not in admin_sessions:
        admin_sessions[session_id] = []
    history = admin_sessions[session_id]
    history.append({"role": "user", "content": user_message})
    
    stats = get_system_stats()
    stats_text = f"\n\n[SYSTEM STATS - Current Data]\n" + \
                 f"- Referral codes generated: {stats['referral_codes']}\n" + \
                 f"- Commissions paid: {stats['commissions_paid']}\n" + \
                 f"- Total commission amount: {stats['total_commission_amount']} USDT\n" + \
                 f"- Total leads captured: {stats['total_leads']}\n"
    
    system_prompt = f"""You are Lucy_Ω, the CEO's strategic AI advisor.
    You have access to the current system stats below. Use them when asked about performance, leads, or commissions.
    Keep responses concise and actionable.
    
    {stats_text}"""
    
    messages = [{"role": "system", "content": system_prompt}] + history
    response = call_deepseek(messages)
    if "error" in response:
        response = call_grok(messages)
    if "choices" in response:
        reply = response["choices"][0]["message"]["content"]
    else:
        reply = "I'm having trouble connecting to my AI services."
    
    history.append({"role": "assistant", "content": reply})
    if len(history) > 20:
        admin_sessions[session_id] = history[-20:]
    return jsonify({"text": reply, "session_id": session_id})

# ============================================================
# Batch import endpoint (for first 200 emails)
# ============================================================
@app.route("/admin/import-emails", methods=["POST"])
@admin_required
def import_emails():
    data = request.get_json()
    emails = data.get("emails", [])
    if not emails:
        return jsonify({"error": "No emails provided"}), 400
    success = batch_import_to_mailerlite(emails)
    return jsonify({"imported": success, "total": len(emails)})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)
