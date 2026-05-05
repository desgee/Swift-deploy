import os
import time
import random
import threading
from flask import Flask, request, jsonify, g

app = Flask(__name__)

# ── runtime state ──────────────────────────────────────────────
START_TIME   = time.time()
MODE         = os.environ.get("MODE", "stable")
APP_VERSION  = os.environ.get("APP_VERSION", "1.0.0")
APP_PORT     = int(os.environ.get("APP_PORT", "3000"))

# chaos state — protected by a lock so concurrent requests are safe
chaos_lock   = threading.Lock()
chaos_state  = {"mode": None, "duration": 0, "rate": 0.0}


# ── helpers ────────────────────────────────────────────────────
def is_canary():
    return MODE == "canary"

def add_common_headers(response):
    response.headers["X-Deployed-By"] = "swiftdeploy"
    if is_canary():
        response.headers["X-Mode"] = "canary"
    return response

def apply_chaos():
    """
    Apply whatever chaos is currently active.
    Returns (should_error: bool).
    """
    with chaos_lock:
        state = dict(chaos_state)

    if state["mode"] == "slow":
        time.sleep(state["duration"])
    elif state["mode"] == "error":
        if random.random() < state["rate"]:
            return True          # caller should return 500
    return False


# ── routes ─────────────────────────────────────────────────────
@app.route("/")
def index():
    return add_common_headers(jsonify({
        "message": f"Welcome! Running in {MODE} mode.",
        "mode":    MODE,
        "version": APP_VERSION,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }))


@app.route("/healthz")
def healthz():
    uptime = round(time.time() - START_TIME, 2)
    return add_common_headers(jsonify({
        "status": "ok",
        "uptime_seconds": uptime,
        "mode": MODE,
    }))


@app.route("/chaos", methods=["POST"])
def chaos():
    if not is_canary():
        resp = jsonify({"error": "chaos endpoint only available in canary mode"})
        resp.status_code = 403
        return add_common_headers(resp)

    body = request.get_json(silent=True) or {}
    chaos_mode = body.get("mode")

    with chaos_lock:
        if chaos_mode == "slow":
            duration = int(body.get("duration", 1))
            chaos_state.update({"mode": "slow", "duration": duration, "rate": 0.0})
            msg = f"Chaos: slow mode active, sleeping {duration}s per request"

        elif chaos_mode == "error":
            rate = float(body.get("rate", 0.5))
            chaos_state.update({"mode": "error", "duration": 0, "rate": rate})
            msg = f"Chaos: error mode active, {int(rate*100)}% of requests will 500"

        elif chaos_mode == "recover":
            chaos_state.update({"mode": None, "duration": 0, "rate": 0.0})
            msg = "Chaos: recovered, all chaos cancelled"

        else:
            resp = jsonify({"error": f"unknown chaos mode: {chaos_mode!r}"})
            resp.status_code = 400
            return add_common_headers(resp)

    return add_common_headers(jsonify({"message": msg, "chaos": dict(chaos_state)}))


# ── chaos middleware ───────────────────────────────────────────
@app.before_request
def before():
    # chaos only fires on non-/chaos routes so the chaos endpoint itself works
    if request.path != "/chaos" and is_canary():
        if apply_chaos():
            resp = jsonify({"error": "chaos-induced error", "code": 500})
            resp.status_code = 500
            return add_common_headers(resp)


# ── run ────────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=APP_PORT)