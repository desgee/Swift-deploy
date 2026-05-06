#!/usr/bin/env python3
"""
SwiftDeploy API Service
Endpoints: GET /, GET /healthz, GET /metrics, POST /chaos
"""

import os
import time
import random
import threading
from flask import Flask, request, jsonify, Response, g

app = Flask(__name__)

# ── runtime state ──────────────────────────────────────────────
START_TIME  = time.time()
MODE        = os.environ.get("MODE", "stable")
APP_VERSION = os.environ.get("APP_VERSION", "1.0.0")
APP_PORT    = int(os.environ.get("APP_PORT", "3000"))

# ── chaos state ────────────────────────────────────────────────
chaos_lock  = threading.Lock()
chaos_state = {"mode": None, "duration": 0, "rate": 0.0}

# ── prometheus metrics ─────────────────────────────────────────
metrics_lock = threading.Lock()

# http_requests_total{method, path, status_code}
request_counts = {}

# histogram buckets
BUCKETS = [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
duration_histograms = {}


def record_request(method, path, status_code, duration_s):
    key_count = (method, path, str(status_code))
    key_hist  = (method, path)
    with metrics_lock:
        request_counts[key_count] = request_counts.get(key_count, 0) + 1
        if key_hist not in duration_histograms:
            duration_histograms[key_hist] = {
                "buckets": [0] * len(BUCKETS),
                "sum": 0.0,
                "count": 0,
            }
        h = duration_histograms[key_hist]
        h["sum"]   += duration_s
        h["count"] += 1
        for i, b in enumerate(BUCKETS):
            if duration_s <= b:
                h["buckets"][i] += 1


def chaos_active_code():
    with chaos_lock:
        m = chaos_state["mode"]
    if m == "slow":  return 1
    if m == "error": return 2
    return 0


# ── helpers ────────────────────────────────────────────────────
def is_canary():
    return MODE == "canary"

def add_common_headers(response):
    response.headers["X-Deployed-By"] = "swiftdeploy"
    if is_canary():
        response.headers["X-Mode"] = "canary"
    return response

def apply_chaos():
    with chaos_lock:
        state = dict(chaos_state)
    if state["mode"] == "slow":
        time.sleep(state["duration"])
    elif state["mode"] == "error":
        if random.random() < state["rate"]:
            return True
    return False


# ── metrics middleware ─────────────────────────────────────────
@app.before_request
def before_request():
    g.start_time = time.time()

@app.after_request
def after_request(response):
    if request.path != "/metrics":
        duration = time.time() - g.start_time
        record_request(request.method, request.path, response.status_code, duration)
    return response


# ── chaos middleware ───────────────────────────────────────────
@app.before_request
def apply_chaos_middleware():
    if request.path not in ("/chaos", "/metrics", "/healthz") and is_canary():
        if apply_chaos():
            resp = jsonify({"error": "chaos-induced error", "code": 500})
            resp.status_code = 500
            return add_common_headers(resp)


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
        "status":         "ok",
        "uptime_seconds": uptime,
        "mode":           MODE,
        "version":        APP_VERSION,
    }))


@app.route("/metrics")
def metrics():
    lines = []

    # ── http_requests_total ──────────────────────────────────
    lines.append("# HELP http_requests_total Total HTTP requests")
    lines.append("# TYPE http_requests_total counter")
    with metrics_lock:
        for (method, path, status), count in sorted(request_counts.items()):
            lines.append(
                f'http_requests_total{{method="{method}",path="{path}",status_code="{status}"}} {count}'
            )

    # ── http_request_duration_seconds ────────────────────────
    lines.append("# HELP http_request_duration_seconds Request latency histogram")
    lines.append("# TYPE http_request_duration_seconds histogram")
    with metrics_lock:
        for (method, path), h in sorted(duration_histograms.items()):
            cumulative = 0
            for i, b in enumerate(BUCKETS):
                cumulative += h["buckets"][i]
                lines.append(
                    f'http_request_duration_seconds_bucket{{method="{method}",path="{path}",le="{b}"}} {cumulative}'
                )
            lines.append(
                f'http_request_duration_seconds_bucket{{method="{method}",path="{path}",le="+Inf"}} {h["count"]}'
            )
            lines.append(
                f'http_request_duration_seconds_sum{{method="{method}",path="{path}"}} {h["sum"]:.6f}'
            )
            lines.append(
                f'http_request_duration_seconds_count{{method="{method}",path="{path}"}} {h["count"]}'
            )

    # ── app state metrics ────────────────────────────────────
    uptime    = round(time.time() - START_TIME, 2)
    mode_val  = 1 if is_canary() else 0
    chaos_val = chaos_active_code()

    lines.append("# HELP app_uptime_seconds Seconds since app started")
    lines.append("# TYPE app_uptime_seconds gauge")
    lines.append(f"app_uptime_seconds {uptime}")

    lines.append("# HELP app_mode Current mode: 0=stable 1=canary")
    lines.append("# TYPE app_mode gauge")
    lines.append(f"app_mode {mode_val}")

    lines.append("# HELP chaos_active Chaos state: 0=none 1=slow 2=error")
    lines.append("# TYPE chaos_active gauge")
    lines.append(f"chaos_active {chaos_val}")

    return Response("\n".join(lines) + "\n", mimetype="text/plain; version=0.0.4")


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

    return add_common_headers(jsonify({
        "message": msg,
        "chaos":   dict(chaos_state),
    }))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=APP_PORT)