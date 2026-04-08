from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

@app.route("/")
def home():
    return {"status": "running"}

@app.route("/stats")
def stats():
    return {"status": "LIVE"}

@app.route("/avatar-chat", methods=["POST"])
def chat():
    data = request.get_json()
    msg = data.get("message", "")
    return jsonify({"text": f"Lucy Ω reply: {msg}"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
