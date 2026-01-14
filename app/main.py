import logging
import os
import threading
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from zoneinfo import ZoneInfo

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

app = FastAPI()

config = load_config(CONFIG_PATH)
setup_logging(config["logging"])

scan_lock = threading.Lock()
jobs = {}
scheduler = None


def require_token(x_api_token: str):
    api_cfg = config.get("api", {})
    token = api_cfg.get("token")
    if token and x_api_token != token:
        raise HTTPException(status_code=401, detail="unauthorized")


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


def start_scheduler():
    sched = BackgroundScheduler(
        timezone=ZoneInfo(config["schedule"]["timezone"])
    )
    trigger = CronTrigger.from_crontab(config["schedule"]["cron"])
    sched.add_job(
        scan_task,
        trigger,
        args=[config],
        id="path_scan_job",
        replace_existing=True,
    )
    sched.start()
    logging.info(
        "调度器启动：cron=%s timezone=%s",
        config["schedule"]["cron"],
        config["schedule"]["timezone"],
    )
    return sched


@app.on_event("startup")
def on_startup():
    api_cfg = config.get("api", {})
    if not api_cfg.get("enabled", True):
        logging.info("API 未启用")
        return
    global scheduler
    scheduler = start_scheduler()


@app.on_event("shutdown")
def on_shutdown():
    if scheduler:
        scheduler.shutdown(wait=False)


@app.get("/health")
def health(x_api_token: str = Header(default="")):
    require_token(x_api_token)
    return {"status": "ok"}


@app.get("/actions")
def list_actions(x_api_token: str = Header(default="")):
    require_token(x_api_token)
    return {"actions": sorted(ACTIONS.keys())}


@app.post("/scan")
async def trigger_scan(request: Request, x_api_token: str = Header(default="")):
    return await trigger_action("scan", request, x_api_token)


@app.post("/actions/{name}")
async def trigger_action(
    name: str,
    request: Request,
    x_api_token: str = Header(default="")
):
    require_token(x_api_token)

    fn = ACTIONS.get(name)
    if not fn:
        raise HTTPException(status_code=404, detail="unknown_action")

    try:
        payload = await request.json()
    except Exception:
        payload = {}
    mode = payload.get("mode", "async")

    job_id = uuid.uuid4().hex

    if mode == "sync":
        run_action(name, fn, job_id)
        return jobs[job_id]

    thread = threading.Thread(
        target=run_action,
        args=(name, fn, job_id),
        daemon=True,
    )
    thread.start()
    record_job(job_id, name, "queued")
    return {"id": job_id, "status": "queued"}


@app.get("/jobs/{job_id}")
def get_job(job_id: str, x_api_token: str = Header(default="")):
    require_token(x_api_token)
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="not_found")
    return job
