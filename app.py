from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
import random
import string
import re
import os
from datetime import datetime

app = Flask(__name__)
CORS(app)

DB = "lucy.db"

def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    # Referral tables
    c.execute('''
        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE,
            created_at TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS earnings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT,
            order_id TEXT UNIQUE,
            amount REAL,
            created_at TEXT
        )
    ''')
    # Lead capture tables (optional, keeps your existing leads)
    c.execute('''
        CREATE TABLE IF NOT EXISTS processed_emails (
            email TEXT PRIMARY KEY
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            email TEXT,
            message TEXT,
            created_at TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# -------------------------------
# Health & stats
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

# -------------------------------
# Chat endpoint (existing)
# -------------------------------
@app.route("/avatar-chat", methods=["POST"])
def chat():
    data = request.get_json()
    msg = data.get("message", "")
    return jsonify({"text": f"Lucy Ω reply: {msg}"})

# -------------------------------
# Lead capture (optional, from earlier setup)
# -------------------------------
def clean_email(email):
    if not email:
        return None
    email = email.strip().lower()
    return email if re.match(r'^[^@]+@[^@]+\.[^@]+$', email) else None

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

# -------------------------------
# Referral & Commission Endpoints
# -------------------------------
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
        c.execute(
            "INSERT INTO earnings (code, order_id, amount, created_at) VALUES (?,?,?,?)",
            (code, order_id, commission_amount, datetime.now().isoformat())
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"error": "Duplicate order_id – commission already paid"}), 409
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
    conn.close()
    return jsonify({
        "total_referral_codes": total_codes,
        "total_commissions_paid": total_commissions,
        "total_commission_amount": total_amount
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)
