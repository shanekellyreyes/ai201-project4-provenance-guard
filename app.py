import os, uuid
from datetime import datetime, timezone
from flask import Flask, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv

import storage, detection

load_dotenv()
app = Flask(__name__)
storage.init_db()

limiter = Limiter(get_remote_address, app=app,
                  default_limits=[], storage_uri="memory://")

@app.route("/submit", methods=["POST"])
@limiter.limit("10 per minute;100 per day")
def submit():
    body = request.get_json(silent=True) or {}
    text = (body.get("text") or "").strip()
    creator_id = (body.get("creator_id") or "").strip()
    if not text or not creator_id:
        return jsonify({"error": "text and creator_id are required"}), 400

    llm = detection.llm_signal(text)
    stylo = detection.stylometric_signal(text)
    confidence, attribution, degraded = detection.combine_scores(
        llm["score"], stylo["score"])
    label = detection.make_label(attribution, confidence)

    content_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    storage.save_submission({
        "content_id": content_id, "creator_id": creator_id, "text": text,
        "attribution": attribution, "confidence": confidence,
        "llm_score": llm["score"], "stylo_score": stylo["score"],
        "status": "classified", "created_at": created_at})
    storage.log_event({
        "content_id": content_id, "creator_id": creator_id,
        "event_type": "classification", "attribution": attribution,
        "confidence": confidence, "llm_score": llm["score"],
        "stylo_score": stylo["score"], "status": "classified",
        "appeal_reasoning": None})

    return jsonify({
        "content_id": content_id, "attribution": attribution,
        "confidence": confidence, "label": label,
        "signals": {
            "llm": {"score": llm["score"], "reasoning": llm["reasoning"],
                    "error": llm["error"]},
            "stylometric": {"score": stylo["score"], "metrics": stylo["metrics"]}},
        "degraded": degraded}), 200

@app.route("/appeal", methods=["POST"])
def appeal():
    body = request.get_json(silent=True) or {}
    content_id = (body.get("content_id") or "").strip()
    reasoning = (body.get("creator_reasoning") or "").strip()
    if not content_id or not reasoning:
        return jsonify({"error": "content_id and creator_reasoning are required"}), 400
    sub = storage.get_submission(content_id)
    if not sub:
        return jsonify({"error": "content_id not found"}), 404
    storage.update_status(content_id, "under_review")
    storage.log_event({
        "content_id": content_id, "creator_id": sub["creator_id"],
        "event_type": "appeal", "attribution": sub["attribution"],
        "confidence": sub["confidence"], "llm_score": sub["llm_score"],
        "stylo_score": sub["stylo_score"], "status": "under_review",
        "appeal_reasoning": reasoning})
    return jsonify({"message": "Appeal received. This content is now under review.",
                    "content_id": content_id, "status": "under_review"}), 200

@app.route("/log", methods=["GET"])
def log():
    return jsonify({"entries": storage.get_log()}), 200

@app.errorhandler(429)
def ratelimit_handler(e):
    return jsonify({"error": "rate limit exceeded",
                    "detail": str(e.description)}), 429

if __name__ == "__main__":
    app.run(debug=True, port=5001)