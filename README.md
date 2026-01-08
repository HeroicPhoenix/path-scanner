# Path Scanner（路径扫描与清单生成工具）

一个适合 **群晖 NAS / Docker / Linux / macOS** 长期运行的路径扫描工具，用于：
- 定期递归扫描指定目录
- 生成完整的文件 / 文件夹清单 CSV
- 本地保留历史结果（自动清理）
- 将 **最新扫描结果 CSV** 上传到 **阿里云 OSS（覆盖式 latest）**

---

## 一、功能特性

- ✅ 递归扫描多个路径（自动去重父子路径）
- ✅ 输出 CSV（目录 + 文件，文件名单独列）
- ✅ 每次生成 `scan_YYYYMMDD_HHMMSS.csv`
- ✅ 同步生成 `scan_latest.csv`
- ✅ 自动清理 N 天前的历史 CSV
- ✅ 使用 **阿里云 OSS Python SDK v2（官方）**
- ✅ OSS 中始终只保留一个 `scan_latest.csv`
- ✅ 支持 cron 定时任务
- ✅ 支持 Docker / Docker Compose
- ✅ 支持本地直接运行

---

## 二、目录结构

```text
path-scanner/
├── app/
│   └── scanner.py
├── config/
│   └── config.json
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md
```

---

## 三、CSV 输出格式

| 列名 | 说明 |
|---|---|
| type | dir / file |
| root_path | 扫描根路径 |
| full_path | 文件或目录完整路径 |
| name | 目录名或文件名 |
| filename | 文件名（仅 file 行有值） |

---

## 四、配置说明（config.json）

### 示例

```json
{
  "schedule": {
    "cron": "0 1 * * *",
    "timezone": "Asia/Shanghai"
  },
  "retention": {
    "days": 30
  },
  "paths": [
    "/volume1/music",
    "/volume1/video",
    "/volume1/homes"
  ],
  "output": {
    "directory": "/output",
    "latest_filename": "scan_latest.csv"
  },
  "scan_options": {
    "follow_symlinks": false,
    "ignore_missing_path": true
  },
  "logging": {
    "directory": "/logs",
    "level": "INFO"
  },
  "oss": {
    "enabled": true,
    "region": "cn-shanghai",
    "endpoint": "https://oss-cn-shanghai.aliyuncs.com",
    "bucket": "your-bucket-name",
    "prefix": "path-scanner/output",
    "latest_object": "scan_latest.csv",
    "access_key_id": "AKxxxxxxxx",
    "access_key_secret": "xxxxxxxx"
  }
}
```

### 关键字段说明

- `schedule.cron`：cron 表达式（示例为每天 1 点）
- `retention.days`：本地历史 CSV 保留天数
- `paths`：需要扫描的路径列表
- `follow_symlinks`：是否跟随软链接（建议 false）
- `oss.enabled`：是否启用 OSS 上传
- `latest_object`：OSS 中 latest CSV 名称（固定覆盖）

---

## 五、本地运行（macOS / Linux）

### 1️⃣ 安装依赖

```bash
pip install -r requirements.txt
```

### 2️⃣ 运行

```bash
CONFIG_PATH=./config/config.json python app/scanner.py
```

---

## 六、Docker 运行

### Dockerfile

```dockerfile
FROM python:3.10-slim

WORKDIR /app
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY app /app

VOLUME ["/config", "/output", "/logs"]

CMD ["python", "/app/scanner.py"]
```

### docker-compose.yml

```yaml
services:
  path-scanner:
    image: machenkai/path-scanner:latest
    container_name: path-scanner
    volumes:
      - ./config/config.json:/config/config.json:ro
      - ./output:/output
      - ./logs:/logs
      - /volume1:/volume1:ro
    restart: always
```

启动：

```bash
docker compose up -d
```

---

## 七、OSS 行为说明

- 每次任务完成后：
  - 本地生成最新 CSV
  - 覆盖上传 OSS 中的 `scan_latest.csv`
- OSS 中：
  - **始终只有一个 latest 文件**
  - 不保存历史版本
- OSS 上传失败：
  - 不影响本地扫描
  - 仅记录日志

---

## 八、适用场景

- 群晖 NAS 文件资产盘点
- 媒体库清单生成
- 数据治理 / 文件审计
- OSS 对外系统拉取最新文件清单
- 长期定时运维任务

---

## 九、安全建议

⚠️ 生产环境建议：
- 使用 **RAM 子账号**
- 只授予 `PutObject` 权限
- 可后续改为环境变量方式传递 AK

---

## 十、License

MIT License
