import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path

from flask import Flask, jsonify, request

from scanner import (
    cleanup_old_outputs,
    load_config,
    scan_task,
    setup_logging,
    upload_latest_csv_to_oss,
)


CONFIG_PATH = os.environ.get(
    "CONFIG_PATH",
    "/config/config.json"
)

app = Flask(__name__)

config = load_config(CONFIG_PATH)
setup_logging(config["logging"])

scan_lock = threading.Lock()
jobs = {}


def require_token():
    api_cfg = config.get("api", {})
    token = api_cfg.get("token")
    if not token:
        return None
    provided = request.headers.get("X-API-Token", "")
    if provided != token:
        return jsonify({"error": "unauthorized"}), 401
    return None


def record_job(job_id: str, name: str, status: str, error: str = ""):
    jobs[job_id] = {
        "id": job_id,
        "action": name,
        "status": status,
        "error": error,
        "updated_at": time.time(),
    }


def run_action(name: str, fn, job_id: str):
    try:
        record_job(job_id, name, "running")
        fn()
        record_job(job_id, name, "success")
    except Exception as exc:
        logging.exception("action failed: %s", name)
        record_job(job_id, name, "error", str(exc))


def action_scan():
    with scan_lock:
        scan_task(config)


def action_cleanup():
    retention_days = config.get("retention", {}).get("days")
    if not retention_days:
        logging.info("未配置 retention.days，跳过清理")
        return
    output_dir = Path(config["output"]["directory"])
    cleanup_old_outputs(output_dir, retention_days)


def action_upload_latest():
    output_dir = Path(config["output"]["directory"])
    latest_csv = output_dir / config["output"]["latest_filename"]
    upload_latest_csv_to_oss(config, latest_csv, output_dir)


ACTIONS = {
    "scan": action_scan,
    "cleanup": action_cleanup,
    "upload_latest": action_upload_latest,
}


@app.get("/health")
def health():
    auth = require_token()
    if auth:
        return auth
    return jsonify({"status": "ok"})


@app.get("/actions")
def list_actions():
    auth = require_token()
    if auth:
        return auth
    return jsonify({"actions": sorted(ACTIONS.keys())})


@app.post("/scan")
def trigger_scan():
    return trigger_action("scan")


@app.post("/actions/<name>")
def trigger_action(name: str):
    auth = require_token()
    if auth:
        return auth

    fn = ACTIONS.get(name)
    if not fn:
        return jsonify({"error": "unknown_action"}), 404

    payload = request.get_json(silent=True) or {}
    mode = payload.get("mode", "async")
    job_id = uuid.uuid4().hex

    if mode == "sync":
        run_action(name, fn, job_id)
        return jsonify(jobs[job_id])

    thread = threading.Thread(
        target=run_action,
        args=(name, fn, job_id),
        daemon=True,
    )
    thread.start()
    record_job(job_id, name, "queued")
    return jsonify({"id": job_id, "status": "queued"})


@app.get("/jobs/<job_id>")
def get_job(job_id: str):
    auth = require_token()
    if auth:
        return auth
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "not_found"}), 404
    return jsonify(job)


def main():
    api_cfg = config.get("api", {})
    if not api_cfg.get("enabled", True):
        logging.info("API 未启用，退出")
        return

    host = api_cfg.get("host", "0.0.0.0")
    port = int(api_cfg.get("port", 5000))
    app.run(host=host, port=port)


if __name__ == "__main__":
    main()
