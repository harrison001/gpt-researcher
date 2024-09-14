#!/bin/bash
source /home/rocky/miniconda3/etc/profile.d/conda.sh
conda activate easyciteai_com

# 查找正在运行的Gunicorn进程
PID=$(pgrep -f "gunicorn -k uvicorn.workers.UvicornWorker -c gunicorn_conf.py gpt_researcher_main:app")

# 如果找到了进程，结束它
if [ ! -z "$PID" ]; then
    echo "Stopping existing Gunicorn process with PID: $PID"
    kill -9 $PID
fi

# 在后台启动新的Gunicorn进程，并将输出重定向到用户主目录下的日志文件
echo "Starting Gunicorn in the background..."
gunicorn -k uvicorn.workers.UvicornWorker -c gunicorn_conf.py gpt_researcher_main:app > ~/gunicorn.log 2>&1 &
GUNICORN_PID=$!

# 等待几秒钟让服务器启动
sleep 5

# 检查进程是否还在运行
if sudo ps -p $GUNICORN_PID > /dev/null
then
    echo "Gunicorn process started successfully with PID: $GUNICORN_PID"
    echo "Check ~/gunicorn.log for more details"
else
    echo "Error: Gunicorn process failed to start or exited immediately"
    echo "Last 20 lines of the log file:"
    sudo tail -n 20 ~/gunicorn.log
    exit 1
fi

# 进行健康检查

#if curl -s http://localhost:8097/health | grep -q "OK"; then
#    echo "Gunicorn has been started successfully and is healthy."
#else
#    echo "Error: Gunicorn may have failed to start or is not responding correctly."
#    exit 1
#fi