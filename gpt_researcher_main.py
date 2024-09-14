from backend.server import app
from dotenv import load_dotenv
load_dotenv()

# 移除对 Config 的导入
# from gunicorn_conf import Config  # 这行应该被删除或注释掉

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8097)
