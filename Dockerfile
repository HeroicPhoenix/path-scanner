FROM crpi-v2fmzydhnzmlpzjc.cn-shanghai.personal.cr.aliyuncs.com/machenkai/python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    TZ=Asia/Shanghai

# 基础依赖（证书 + 时区）
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python 依赖
COPY requirements.txt /app/requirements.txt

RUN pip install --no-cache-dir -r requirements.txt \
    -i https://mirrors.aliyun.com/pypi/simple/ \
    && rm -rf /root/.cache/pip

# 项目代码
COPY app /app

# 约定挂载点
VOLUME ["/config", "/output", "/logs"]

# 启动 API（含调度器）
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "12084"]
