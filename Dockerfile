# 使用官方Python运行时作为父镜像
FROM python:3.10-slim

# 设置工作目录
WORKDIR /app

# 复制依赖文件
COPY requirements.txt .

# 安装Python依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目文件
COPY . .

# 暴露Flask默认端口
EXPOSE 5000

# 设置启动命令
CMD ["python", "app.py"]