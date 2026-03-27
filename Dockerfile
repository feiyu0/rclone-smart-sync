FROM python:3.11-alpine

# 安装系统依赖
RUN apk add --no-cache \
    bash \
    curl \
    tzdata \
    sqlite \
    supervisor \
    inotify-tools \
    rclone \
    gcc \
    musl-dev \
    libffi-dev

# 设置工作目录
WORKDIR /app

# 复制文件
COPY app /app/app
COPY supervisord.conf /app/supervisord.conf
COPY requirements.txt /app/requirements.txt

# 安装 Python 依赖
RUN pip install --no-cache-dir -r requirements.txt

# 创建目录
RUN mkdir -p /app/data /app/logs

# 环境变量
ENV WATCH_ROOT=/data
ENV WEBUI_PORT=8080
ENV TZ=Asia/Shanghai

EXPOSE 8080

CMD ["/usr/bin/supervisord", "-c", "/app/supervisord.conf"]
