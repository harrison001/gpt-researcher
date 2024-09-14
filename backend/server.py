import json
import os
import re
import time
import bcrypt
import secrets
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, File, UploadFile, Header, Depends, HTTPException, status, Response, Cookie
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from threading import Lock
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials

security = HTTPBasic()

# 用于存储用户 token 的字典
user_tokens = {}

def authenticate(credentials: HTTPBasicCredentials = Depends(security)):
    stored_username = os.getenv("EASYCITE_USERNAME")
    stored_password_hash = os.getenv("EASYCITE_PASSWORD_HASH")  # 存储的是密码的哈希值

    if not (credentials.username == stored_username and 
            bcrypt.checkpw(credentials.password.encode('utf-8'), stored_password_hash.encode('utf-8'))):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

# Define the NoCacheMiddleware
class NoCacheMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

from backend.utils import write_md_to_pdf, write_md_to_word, write_text_to_md
from backend.websocket_manager import WebSocketManager

import shutil
from multi_agents.main import run_research_task
from gpt_researcher.document.document import DocumentLoader
from gpt_researcher.master.actions import stream_output


class ResearchRequest(BaseModel):
    task: str
    report_type: str
    agent: str

class ConfigRequest(BaseModel):
    ANTHROPIC_API_KEY: str
    TAVILY_API_KEY: str
    LANGCHAIN_TRACING_V2: str
    LANGCHAIN_API_KEY: str
    OPENAI_API_KEY: str
    DOC_PATH: str
    RETRIEVER: str
    GOOGLE_API_KEY: str = ''
    GOOGLE_CX_KEY: str = ''
    BING_API_KEY: str = ''
    SERPAPI_API_KEY: str = ''
    SERPER_API_KEY: str = ''
    SEARX_URL: str = ''

app = FastAPI()

# Add the NoCacheMiddleware
app.add_middleware(NoCacheMiddleware)

# Enable CORS for your frontend domain (adjust accordingly)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/site", StaticFiles(directory="./frontend"), name="site")
app.mount("/static", StaticFiles(directory="./frontend/static"), name="static")

templates = Jinja2Templates(directory="./frontend")

manager = WebSocketManager()
connection_lock = Lock()  # Lock for WebSocket connections
file_lock = Lock()  # Lock for file operations

# Dynamic directory for outputs once first research is run
@app.on_event("startup")
def startup_event():
    os.makedirs("outputs", exist_ok=True)
    app.mount("/outputs", StaticFiles(directory="outputs"), name="outputs")

@app.get("/health")
async def health_check():
    return {"status": "OK"}

@app.get("/")
async def read_root(request: Request):
    return templates.TemplateResponse(
        "index.html", {"request": request, "report": None}
    )


# Add the sanitize_filename function here
def sanitize_filename(filename):
    return re.sub(r"[^\w\s-]", "", filename).strip()

@app.post("/login")
def login(response: Response, credentials: HTTPBasicCredentials = Depends(security)):
    stored_username = os.getenv("EASYCITE_USERNAME")
    stored_password_hash = os.getenv("EASYCITE_PASSWORD_HASH")

    if not (credentials.username == stored_username and 
            bcrypt.checkpw(credentials.password.encode('utf-8'), stored_password_hash.encode('utf-8'))):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    
    # 生成 token
    token = secrets.token_urlsafe(32)
    user_tokens[token] = credentials.username

    response.set_cookie(key="session_token", value=token, httponly=True, secure=True)
    return {"message": "Login successful", "token": token}

@app.get("/check-login")
def check_login(session_token: str = Cookie(None)):
    if not session_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No session token")
    
    if session_token not in user_tokens:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session token")
    
    return {"message": "Authenticated", "token": session_token}

@app.post("/logout")
def logout(response: Response, session_token: str = Cookie(None)):
    if session_token in user_tokens:
        del user_tokens[session_token]
    response.delete_cookie(key="session_token")
    return {"message": "Logout successful"}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            if data.startswith("start"):
                json_data = json.loads(data[6:])
                task = json_data.get("task")
                report_type = json_data.get("report_type")
                source_urls = json_data.get("source_urls")
                tone = json_data.get("tone")
                headers = json_data.get("headers", {})
                filename = f"task_{int(time.time())}_{task}"
                sanitized_filename = sanitize_filename(filename)
                report_source = json_data.get("report_source")
                if task and report_type:
                    report = await manager.start_streaming(
                        task, report_type, report_source, source_urls, tone, websocket, headers
                    )
                    # 生成文件
                    md_file = await write_text_to_md(report, sanitized_filename)
                    pdf_file = await write_md_to_pdf(report, sanitized_filename)
                    word_file = await write_md_to_word(report, sanitized_filename)
                    
                    # 发送文件路径给客户端
                    await websocket.send_json({
                        "type": "files",
                        "md": md_file,
                        "pdf": pdf_file,
                        "word": word_file
                    })
            elif data.startswith("human_feedback"):
                # 处理人类反馈
                pass
            else:
                await websocket.send_text("Error: not enough parameters provided.")
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        print(f"WebSocket error: {str(e)}")

@app.post("/api/multi_agents")
async def run_multi_agents():
    websocket = manager.active_connections[0] if manager.active_connections else None
    if websocket:
        report = await run_research_task("Is AI in a hype cycle?", websocket, stream_output)
        return {"report": report}
    else:
        return JSONResponse(status_code=400, content={"message": "No active WebSocket connection"})

@app.get("/getConfig", dependencies=[Depends(authenticate)])
async def get_config(
    langchain_api_key: str = Header(None),
    openai_api_key: str = Header(None),
    tavily_api_key: str = Header(None),
    google_api_key: str = Header(None),
    google_cx_key: str = Header(None),
    bing_api_key: str = Header(None),
    serpapi_api_key: str = Header(None),
    serper_api_key: str = Header(None),
    searx_url: str = Header(None)
):
    config = {
        "LANGCHAIN_API_KEY": langchain_api_key if langchain_api_key else os.getenv("LANGCHAIN_API_KEY", ""),
        "OPENAI_API_KEY": openai_api_key if openai_api_key else os.getenv("OPENAI_API_KEY", ""),
        "TAVILY_API_KEY": tavily_api_key if tavily_api_key else os.getenv("TAVILY_API_KEY", ""),
        "GOOGLE_API_KEY": google_api_key if google_api_key else os.getenv("GOOGLE_API_KEY", ""),
        "GOOGLE_CX_KEY": google_cx_key if google_cx_key else os.getenv("GOOGLE_CX_KEY", ""),
        "BING_API_KEY": bing_api_key if bing_api_key else os.getenv("BING_API_KEY", ""),
        "SERPAPI_API_KEY": serpapi_api_key if serpapi_api_key else os.getenv("SERPAPI_API_KEY", ""),
        "SERPER_API_KEY": serper_api_key if serper_api_key else os.getenv("SERPER_API_KEY", ""),
        "SEARX_URL": searx_url if searx_url else os.getenv("SEARX_URL", ""),
        "LANGCHAIN_TRACING_V2": os.getenv("LANGCHAIN_TRACING_V2", "true"),
        "DOC_PATH": os.getenv("DOC_PATH", ""),
        "RETRIEVER": os.getenv("RETRIEVER", ""),
        "EMBEDDING_MODEL": os.getenv("OPENAI_EMBEDDING_MODEL", "")
    }
    return config

@app.post("/setConfig", dependencies=[Depends(authenticate)])
async def set_config(config: ConfigRequest):
    os.environ["ANTHROPIC_API_KEY"] = config.ANTHROPIC_API_KEY
    os.environ["TAVILY_API_KEY"] = config.TAVILY_API_KEY
    os.environ["LANGCHAIN_TRACING_V2"] = config.LANGCHAIN_TRACING_V2
    os.environ["LANGCHAIN_API_KEY"] = config.LANGCHAIN_API_KEY
    os.environ["OPENAI_API_KEY"] = config.OPENAI_API_KEY
    os.environ["DOC_PATH"] = config.DOC_PATH
    os.environ["RETRIEVER"] = config.RETRIEVER
    os.environ["GOOGLE_API_KEY"] = config.GOOGLE_API_KEY
    os.environ["GOOGLE_CX_KEY"] = config.GOOGLE_CX_KEY
    os.environ["BING_API_KEY"] = config.BING_API_KEY
    os.environ["SERPAPI_API_KEY"] = config.SERPAPI_API_KEY
    os.environ["SERPER_API_KEY"] = config.SERPER_API_KEY
    os.environ["SEARX_URL"] = config.SEARX_URL
    return {"message": "Config updated successfully"}

# Define DOC_PATH
DOC_PATH = os.getenv("DOC_PATH", "./my-docs")
if not os.path.exists(DOC_PATH):
    os.makedirs(DOC_PATH)


@app.post("/upload/")
async def upload_file(file: UploadFile = File(...)):
    with file_lock:  # Ensure file operations are thread-safe
        file_path = os.path.join(DOC_PATH, file.filename)
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        print(f"File uploaded to {file_path}")

        # Load documents after upload
        document_loader = DocumentLoader(DOC_PATH)
        await document_loader.load()

    return {"filename": file.filename, "path": file_path}


@app.get("/files/")
async def list_files():
    files = os.listdir(DOC_PATH)
    print(f"Files in {DOC_PATH}: {files}")
    return {"files": files}

@app.delete("/files/{filename}")
async def delete_file(filename: str):
    with file_lock:  # Ensure file operations are thread-safe
        file_path = os.path.join(DOC_PATH, filename)
        if os.path.exists(file_path):
            os.remove(file_path)
            print(f"File deleted: {file_path}")
            return {"message": "File deleted successfully"}
        else:
            print(f"File not found: {file_path}")
            return JSONResponse(status_code=404, content={"message": "File not found"})
