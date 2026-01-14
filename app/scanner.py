import os
import csv
import json
import time
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import List

import alibabacloud_oss_v2 as oss
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from zoneinfo import ZoneInfo


CONFIG_PATH = os.environ.get(
    "CONFIG_PATH",
    "/config/config.json"
)

LATEST_CSV_NAME = "scan_latest.csv"
OSS_UPLOAD_MARKER = ".last_oss_upload"


# ---------- 配置 ----------

def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------- 日志 ----------

def setup_logging(cfg: dict):
    log_dir = Path(cfg["directory"])
    log_dir.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=getattr(logging, cfg.get("level", "INFO")),
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_dir / "scanner.log"),
            logging.StreamHandler()
        ],
    )


# ---------- 路径处理 ----------

def normalize_paths(paths: List[str]) -> List[Path]:
    return [Path(p).resolve() for p in paths]


def deduplicate_parent_paths(paths: List[Path]) -> List[Path]:
    roots: List[Path] = []
    for p in sorted(paths):
        if not any(p.is_relative_to(r) for r in roots):
            roots.append(p)
    return roots


# ---------- 扫描逻辑 ----------

def scan_root(root: Path, follow_symlinks: bool):
    for dirpath, dirnames, filenames in os.walk(
        root, followlinks=follow_symlinks
    ):
        dirpath = Path(dirpath)

        # 跳过隐藏目录和群晖系统目录
        dirnames[:] = [
            d for d in dirnames
            if not (d.startswith(".") or d == "@eaDir")
        ]

        # 目录
        for d in dirnames:
            yield {
                "type": "dir",
                "root_path": str(root),
                "full_path": str(dirpath / d),
                "name": d
            }

        # 文件
        for f in filenames:
            if f.startswith(".") or f == "@eaDir":
                continue
            yield {
                "type": "file",
                "root_path": str(root),
                "full_path": str(dirpath / f),
                "name": f
            }


# ---------- CSV 输出 ----------

def write_csv(rows, output_file: Path):
    fieldnames = [
        "type",
        "root_path",
        "full_path",
        "name"
    ]
    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


# ---------- 本地历史 CSV 清理 ----------

def cleanup_old_outputs(output_dir: Path, keep_days: int):
    expire_before = datetime.now() - timedelta(days=keep_days)
    pattern = re.compile(r"^scan_\d{8}_\d{6}\.csv$")

    removed = 0
    for f in output_dir.iterdir():
        if not f.is_file():
            continue

        if f.name == LATEST_CSV_NAME:
            continue

        if not pattern.match(f.name):
            continue

        mtime = datetime.fromtimestamp(f.stat().st_mtime)
        if mtime < expire_before:
            f.unlink()
            removed += 1

    logging.info(
        "历史 CSV 清理完成：删除 %d 个，保留最近 %d 天",
        removed,
        keep_days
    )


# ---------- OSS（v2 SDK）：上传 latest CSV ----------

def should_upload_to_oss(oss_cfg: dict, output_dir: Path) -> bool:
    interval_days = oss_cfg.get("upload_interval_days")
    if not interval_days:
        return True

    marker_path = output_dir / OSS_UPLOAD_MARKER
    if not marker_path.exists():
        return True

    try:
        last_ts = float(marker_path.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return True

    elapsed = time.time() - last_ts
    return elapsed >= interval_days * 86400


def mark_oss_upload(output_dir: Path):
    marker_path = output_dir / OSS_UPLOAD_MARKER
    marker_path.write_text(str(time.time()), encoding="utf-8")


def upload_latest_csv_to_oss(config: dict, latest_csv: Path, output_dir: Path):
    oss_cfg = config.get("oss")
    if not oss_cfg or not oss_cfg.get("enabled", False):
        return

    if not latest_csv.exists():
        logging.warning("latest CSV 不存在，跳过 OSS 上传")
        return

    if not should_upload_to_oss(oss_cfg, output_dir):
        logging.info("未到 OSS 上传间隔，跳过本次上传")
        return

    try:
        # 1. AK/SK（来自 config.json）
        credentials_provider = oss.credentials.StaticCredentialsProvider(
            oss_cfg["access_key_id"],
            oss_cfg["access_key_secret"]
        )

        # 2. 加载默认配置
        cfg = oss.config.load_default()
        cfg.credentials_provider = credentials_provider
        cfg.region = oss_cfg["region"]

        if oss_cfg.get("endpoint"):
            cfg.endpoint = oss_cfg["endpoint"]

        # 3. 创建客户端
        client = oss.Client(cfg)

        object_key = f'{oss_cfg["prefix"].rstrip("/")}/{oss_cfg["latest_object"]}'

        # 4. 覆盖式上传（等价 删除旧 + 上传新）
        result = client.put_object_from_file(
            oss.PutObjectRequest(
                bucket=oss_cfg["bucket"],
                key=object_key
            ),
            str(latest_csv)
        )

        logging.info(
            "最新 CSV 已上传至 OSS：%s (request_id=%s)",
            object_key,
            result.request_id
        )
        mark_oss_upload(output_dir)

    except Exception as e:
        logging.exception("上传 latest CSV 到 OSS 失败：%s", e)


# ---------- 核心任务 ----------

def scan_task(config: dict):
    logging.info("开始扫描任务")

    paths_cfg = config["paths"]
    options = config["scan_options"]
    output_cfg = config["output"]

    raw_paths = normalize_paths(paths_cfg)
    roots = deduplicate_parent_paths(raw_paths)

    logging.info("最终扫描根路径：%s", roots)

    rows = []
    for root in roots:
        if not root.exists():
            msg = f"路径不存在：{root}"
            if options.get("ignore_missing_path", True):
                logging.warning(msg)
                continue
            else:
                raise RuntimeError(msg)

        rows.extend(
            scan_root(root, options.get("follow_symlinks", False))
        )

    ts = time.strftime("%Y%m%d_%H%M%S")
    out_dir = Path(output_cfg["directory"])
    out_dir.mkdir(parents=True, exist_ok=True)

    output_file = out_dir / f"scan_{ts}.csv"
    write_csv(rows, output_file)

    latest_csv = out_dir / output_cfg["latest_filename"]
    latest_csv.write_bytes(output_file.read_bytes())

    logging.info("扫描完成，共 %d 条记录，输出 %s", len(rows), output_file)

    # ---------- 本地历史清理 ----------
    retention_days = config.get("retention", {}).get("days")
    if retention_days:
        cleanup_old_outputs(out_dir, retention_days)

    # ---------- OSS 上传 latest CSV ----------
    upload_latest_csv_to_oss(config, latest_csv, out_dir)


# ---------- 启动 ----------

def main():
    config = load_config(CONFIG_PATH)
    setup_logging(config["logging"])

    scheduler = BlockingScheduler(
        timezone=ZoneInfo(config["schedule"]["timezone"])
    )

    trigger = CronTrigger.from_crontab(config["schedule"]["cron"])

    scheduler.add_job(
        scan_task,
        trigger,
        args=[config],
        id="path_scan_job",
        replace_existing=True,
    )

    logging.info(
        "调度器启动：cron=%s timezone=%s",
        config["schedule"]["cron"],
        config["schedule"]["timezone"],
    )

    scheduler.start()


if __name__ == "__main__":
    main()
