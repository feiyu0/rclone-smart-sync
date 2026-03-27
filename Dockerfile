FROM alpine:3.19

# 安装基础依赖
RUN apk add --no-cache \
    python3 \
    py3-pip \
    bash \
    curl \
    tzdata \
    sqlite \
    supervisor \
    inotify-tools \
    rclone

# 设置工作目录
WORKDIR /app

# 复制项目文件
COPY app /app/app
COPY supervisord.conf /app/supervisord.conf
COPY requirements.txt /app/requirements.txt

# 安装 Python 依赖
RUN pip3 install --no-cache-dir -r requirements.txt

# 创建目录
RUN mkdir -p /app/data /app/logs

# 设置环境变量
ENV WATCH_ROOT=/data
ENV WEBUI_PORT=8080
ENV TZ=Asia/Shanghai

# 暴露端口
EXPOSE 8080

# 启动 supervisor
CMD ["/usr/bin/supervisord", "-c", "/app/supervisord.conf"]
