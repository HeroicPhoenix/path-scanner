# Path Scanner（路径扫描与清单生成工具）

适合群晖 NAS / Docker / Linux / macOS 长期运行的路径扫描工具：
- 定期递归扫描指定目录
- 生成文件/文件夹清单 CSV
- 本地历史自动清理
- 最新结果覆盖上传到阿里云 OSS
- 提供 API 触发扫描/上传/清理

---

## 1. 功能特性

- 递归扫描多个路径（自动去重父子路径）
- 输出 CSV（目录 + 文件）
- 忽略隐藏文件（如 `.DS_Store`）与群晖系统目录 `@eaDir`
- 每次生成 `scan_YYYYMMDD_HHMMSS.csv`
- 同步生成 `scan_latest.csv`
- 自动清理 N 天前历史 CSV
- OSS 覆盖上传 latest（可配置 N 天游间隔）
- FastAPI 接口手动触发扫描/上传/清理
- cron 定时调度

---

## 2. 目录结构

```text
path-scanner/
├── app/
│   ├── main.py
│   └── scanner.py
├── config/
│   └── config.json
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md
```

---

## 3. CSV 输出格式

| 列名 | 说明 |
|---|---|
| type | dir / file |
| root_path | 扫描根路径 |
| full_path | 文件或目录完整路径 |
| name | 目录名或文件名 |

---

## 4. 配置说明（config.json）

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
  "api": {
    "enabled": true,
    "host": "0.0.0.0",
    "port": 12084,
    "token": ""
  },
  "oss": {
    "enabled": true,
    "region": "cn-shanghai",
    "endpoint": "https://oss-cn-shanghai.aliyuncs.com",
    "bucket": "your-bucket-name",
    "prefix": "path-scanner/output",
    "latest_object": "scan_latest.csv",
    "upload_interval_days": 7,
    "access_key_id": "AKxxxxxxxx",
    "access_key_secret": "xxxxxxxx"
  }
}
```

### 关键字段

- `schedule.cron`：cron 表达式
- `retention.days`：本地历史 CSV 保留天数
- `paths`：需要扫描的路径列表
- `scan_options.follow_symlinks`：是否跟随软链接
- `scan_options.ignore_missing_path`：忽略不存在路径
- `api.enabled`：是否启用 API
- `api.host`/`api.port`：API 监听地址与端口
- `api.token`：API 访问令牌（为空则不校验）
- `oss.enabled`：是否启用 OSS 上传
- `oss.latest_object`：OSS 中 latest CSV 名称（覆盖式）
- `oss.upload_interval_days`：上传间隔天数（为空或 0 表示每次都上传）

---

## 5. 本地运行

安装依赖：

```bash
pip install -r requirements.txt
```

启动 API（包含定时调度）：

```bash
CONFIG_PATH=./config/config.json uvicorn main:app --host 0.0.0.0 --port 12084
```

---

## 6. API 使用

### 6.1 可用接口

- `GET /health` 健康检查
- `GET /actions` 返回可用动作列表
- `POST /scan` 触发扫描（等价于 `/actions/scan`）
- `POST /actions/upload_latest` 上传 latest CSV 到 OSS
- `POST /actions/cleanup` 清理历史 CSV
- `GET /jobs/{id}` 查询异步任务状态

### 6.2 调用示例

```bash
curl http://localhost:12084/actions
```

带 Token：

```bash
curl http://localhost:12084/actions -H "X-API-Token: your-token"
```

触发扫描（异步，默认）：

```bash
curl -X POST http://localhost:12084/scan
```

同步执行：

```bash
curl -X POST http://localhost:12084/scan \
  -H "Content-Type: application/json" \
  -d '{"mode":"sync"}'
```

---

## 7. Docker 运行

### 7.1 Dockerfile（镜像内默认启动 API）

```dockerfile
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "12084"]
```

### 7.2 docker-compose.yml

```yaml
services:
  path-scanner:
    image: crpi-v2fmzydhnzmlpzjc.cn-shanghai.personal.cr.aliyuncs.com/machenkai/path-scanner:latest
    container_name: path-scanner
    ports:
      - "12084:12084"
    volumes:
      - /volume1/docker/path-scanner/config/config.json:/config/config.json:ro
      - /volume1/docker/path-scanner/output:/output
      - /volume1/docker/path-scanner/logs:/logs
      - /volume1:/volume1:ro
    restart: always
```

启动：

```bash
docker compose up -d
```

---

## 8. OSS 行为说明

- 每次任务完成后生成 latest CSV
- OSS 中始终只保留一个 latest 文件（覆盖上传）
- 上传失败不影响本地扫描，只记录日志

---

## 9. 适用场景

- 群晖 NAS 文件资产盘点
- 媒体库清单生成
- 数据治理 / 文件审计
- OSS 对外系统拉取最新文件清单

---

## 10. License

MIT License
