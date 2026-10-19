import asyncio
import json
import logging
import sys
import threading
import time
import hashlib

_fmt = logging.Formatter(
    fmt="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
_fmt.converter = time.gmtime

logging.basicConfig(level=logging.INFO)
logging.root.handlers[0].setFormatter(_fmt)

for _name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
    _logger = logging.getLogger(_name)
    for _h in _logger.handlers:
        _h.setFormatter(_fmt)
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import base64

from Crypto.PublicKey import RSA as CryptoRSA
from Crypto.Cipher import PKCS1_v1_5

import websocket
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Form, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import event_log
from config import (
    get_config, save_config, get_course_config, update_course_config,
    get_ai_config, update_ai_config,
    get_audio_config, update_audio_config, STORE_DIR,
    get_domain, set_domain,
    make_headers, api_url, http_request,
    DEFAULT_COURSE_CONFIG, DOMAIN_OPTIONS,
)
from monitor import Monitor
from runtime import get_runtime, save_runtime
from app_version import VERSION
from resources import resource_path

# API URLs (used only in main.py)
URL_WSS = "wss://{domain}/wsapp/"
URL_USER_INFO = "https://{domain}/api/v3/user/basic-info"
URL_COURSE_LIST = "https://{domain}/v2/api/web/courses/list?identity=2"
URL_WEB_LOGIN = "https://{domain}/pc/web_login"
URL_PASSWORD_LOGIN = "https://{domain}/pc/login/verify_pwd_login/"
URL_GET_PUBLIC_KEY = "https://{domain}/pc/register/get_pws_public_key/"

# ---------------------------------------------------------------------------
# Application state
# ---------------------------------------------------------------------------

event_queue: asyncio.Queue = asyncio.Queue()
_subscribers: set[asyncio.Queue] = set()
monitor: Optional[Monitor] = None
_auth_verified = False


def get_monitor() -> Optional[Monitor]:
    return monitor


def set_monitor(m: Optional[Monitor]) -> None:
    global monitor
    monitor = m


def _handle_session_expired() -> None:
    global _auth_verified
    _auth_verified = False
    cfg = get_config()
    cfg["sessionid"] = ""
    cfg["user"] = {}
    cfg["course_list"] = []
    save_config(cfg)


def _restart_monitor(sessionid: str) -> None:
    loop = asyncio.get_event_loop()
    m = get_monitor()
    if m:
        m.stop()
    m = Monitor(sessionid=sessionid, event_queue=event_queue, on_session_expired=_handle_session_expired)
    set_monitor(m)
    m.start(loop)


# ---------------------------------------------------------------------------
# Startup cache helper
# ---------------------------------------------------------------------------


def _refresh_local_cache(sessionid: str) -> None:
    global _auth_verified
    cfg = get_config()
    headers = make_headers(sessionid)

    response = http_request("GET", api_url(URL_USER_INFO), headers=headers, retries=1)
    body = response.json()
    if not response.ok or body.get("code") != 0 or not (body.get("data") or {}).get("id"):
        _auth_verified = False
        raise ValueError("服务器未确认用户登录")
    cfg = get_config()
    cfg["user"] = body["data"]
    save_config(cfg)
    _auth_verified = True

    try:
        response_data = http_request("GET", api_url(URL_COURSE_LIST), headers=headers, retries=1).json()
    except Exception as exc:
        logging.getLogger("auth").warning("用户已验证，课程列表请求暂不可用：%s", type(exc).__name__)
        return

    # 检查是否包含 data
    if not isinstance(response_data.get("data"), dict):
        logging.getLogger("auth").warning("课程列表暂不可用，请刷新课程")
        return
    else:
        raw_courses = response_data["data"].get("list", [])
    course_list = [
        {
            "classroom_id": str(c["classroom_id"]),
            "name": c["course"]["name"],
            "classroom_name": c["name"],
            "teacher_name": c["teacher"]["name"],
        }
        for c in raw_courses
    ]
    cfg = get_config()
    cfg["course_list"] = course_list

    courses = cfg.setdefault("courses", {})
    for c in course_list:
        cid = c["classroom_id"]
        if cid not in courses:
            courses[cid] = {"name": c["name"], **DEFAULT_COURSE_CONFIG}
        elif courses[cid].get("name") != c["name"]:
            courses[cid]["name"] = c["name"]

    save_config(cfg)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


async def _broadcast_events():
    while True:
        event = await event_queue.get()
        dead: list[asyncio.Queue] = []
        for q in _subscribers:
            if q.full():
                dead.append(q)
            else:
                q.put_nowait(event)
        for q in dead:
            _subscribers.discard(q)


@asynccontextmanager
async def lifespan(app: FastAPI):
    loop = asyncio.get_event_loop()
    event_log.sanitize_storage()

    audio_dir = STORE_DIR / "audio"
    if audio_dir.exists():
        for f in audio_dir.iterdir():
            try:
                f.unlink()
            except:
                pass
        try:
            audio_dir.rmdir()
        except:
            pass

    broadcaster = asyncio.create_task(_broadcast_events())

    cfg = get_config()
    if cfg.get("sessionid"):
        try:
            await asyncio.to_thread(_refresh_local_cache, cfg["sessionid"])
        except Exception as exc:
            logging.getLogger("auth").warning("启动登录验证未完成：%s", type(exc).__name__)
        _restart_monitor(cfg["sessionid"])

    yield

    broadcaster.cancel()

    m = get_monitor()
    if m:
        m.stop()


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(title="Yuketang Helper API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class NotificationSub(BaseModel):
    enabled: bool
    signin: bool
    problem: bool
    call: bool
    danmu: bool
    red_packet: bool = True


class CourseConfig(BaseModel):
    type1: str
    type2: str
    type3: str
    type4: str
    type5: str
    answer_delay_min: int
    answer_delay_max: int
    answer_last5s: bool = True
    auto_danmu: bool
    auto_redpacket: bool = True
    danmu_threshold: int
    notification: NotificationSub
    voice_notification: NotificationSub


class AIKeyEntry(BaseModel):
    name: str
    provider: str
    key: str
    base_url: Optional[str] = None
    model: Optional[str] = None

class AIActiveKey(BaseModel):
    active_key: int


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------


@app.get("/api/domain")
async def get_domain_setting():
    return {"domain": get_domain(), "options": DOMAIN_OPTIONS}


@app.put("/api/domain")
async def update_domain_setting(body: dict):
    domain = body.get("domain", "")
    valid_keys = {opt["key"] for opt in DOMAIN_OPTIONS}
    if domain not in valid_keys:
        return {"ok": False, "error": "Invalid domain"}
    if get_config().get("sessionid") and domain != get_domain():
        return {"ok": False, "error": "切换服务器前请先退出登录"}
    set_domain(domain)
    return {"ok": True, "domain": domain}


@app.get("/api/auth/status")
async def auth_status():
    cfg = get_config()
    if not cfg.get("sessionid"):
        return {"logged_in": False, "user": None}
    return {"logged_in": _auth_verified, "user": cfg["user"] if _auth_verified else None}


@app.get("/api/user/avatar")
async def user_avatar():
    from fastapi.responses import Response as HttpResponse
    cfg = get_config()
    avatar_url = cfg.get("user", {}).get("avatar", "")
    if not avatar_url:
        return HttpResponse(status_code=404, content=b"", media_type="image/png")
    try:
        r = http_request("GET", avatar_url, timeout=10)
        content_type = r.headers.get("Content-Type", "image/png").split(";")[0].strip()
        return HttpResponse(content=r.content, media_type=content_type)
    except Exception:
        return HttpResponse(status_code=502, content=b"", media_type="image/png")


@app.post("/api/auth/logout")
async def auth_logout():
    global _auth_verified
    _auth_verified = False
    cfg = get_config()
    cfg["sessionid"] = ""
    cfg["user"] = {}
    cfg["course_list"] = []
    save_config(cfg)

    m = get_monitor()
    if m:
        m.stop()
        set_monitor(None)

    return {"ok": True}


class PasswordLoginBody(BaseModel):
    phone: str
    password: str
    ticket: str
    randstr: str


@app.post("/api/auth/password-login")
async def password_login(body: PasswordLoginBody):
    log = logging.getLogger("auth")
    domain = get_domain()

    # Fetch RSA public key from Yuketang
    key_r = http_request("GET", api_url(URL_GET_PUBLIC_KEY),
        headers={"Referer": f"https://{domain}/"},
    )
    pub_pem = key_r.json()["data"]["public_key"]
    cipher = PKCS1_v1_5.new(CryptoRSA.import_key(pub_pem))
    encrypted = base64.b64encode(cipher.encrypt(body.password.encode())).decode()

    login_url = api_url(URL_PASSWORD_LOGIN)
    payload = {
        "name": body.phone,
        "pwd": encrypted,
        "type": "PP",
        "ticket": body.ticket,
        "randstr": body.randstr,
        "hcaptcha_token": "",
    }
    log.info("Sending password login to %s", domain)

    r = http_request("POST", login_url,
        json=payload,
        headers={
            "Content-Type": "application/json",
            "Referer": f"https://{domain}/",
        },
    )

    log.info("Response: status=%s", r.status_code)

    data = r.json()
    if not data.get("success"):
        return {"ok": False, "error": data.get("msg") or str(data)}

    sessionid = r.cookies["sessionid"]

    cfg = get_config()
    cfg["sessionid"] = sessionid
    save_config(cfg)

    _refresh_local_cache(sessionid)
    user = get_config()["user"]

    _restart_monitor(sessionid)

    return {"ok": True, "user": user}


# ---------------------------------------------------------------------------
# Login WebSocket
# ---------------------------------------------------------------------------


@app.websocket("/ws/login")
async def ws_login(ws: WebSocket):
    await ws.accept()
    loop = asyncio.get_running_loop()
    login_queue = asyncio.Queue()
    stopped = threading.Event()
    login_domain = get_domain()

    def emit(message):
        if not stopped.is_set() and not loop.is_closed():
            asyncio.run_coroutine_threadsafe(login_queue.put(message), loop)

    def request_qr(wsapp):
        wsapp.send(json.dumps({"op": "requestlogin", "role": "web", "version": 1.4, "type": "qrcode", "from": "web"}))

    def on_message(wsapp, message):
        try:
            data = json.loads(message)
            if get_domain() != login_domain:
                raise ValueError("服务器已改变，请重新获取二维码")
            if data.get("op") == "requestlogin":
                resp = http_request("GET", data["ticket"], retries=1)
                resp.raise_for_status()
                content_type = resp.headers.get("Content-Type", "image/png").split(";")[0]
                if not content_type.startswith("image/"): raise ValueError("二维码下载未返回图片")
                emit({"type": "qr", "url": f"data:{content_type};base64,{base64.b64encode(resp.content).decode()}"})
            elif data.get("op") == "loginsuccess":
                r = http_request("POST", api_url(URL_WEB_LOGIN), data=json.dumps({"UserID": data["UserID"], "Auth": data["Auth"]}), retries=1)
                r.raise_for_status()
                sessionid = r.cookies.get("sessionid")
                if not sessionid: raise ValueError("登录响应缺少 sessionid")
                cfg = get_config()
                cfg["sessionid"] = sessionid
                save_config(cfg)
                _refresh_local_cache(sessionid)
                emit({"type": "success", "user": get_config()["user"]})
                wsapp.close()
        except Exception as exc:
            emit({"type": "error", "message": f"登录尚未验证成功：{type(exc).__name__}，请刷新二维码重试"})

    def on_error(wsapp, error):
        emit({"type": "error", "message": f"登录连接失败：{type(error).__name__}，请刷新重试"})

    wsapp = websocket.WebSocketApp(url=api_url(URL_WSS), on_open=request_qr, on_message=on_message, on_error=on_error)
    threading.Thread(target=wsapp.run_forever, daemon=True, name="login-ws").start()

    def refresh():
        while not stopped.wait(55):
            try:
                if wsapp.sock and wsapp.sock.connected: request_qr(wsapp)
            except Exception: break
    threading.Thread(target=refresh, daemon=True, name="login-qr-refresh").start()
    incoming = asyncio.create_task(ws.receive())
    outgoing = None
    try:
        while True:
            outgoing = asyncio.create_task(login_queue.get())
            done, _ = await asyncio.wait({incoming, outgoing}, return_when=asyncio.FIRST_COMPLETED)
            if incoming in done:
                break
            message = outgoing.result()
            await ws.send_json(message)
            if message["type"] == "success":
                _restart_monitor(get_config()["sessionid"])
                break
            if message["type"] == "error": break
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        stopped.set()
        incoming.cancel()
        if outgoing: outgoing.cancel()
        wsapp.close()


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Course routes
# ---------------------------------------------------------------------------


@app.get("/api/courses/active")
async def get_active_courses():
    m = get_monitor()
    if not m:
        return {"lessons": []}
    return {"lessons": m.get_active_lessons()}


@app.get("/api/courses/all")
async def get_all_courses_endpoint():
    cfg = get_config()
    if not cfg.get("sessionid"):
        return []
    cached = cfg.get("course_list", [])
    m = get_monitor()
    active_map: dict = {}
    if m:
        for lesson in m.discovered:
            active_map[str(lesson["classroomid"])] = lesson["lessonid"]
    return [
        {
            "classroom_id": c["classroom_id"],
            "name": c["name"],
            "classroom_name": c["classroom_name"],
            "teacher_name": c["teacher_name"],
            "active": c["classroom_id"] in active_map,
        }
        for c in cached
    ]


@app.get("/api/courses/defaults")
async def get_course_defaults():
    return DEFAULT_COURSE_CONFIG


@app.get("/api/courses/settings")
async def get_all_course_settings():
    cfg = get_config()
    return {cid: get_course_config(cid) for cid in cfg.get("courses", {})}


@app.get("/api/courses/settings/{course_id}")
async def get_course_settings(course_id: str):
    return get_course_config(course_id)


@app.put("/api/courses/settings/{course_id}")
async def update_course_settings(course_id: str, body: CourseConfig):
    data = body.model_dump()
    update_course_config(course_id, data)

    m = get_monitor()
    if m:
        with m._lock:
            lesson = next(
                (l for l in m._active_lessons.values() if str(l.classroomid) == course_id),
                None,
            )
        if lesson:
            lesson.course_config.update(data)

    return {"ok": True, "course_id": course_id, "config": data}


# ---------------------------------------------------------------------------
# AI settings routes
# ---------------------------------------------------------------------------


@app.post("/api/ai/test")
async def test_ai_key(
    provider: str = Form(...),
    key: Optional[str] = Form(None),
    key_index: Optional[str] = Form(default=None),
    image: UploadFile = File(...),
):
    # Multipart form may send key_index as a string; Optional[int] sometimes fails to bind — parse explicitly.
    idx: Optional[int] = None
    if key_index is not None and str(key_index).strip() != "":
        try:
            idx = int(key_index)
        except ValueError:
            return {"ok": False, "error": "Invalid key index"}

    key_entry: Optional[dict] = None
    if idx is not None:
        cfg = get_ai_config()
        if idx < 0 or idx >= len(cfg["keys"]):
            return {"ok": False, "error": "Invalid key index"}
        key_entry = cfg["keys"][idx]
        key = key_entry["key"]
        provider = key_entry.get("provider") or ""
        _logger.info("Testing AI provider: %s using key index: %d", provider, idx)
    else:
        if not provider or not key:
            return {"ok": False, "error": "Missing provider or key"}
        _logger.info("Testing AI provider: %s, key length: %d", provider, len(key))
    
    # Require image for testing
    if not image:
        return {"ok": False, "error": "Image is required for testing"}
    
    from ai_provider import create_provider, create_provider_from_entry, describe_provider_failure
    try:
        if idx is not None and key_entry is not None:
            ai_client = create_provider_from_entry(key_entry)
            if not ai_client:
                _logger.error("Failed to create provider from entry: %s", key_entry.get("provider"))
                return {"ok": False, "error": describe_provider_failure(key_entry)}
        else:
            ai_client = create_provider(provider, key)
            if not ai_client:
                _logger.error("Failed to create provider: %s", provider)
                return {
                    "ok": False,
                    "error": (
                        f"Invalid provider: {provider}. "
                        "Use google, qwen, dashscope, moonshot, or add a custom OpenAI-compatible key with Base URL and model."
                    ),
                }
        
        image_bytes = await image.read()
        _logger.info("Test image size: %d bytes", len(image_bytes))

        _logger.info("Calling test_call for provider: %s", provider)
        result = await asyncio.to_thread(ai_client.test_call, image_bytes=image_bytes)
        _logger.info("Test successful: %s", result[:100] + "..." if len(result) > 100 else result)
        return {"ok": True, "message": result}
    except Exception as e:
        _logger.error("AI test failed: %s", type(e).__name__)
        return {"ok": False, "error": "AI 请求未通过：" + type(e).__name__}


@app.get("/api/ai/settings")
async def get_ai_settings():
    from ai_provider import effective_ai_entry

    cfg = get_ai_config()
    masked_keys = []
    for entry in cfg["keys"]:
        eff = effective_ai_entry(entry)
        raw = eff["key"]
        masked = raw[:4] + "****" + raw[-4:] if len(raw) > 8 else "****"
        masked_keys.append({**eff, "key": masked})
    return {"keys": masked_keys, "active_key": cfg["active_key"], "fallback_keys": cfg.get("fallback_keys", True)}


@app.post("/api/ai/keys")
async def add_ai_key(body: AIKeyEntry):
    cfg = get_ai_config()
    keys = cfg["keys"]
    keys.append(body.model_dump())
    active = cfg["active_key"]
    if active < 0:
        active = 0
    update_ai_config({"keys": keys, "active_key": active})
    return {"ok": True, "index": len(keys) - 1}


@app.delete("/api/ai/keys/{index}")
async def delete_ai_key(index: int):
    cfg = get_ai_config()
    keys = cfg["keys"]
    keys.pop(index)
    active = cfg["active_key"]
    if active >= len(keys):
        active = len(keys) - 1
    elif active > index:
        active -= 1
    elif active == index:
        active = 0 if keys else -1
    update_ai_config({"keys": keys, "active_key": active})
    return {"ok": True}


@app.put("/api/ai/active")
async def set_active_ai_key(body: AIActiveKey):
    update_ai_config({"active_key": body.active_key})
    return {"ok": True}


@app.put("/api/ai/fallback")
async def set_ai_fallback(body: dict):
    update_ai_config({"fallback_keys": bool(body.get("fallback_keys", True))})
    return {"ok": True}


# ---------------------------------------------------------------------------
# Answer Queue routes
# ---------------------------------------------------------------------------


@app.get("/api/answer/queue")
async def get_answer_queue():
    from config import get_answer_queue as get_queue
    queue = get_queue()
    return {"queue": queue}


@app.post("/api/answer/queue")
async def add_to_answer_queue(body: dict):
    from config import add_answer_to_queue
    add_answer_to_queue(body)
    return {"ok": True}


@app.post("/api/answer/queue/batch")
async def batch_add_to_answer_queue(body: dict):
    from config import batch_add_to_queue
    answers = body.get("answers", [])
    added = batch_add_to_queue(answers)
    return {"ok": True, "added": added}


@app.delete("/api/answer/queue/{index}")
async def remove_from_answer_queue(index: int):
    from config import remove_answer_from_queue
    remove_answer_from_queue(index)
    return {"ok": True}


@app.put("/api/answer/queue/{index}")
async def update_answer_in_queue(index: int, body: dict):
    from config import update_answer_in_queue as update_fn
    update_fn(index, body)
    return {"ok": True}


@app.delete("/api/answer/queue")
async def clear_answer_queue():
    from config import clear_answer_queue
    clear_answer_queue()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Audio settings routes
# ---------------------------------------------------------------------------

@app.get("/api/audio/settings")
async def get_audio_settings_endpoint():
    return get_audio_config()


@app.put("/api/audio/settings")
async def update_audio_settings_endpoint(body: dict):
    update_audio_config({"enabled": bool(body.get("enabled", False))})
    return {"ok": True}


@app.post("/api/audio/upload")
async def upload_audio(file: UploadFile = File(...)):
    if not file.filename:
        return {"ok": False, "error": "No file"}
    ext = Path(file.filename).suffix
    if ext.lower() not in [".mp3", ".wav", ".ogg", ".m4a"]:
        return {"ok": False, "error": "Unsupported file type"}
    
    save_path = STORE_DIR / "custom_audio"
    with open(save_path, "wb") as f:
        f.write(await file.read())
    
    return {"ok": True}


@app.get("/api/audio/custom")
async def get_custom_audio():
    save_path = STORE_DIR / "custom_audio"
    if save_path.exists():
        from fastapi.responses import FileResponse
        return FileResponse(save_path, media_type="audio/mpeg")
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=404, content={"ok": False, "error": "No custom audio"})

@app.get("/api/audio/exists")
async def check_audio_exists():
    save_path = STORE_DIR / "custom_audio"
    if save_path.exists():
        return {"exists": True}
    return {"exists": False}


# ---------------------------------------------------------------------------
# Events WebSocket
# ---------------------------------------------------------------------------


@app.websocket("/ws/events")
async def ws_events(ws: WebSocket):
    await ws.accept()

    history = event_log.load_recent(50)
    if history:
        await ws.send_json({"type": "history", "events": history})

    client_queue: asyncio.Queue = asyncio.Queue(maxsize=200)
    _subscribers.add(client_queue)

    async def heartbeat():
        while True:
            await asyncio.sleep(30)
            await ws.send_json({"type": "heartbeat"})

    hb_task = asyncio.create_task(heartbeat())

    try:
        while True:
            event = await client_queue.get()
            await ws.send_json(event)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        hb_task.cancel()
        _subscribers.discard(client_queue)


# ---------------------------------------------------------------------------
# Static file serving (production)
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def experiment_health():
    m = get_monitor()
    validation_path = STORE_DIR / "vision-test.json"
    try:
        validation = json.loads(validation_path.read_text(encoding="utf-8")) if validation_path.exists() else None
    except (ValueError, OSError):
        validation = None
    if validation:
        validation["current_config"] = validation.get("fingerprint") == _ai_fingerprint()
    check_path = STORE_DIR / "submission-test.json"
    try:
        submission = json.loads(check_path.read_text(encoding="utf-8")) if check_path.exists() else None
    except (ValueError, OSError): submission = None
    return {"server": "ok", "version": VERSION, "domain": get_domain(), "login_verified": _auth_verified,
            "runtime": get_runtime(), "monitor": m.health() if m else None, "vision_validation": validation,
            "submission_validation": submission,
            "needs_setup": not get_config().get("setup_completed", False) and not (get_ai_config().get("keys") and get_runtime()["course_ids"])}


@app.post("/api/setup/complete")
async def setup_complete():
    cfg = get_config()
    cfg["setup_completed"] = True
    save_config(cfg)
    return {"ok": True}


def _ai_fingerprint():
    from config import get_active_ai_key_entry
    entry = get_active_ai_key_entry() or {}
    return hashlib.sha256(json.dumps(entry, sort_keys=True).encode()).hexdigest()[:16]


@app.get("/api/runtime")
async def runtime_settings():
    return get_runtime()


@app.put("/api/runtime")
async def runtime_update(body: dict):
    try:
        settings = save_runtime(body)
        # Stop disallowed connections immediately. New connections start at the next poll.
        from runtime import can_signin
        m = get_monitor()
        if m:
            with m._lock:
                for lesson in m._active_lessons.values():
                    if not can_signin(lesson.classroomid): lesson.stop_lesson()
        event_log.append({"type": "runtime", "status": settings["mode"], "message": "实验模式已更新"})
        return {"ok": True, "config": settings}
    except (ValueError, TypeError) as exc:
        return {"ok": False, "error": str(exc)}


@app.post("/api/courses/refresh")
async def refresh_courses():
    sessionid = get_config().get("sessionid")
    if not sessionid: return {"ok": False, "error": "请先扫码登录"}
    try:
        await asyncio.to_thread(_refresh_local_cache, sessionid)
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": f"登录或课程刷新失败：{type(exc).__name__}"}


@app.get("/api/events/recent")
async def recent_events():
    return event_log.load_recent(100)


@app.get("/api/experiment/sample.png")
async def experiment_sample_image():
    return FileResponse(resource_path("examples/circuit.png"))


@app.post("/api/experiment/vision-test")
async def experiment_vision_test(request: Request):
    from lesson import Lesson
    # Same image download, multimodal request and strict parser as classroom questions.
    problem = {"problemId": "local-circuit", "problemType": 1,
               "content": "Read the circuit image and compute current I. Choose the answer.",
               "options": [{"key": "A", "content": "1 A"}, {"key": "B", "content": "2 A"},
                           {"key": "C", "content": "3 A"}, {"key": "D", "content": "6 A"}],
               "_cover": str(request.base_url).rstrip("/") + "/api/experiment/sample.png"}
    def run():
        instance = Lesson({"lessonid": 0, "lessonname": "本地图片试题", "classroomid": 0}, "", {}, lambda *args: None)
        return instance._build_ai_answers(problem, time.monotonic() + get_runtime()["ai_timeout"])
    started = time.time()
    fingerprint = _ai_fingerprint()
    from config import get_active_ai_key_entry
    active = get_active_ai_key_entry() or {}
    try:
        answer = await asyncio.to_thread(run)
        result = {"ok": True, "answers": answer, "expected": ["B"], "correct": answer == ["B"], "submitted": False,
                  "tested_at": time.time(), "elapsed_seconds": round(time.time() - started, 2),
                  "active_model": active.get("model"), "fingerprint": fingerprint}
    except Exception as exc:
        result = {"ok": False, "error": f"识图接口或解析未通过：{type(exc).__name__}。请检查 API Key、地址和视觉模型名称。", "submitted": False,
                  "tested_at": time.time(), "elapsed_seconds": round(time.time() - started, 2), "fingerprint": fingerprint}
    (STORE_DIR / "vision-test.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    event_log.append({"type": "vision_test", "status": "passed" if result.get("correct") else "failed",
                      "message": "本地电路图模型接口验证，不产生课堂提交", **result})
    return result


_diagnostic_lock = threading.Lock()


@app.post("/api/experiment/submission-test")
async def submission_diagnostic():
    def run():
        import subprocess
        import tempfile
        if not _diagnostic_lock.acquire(blocking=False):
            return {"ok": False, "error": "自检正在运行，请稍后查看结果"}
        try:
            with tempfile.TemporaryDirectory(prefix="yuketang-diagnostic-") as folder:
                report = Path(folder) / "result.json"
                if getattr(sys, "frozen", False):
                    command = [sys.executable, "--self-test", "--report", str(report)]
                else:
                    command = [sys.executable, "-m", "submission_check", "--report", str(report)]
                options = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
                subprocess.run(command, cwd=Path(__file__).resolve().parent, timeout=45,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **options)
                if not report.exists(): return {"ok": False, "error": "自检进程未完成，请查看本机日志"}
                result = json.loads(report.read_text(encoding="utf-8"))
                (STORE_DIR / "submission-test.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                event_log.append({"type": "submission_test", "status": "passed" if result.get("ok") else "failed",
                                  "message": f"本机模拟提交自检：{result.get('passed')}/{result.get('total')}，真实课堂请求 0"})
                return result
        except Exception as exc:
            return {"ok": False, "error": "自检未完成：" + type(exc).__name__}
        finally:
            _diagnostic_lock.release()
    return await asyncio.to_thread(run)


@app.get("/api/lessons/{lesson_id}/problems/{problem_id}/image")
async def problem_image(lesson_id: str, problem_id: str):
    from ai_provider import AIProvider, image_mime
    from fastapi.responses import Response
    m = get_monitor()
    if not m: raise HTTPException(404, "课堂未连接")
    with m._lock:
        item = next((l for l in m._active_lessons.values() if str(l.lessonid) == lesson_id), None)
    if not item: raise HTTPException(404, "课堂已结束")
    with item._lock:
        problem = next((p.copy() for p in item.problems_ls if str(p["problemId"]) == problem_id), None)
    if not problem or not problem.get("_cover"): raise HTTPException(404, "题图暂不可用")
    try:
        provider = AIProvider().prepare({}, 10, item.headers)
        picture = await asyncio.to_thread(provider._fetch_image, problem["_cover"])
        return Response(picture, media_type=image_mime(picture), headers={"Cache-Control": "private, max-age=30"})
    except Exception:
        raise HTTPException(502, "题图获取失败")


def _get_static_dir() -> Path:
    """Locate the frontend static files in both normal and PyInstaller environments."""
    if getattr(sys, "frozen", False):
        # PyInstaller bundle — files are extracted to sys._MEIPASS
        return Path(sys._MEIPASS) / "static"
    static = Path(__file__).resolve().parent / "static"
    return static if static.is_dir() else Path(__file__).resolve().parent.parent / "frontend" / "dist"


_STATIC_DIR = _get_static_dir()

if _STATIC_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=_STATIC_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        file = (_STATIC_DIR / full_path).resolve()
        if file.is_relative_to(_STATIC_DIR.resolve()) and file.is_file():
            return FileResponse(file)
        return FileResponse(_STATIC_DIR / "index.html")
