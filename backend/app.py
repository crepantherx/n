from __future__ import annotations

import asyncio
import json
import os
import signal
import shlex
import threading
import time
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, File, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from pydantic import BaseModel, Field

from .auth import AuthStore, SESSION_COOKIE, normalize_email, safe_user_slug
from .config_store import ConfigStore, REPO_ROOT, normalize_hhmm, portable_config_path, resolve_config_path
from .log_hub import LogHub
from .scheduler import SimpleScheduler
from .task_runner import TaskRunner
from .runtime import cloud_features, is_cloud_runtime, unsupported_detail


APP_ROOT = Path(__file__).resolve().parent
WEB_DIR = APP_ROOT / "web"


class TaskStartRequest(BaseModel):
    target: int = Field(default=30, ge=1, le=2000)
    headless: bool = True


class StopAllRequest(BaseModel):
    # True means no task can be launched again by the in-app scheduler after the stop.
    disable_schedules: bool = True
    # True also removes cron entries created by this suite, so jobs do not restart after the dashboard quits.
    clear_system_cron: bool = True


class LoginRequest(BaseModel):
    email: str
    password: str


class GoogleLoginRequest(BaseModel):
    credential: str


class ConfigUpdateRequest(BaseModel):
    email: Optional[str] = None
    password: Optional[str] = None
    resume_path: Optional[str] = None
    job_titles: Optional[str] = None

    schedule_times: Optional[list[str]] = None
    bot_schedule_times: Optional[list[str]] = None
    linkedin_schedule_times: Optional[list[str]] = None
    lead_scraper_schedule_times: Optional[list[str]] = None
    intl_linkedin_schedule_times: Optional[list[str]] = None
    intl_indeed_schedule_times: Optional[list[str]] = None
    intl_reed_schedule_times: Optional[list[str]] = None
    intl_crawler_schedule_times: Optional[list[str]] = None

    linkedin_email: Optional[str] = None
    linkedin_password: Optional[str] = None
    linkedin_phone: Optional[str] = None
    
    reed_email: Optional[str] = None
    reed_password: Optional[str] = None

    schedule_enabled_naukri: Optional[bool] = None
    schedule_enabled_bot: Optional[bool] = None
    schedule_enabled_linkedin: Optional[bool] = None
    schedule_enabled_intl_indeed: Optional[bool] = None
    schedule_enabled_intl_reed: Optional[bool] = None
    schedule_enabled_intl_crawler: Optional[bool] = None
    schedule_enabled_lead_scraper: Optional[bool] = None
    schedule_enabled_intl_linkedin: Optional[bool] = None

    ui_headless_naukri: Optional[bool] = None
    ui_headless_bot: Optional[bool] = None
    ui_headless_linkedin: Optional[bool] = None
    ui_headless_intl_indeed: Optional[bool] = None
    ui_headless_intl_reed: Optional[bool] = None
    ui_headless_intl_crawler: Optional[bool] = None
    ui_headless_lead_scraper: Optional[bool] = None
    ui_headless_intl_linkedin: Optional[bool] = None

    intl_schedule_times: Optional[list[str]] = None
    ctc_inr: Optional[str] = None

    # Per-agent region assignments
    region_naukri: Optional[str] = None
    region_bot: Optional[str] = None
    region_linkedin: Optional[str] = None
    region_intl_indeed: Optional[str] = None
    region_intl_reed: Optional[str] = None
    region_intl_crawler: Optional[str] = None
    region_intl_linkedin: Optional[str] = None


def _safe_json_load(path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
    try:
        if not path.exists():
            return dict(default)
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else dict(default)
    except Exception:
        return dict(default)


def create_app() -> FastAPI:
    app = FastAPI(title="Naukri Automation Suite (Web)")

    max_upload_bytes = int(os.getenv("NAUKRI_MAX_UPLOAD_BYTES", "15728640"))  # 15MB
    features = cloud_features()
    cloud_mode = is_cloud_runtime()
    auth_store = AuthStore(REPO_ROOT)

    def _get_users() -> dict[str, dict[str, Any]]:
        return auth_store.load_users()

    def _get_current_user(request: Request) -> Optional[str]:
        return auth_store.verify_session(request.cookies.get(SESSION_COOKIE))

    def _set_session_cookie(resp: JSONResponse, request: Request, email: str) -> None:
        resp.set_cookie(
            key=SESSION_COOKIE,
            value=auth_store.create_session(email),
            httponly=True,
            max_age=86400 * 30,
            samesite="lax",
            secure=(request.url.scheme == "https"),
        )

    @app.middleware("http")
    async def _auth_middleware(request: Request, call_next):
        # Static files, login/logout, and health/system-info endpoints are public.
        path = request.url.path
        public_api = {"/api/login", "/api/login/google", "/api/logout", "/api/health", "/api/system_info", "/api/runtime", "/api/cloud/status", "/api/cloud/cron", "/api/cloud/run"}
        if not path.startswith("/api/") or path in public_api:
            return await call_next(request)

        user = _get_current_user(request)
        if not user:
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)

        request.state.user = user
        return await call_next(request)

    log_hub = LogHub()

    def _get_config_store(user: str) -> ConfigStore:
        return ConfigStore.for_user(safe_user_slug(user))
        
    def _files_dir(user: str) -> Path:
        base = _get_config_store(user).path.parent
        return base / "files"

    def _safe_resume_dest(user: str, upload_filename: Optional[str]) -> Path:
        allowed = {".pdf", ".doc", ".docx"}
        ext = Path(upload_filename or "").suffix.lower()
        if ext not in allowed:
            ext = ".pdf"
        dest_dir = _files_dir(user)
        dest_dir.mkdir(parents=True, exist_ok=True)
        return dest_dir / f"resume{ext}"

    def _resume_info(user: str) -> dict[str, Any]:
        cfg = _get_config_store(user).load()
        raw_path = str(cfg.get("resume_path") or "").strip()
        if not raw_path:
            return {"path": None, "exists": False, "filename": None, "size": None, "parsed": None}

        p = resolve_config_path(raw_path, config_path=_get_config_store(user).path)
        exists = bool(raw_path) and p.exists()
        try:
            size = int(p.stat().st_size) if exists else None
        except Exception:
            size = None
            
        parsed_data = None
        if exists:
            try:
                # Add import dynamically to avoid circular issues
                sys.path.insert(0, str(REPO_ROOT))
                from resume_parser import parse_resume
                parsed_data = parse_resume(str(p))
            except Exception as e:
                # Ideally log to user's log_hub, but we'll leave it out for this helper
                pass
                
        return {"path": str(p), "exists": exists, "filename": p.name, "size": size, "parsed": parsed_data}

    def _get_runners(user: str) -> dict[str, TaskRunner]:
        if not hasattr(app.state, "user_runners"):
            app.state.user_runners = {}
        if user not in app.state.user_runners:
            app.state.user_runners[user] = {}
            
        expected_tasks = {
            "naukri": "naukri_job_applier.py",
            "bot": "naukri_bot.py",
            "linkedin": "linkedin_job_applier.py",
            "intl_linkedin": "intl_linkedin_applier.py",
            "intl_indeed": "intl_indeed_applier.py",
            "intl_reed": "intl_reed_applier.py",
            "intl_crawler": "intl_career_page_crawler.py",
            "lead_scraper": "lead_scraper.py",
        }
        
        for task_name, script_name in expected_tasks.items():
            if task_name not in app.state.user_runners[user]:
                app.state.user_runners[user][task_name] = TaskRunner(f"{task_name}_{user}", REPO_ROOT / script_name)
                
        return app.state.user_runners[user]

    def start_task(user: str, task: str, *, target: int = 30, headless: bool = True) -> Dict[str, Any]:
        if cloud_mode and not features.get("subprocess_tasks"):
            raise ValueError(unsupported_detail("Starting automation tasks"))
        runners = _get_runners(user)
        if task not in runners:
            raise ValueError(f"Unknown task: {task}")

        if task == "naukri":
            args = ["--target", str(target)]
            if headless:
                args.append("--headless")
        elif task == "bot":
            args = []
            if headless:
                args.append("--headless")
        elif task == "linkedin":
            args = ["--target", str(target)]
            if headless:
                args.append("--headless")
        elif task in ["intl_linkedin", "intl_indeed", "intl_reed", "intl_crawler", "lead_scraper"]:
            args = ["--target", str(target)]
            if headless:
                args.append("--headless")
        else:
            args = []

        # Helpful for debugging: show the exact command being executed.
        cmd_preview = (
            f"{sys.executable} -u {runners[task].script_path} "
            + " ".join(args)
            + f"  (headless={headless})"
        )
        log_hub.status(f"{task}_{user}", f"Command: {cmd_preview}")

        def _on_log(line: str) -> None:
            # We prefix user to the task name in logs to partition logs correctly
            log_hub.log(f"{task}_{user}", line.rstrip("\n") + "\n")

        def _on_exit(code: int) -> None:
            log_hub.status(f"{task}_{user}", f"Exited with code {code}.")

        user_cfg_path = _get_config_store(user).path
        user_data_dir = user_cfg_path.parent
        user_data_dir.mkdir(parents=True, exist_ok=True)

        st = runners[task].start(
            args=args,
            cwd=REPO_ROOT,
            env={**os.environ, "NAUKRI_CONFIG_PATH": str(user_cfg_path), "NAUKRI_DATA_DIR": str(user_data_dir)},
            on_log_line=_on_log,
            on_exit=_on_exit,
        )
        log_hub.status(f"{task}_{user}", f"Started (pid {st.pid}).")
        return st.__dict__

    def stop_task(user: str, task: str) -> Dict[str, Any]:
        runners = _get_runners(user)
        if task not in runners:
            raise ValueError(f"Unknown task: {task}")
        st = runners[task].stop()
        log_hub.status(f"{task}_{user}", "Stop requested.")
        return st.__dict__

    def _headless_pref(user: str, task: str) -> bool:
        cfg = _get_config_store(user).load()
        return bool(cfg.get(f"ui_headless_{task}", True))

    scheduler = SimpleScheduler(
        get_users=lambda: list(_get_users().keys()),
        get_config_store=_get_config_store,
        log_hub=log_hub,
        trigger=lambda u, t: start_task(u, t, target=30, headless=_headless_pref(u, t)),
    )

    @app.on_event("startup")
    async def _startup():
        log_hub.set_loop(asyncio.get_running_loop())
        if cloud_mode:
            log_hub.status("scheduler", "Cloud runtime detected: in-process desktop scheduler is disabled.")
        else:
            scheduler.start()

    @app.on_event("shutdown")
    async def _shutdown():
        scheduler.stop()
        # A server stop must not leave Playwright/Python children behind.
        try:
            for runners in getattr(app.state, "user_runners", {}).values():
                for runner in runners.values():
                    runner.stop()
        except Exception:
            pass
        try:
            for agent in _agent_instances.values():
                agent.stop()
        except Exception:
            pass

    # ------------------------
    # Frontend routes & Login
    # ------------------------
    @app.post("/api/login")
    def api_login(req: LoginRequest, request: Request):
        try:
            result = auth_store.authenticate_password(req.email, req.password)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        if not result:
            raise HTTPException(status_code=401, detail="Invalid credentials")

        resp = JSONResponse({"status": "ok", "email": result.email, "created": result.created})
        _set_session_cookie(resp, request, result.email)
        return resp

    @app.post("/api/login/google")
    def api_login_google(req: GoogleLoginRequest, request: Request):
        from .config_store import _load_env_file
        import urllib.error
        import urllib.parse
        import urllib.request

        token = (req.credential or "").strip()
        if not token:
            raise HTTPException(status_code=400, detail="Missing Google credential")

        env_vals = _load_env_file()
        client_id = os.getenv("GOOGLE_CLIENT_ID") or env_vals.get("GOOGLE_CLIENT_ID", "")
        if not client_id:
            raise HTTPException(status_code=400, detail="Google Client ID not configured on server")

        def _fetch_json(url: str) -> dict[str, Any]:
            with urllib.request.urlopen(url, timeout=15) as response:
                payload = response.read().decode("utf-8")
            data = json.loads(payload)
            return data if isinstance(data, dict) else {}

        try:
            # Google One Tap sends an ID token. The OAuth fallback sends an access token.
            if token.count(".") == 2:
                url = "https://oauth2.googleapis.com/tokeninfo?" + urllib.parse.urlencode({"id_token": token})
                data = _fetch_json(url)
                aud = data.get("aud")
                if aud != client_id:
                    raise HTTPException(status_code=401, detail="Google token audience mismatch")
            else:
                req_obj = urllib.request.Request(
                    "https://www.googleapis.com/oauth2/v3/userinfo",
                    headers={"Authorization": f"Bearer {token}"},
                )
                with urllib.request.urlopen(req_obj, timeout=15) as response:
                    data = json.loads(response.read().decode("utf-8"))

            email = normalize_email(str(data.get("email", "")))
            if str(data.get("email_verified", "true")).lower() == "false":
                raise HTTPException(status_code=401, detail="Google email is not verified")

            result = auth_store.authenticate_google_email(email)
            if not result:
                raise HTTPException(status_code=401, detail="Google account is not allowed for this app")

            resp = JSONResponse({"status": "ok", "email": result.email, "created": result.created})
            _set_session_cookie(resp, request, result.email)
            return resp

        except HTTPException:
            raise
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace") if hasattr(e, "read") else str(e)
            raise HTTPException(status_code=401, detail=f"Invalid Google token: {detail}")
        except Exception as e:
            raise HTTPException(status_code=401, detail=f"Google login failed: {e}")

    @app.post("/api/logout")
    def api_logout():
        resp = JSONResponse({"status": "ok"})
        resp.delete_cookie(SESSION_COOKIE)
        return resp
    @app.get("/")
    def index():
        # Cache-bust static assets so UI always picks up the latest JS/CSS without hard-refresh.
        html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        try:
            js_v = int((WEB_DIR / "app.js").stat().st_mtime)
        except Exception:
            js_v = 0
        try:
            css_v = int((WEB_DIR / "styles.css").stat().st_mtime)
        except Exception:
            css_v = 0
        try:
            drive_v = int((WEB_DIR / "googleDrive.js").stat().st_mtime)
            sync_v = int((WEB_DIR / "attach_drive_sync.js").stat().st_mtime)
        except Exception:
            drive_v = 0
            sync_v = 0

        html = html.replace("/app.js", f"/app.js?v={js_v}")
        html = html.replace("/styles.css", f"/styles.css?v={css_v}")
        html = html.replace("/googleDrive.js?v=2", f"/googleDrive.js?v={drive_v}")
        html = html.replace("/attach_drive_sync.js?v=3", f"/attach_drive_sync.js?v={sync_v}")
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    @app.get("/app.js")
    def app_js():
        return FileResponse(WEB_DIR / "app.js", headers={"Cache-Control": "no-store"})

    @app.get("/styles.css")
    def styles_css():
        return FileResponse(WEB_DIR / "styles.css", headers={"Cache-Control": "no-store"})

    @app.get("/googleDrive.js")
    def google_drive_js():
        return FileResponse(WEB_DIR / "googleDrive.js", headers={"Cache-Control": "no-store"})

    @app.get("/attach_drive_sync.js")
    def attach_drive_sync_js():
        return FileResponse(WEB_DIR / "attach_drive_sync.js", headers={"Cache-Control": "no-store"})

    # ------------------------
    # API
    # ------------------------
    @app.get("/api/health")
    def health():
        return {"ok": True, "runtime": features.get("runtime", "local")}

    @app.get("/api/runtime")
    def runtime_info():
        return {"ok": True, **features}

    @app.get("/api/test")
    def get_test():
        return {"test": "hello"}

    @app.post("/api/debug/ping")
    def debug_ping(request: Request):
        log_hub.status(f"debug_{request.state.user}", "Ping from UI.")
        return {"ok": True}

    @app.get("/api/system_info")
    def get_system_info():
        # Load from .env if present, otherwise environment
        # _load_env_file() can be used or just use os.environ if dotenv loaded, 
        # but config_store._load_env_file does it best.
        from .config_store import _load_env_file
        env_vals = _load_env_file()
        client_id = os.getenv("GOOGLE_CLIENT_ID") or env_vals.get("GOOGLE_CLIENT_ID", "")
        client_secret = os.getenv("GOOGLE_CLIENT_SECRET") or env_vals.get("GOOGLE_CLIENT_SECRET", "")
        return {"google_client_id": client_id, "has_google_secret": bool(client_secret), "runtime": features}

    @app.get("/api/config")
    def get_config(request: Request):
        return _get_config_store(request.state.user).load()

    @app.put("/api/config")
    def update_config(req: ConfigUpdateRequest, request: Request):
        store = _get_config_store(request.state.user)
        cfg = store.load()

        # Support both Pydantic v1 (req.dict) and v2 (req.model_dump)
        if hasattr(req, "model_dump"):
            updates = req.model_dump(exclude_unset=True)
        else:
            updates = req.dict(exclude_unset=True)
        cfg.update(updates)
        store.save(cfg)
        saved = store.load()

        log_hub.status(f"config_{request.state.user}", "Configuration updated.")
        return saved

    @app.get("/api/resume")
    def api_resume_info(request: Request):
        return {"ok": True, "resume": _resume_info(request.state.user)}

    @app.post("/api/resume")
    async def api_resume_upload(request: Request, file: UploadFile = File(...)):
        if not file:
            raise HTTPException(status_code=400, detail="Missing file")

        dest = _safe_resume_dest(request.state.user, file.filename)
        dest.parent.mkdir(parents=True, exist_ok=True)

        # Remove any previous uploaded resume (regardless of extension).
        try:
            for existing in dest.parent.glob("resume.*"):
                try:
                    existing.unlink()
                except Exception:
                    pass
        except Exception:
            pass

        total = 0
        try:
            with dest.open("wb") as f:
                while True:
                    chunk = await file.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_upload_bytes:
                        raise HTTPException(status_code=413, detail="File too large")
                    f.write(chunk)
        finally:
            try:
                await file.close()
            except Exception:
                pass

        if total <= 0:
            try:
                dest.unlink()
            except Exception:
                pass
            raise HTTPException(status_code=400, detail="Empty file")

        store = _get_config_store(request.state.user)
        cfg = store.load()
        cfg["resume_path"] = portable_config_path(dest, config_path=store.path)
        store.save(cfg)
        log_hub.status(f"config_{request.state.user}", f"Resume uploaded: {dest.name} ({total} bytes).")
        return {"ok": True, "resume": _resume_info(request.state.user)}

    @app.delete("/api/resume")
    def api_resume_delete(request: Request):
        # Best-effort delete stored resume files.
        removed = 0
        d = _files_dir(request.state.user)
        try:
            for existing in d.glob("resume.*"):
                try:
                    existing.unlink()
                    removed += 1
                except Exception:
                    pass
        except Exception:
            pass

        store = _get_config_store(request.state.user)
        cfg = store.load()
        cfg["resume_path"] = ""
        store.save(cfg)
        log_hub.status(f"config_{request.state.user}", f"Resume cleared (removed {removed} file(s)).")
        return {"ok": True, "removed": removed, "resume": _resume_info(request.state.user)}
    @app.delete("/api/data")
    def api_clear_data(request: Request):
        user = request.state.user
        
        # Stop any running tasks before removing their data directories.
        try:
            for runner in _get_runners(user).values():
                runner.stop()
        except Exception:
            pass

        # 1. Clear config
        store = _get_config_store(user)
        store.path.unlink(missing_ok=True)
        
        # 2. Clear user data files
        user_data_dir = store.path.parent
        for f in ["stats.json", "naukri_bot_stats.json", "linkedin_stats.json", "intl_stats.json", "outreach_leads.json", "applications_log.json", "agent_memory.db"]:
            (user_data_dir / f).unlink(missing_ok=True)
        shutil.rmtree(user_data_dir / "logs", ignore_errors=True)
        shutil.rmtree(user_data_dir / "debug", ignore_errors=True)
            
        # 3. Clear legacy log files in repo root
        for log_file in REPO_ROOT.glob("*.log"):
            try:
                log_file.unlink()
            except Exception:
                pass
                
        # 4. Clear LogHub history
        log_hub.clear_user_history(user)
        
        # 5. Clear resume files
        d = _files_dir(user)
        try:
            for existing in d.glob("resume.*"):
                try:
                    existing.unlink()
                except Exception:
                    pass
        except Exception:
            pass

        return {"ok": True}

    @app.get("/api/tasks")
    def get_tasks(request: Request):
        runners = _get_runners(request.state.user)
        return {k: runners[k].status().__dict__ for k in runners.keys()}

    @app.post("/api/tasks/{task}/start")
    def api_start_task(task: str, req: TaskStartRequest, request: Request):
        try:
            return start_task(request.state.user, task, target=req.target, headless=req.headless)
        except RuntimeError as e:
            raise HTTPException(status_code=409, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.post("/api/tasks/{task}/stop")
    def api_stop_task(task: str, request: Request):
        try:
            return stop_task(request.state.user, task)
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.get("/api/logs/history")
    def api_logs_history(request: Request, limit: int = 500):
        # We can either filter logs history by the `user` suffix we added, or rewrite LogHub.
        # Since we prefixed task names with `_{user}` in log_hub.log and log_hub.status, 
        # we can filter the returned history items.
        hist = log_hub.history(limit=1000)
        user_suffix = f"_{request.state.user}"
        filtered = [item for item in hist if item["task"].endswith(user_suffix) or item["task"] == "scheduler"]
        return filtered[-limit:]

    def _applescript_string(value: Any) -> str:
        text = str(value or "")
        text = text.replace("\\", "\\\\").replace('"', '\\"').replace("\r", "").replace("\n", "\\n")
        return f'"{text}"'

    def _require_macos_mail() -> None:
        if sys.platform != "darwin" or not shutil.which("osascript"):
            raise HTTPException(status_code=400, detail="Apple Mail automation is available only on macOS with osascript installed")

    def _resolved_resume_path_for_user(user: str, raw_path: Any) -> Optional[Path]:
        if not raw_path:
            return None
        store = _get_config_store(user)
        path = resolve_config_path(raw_path, config_path=store.path)
        return path if path.exists() else None

    @app.get("/api/leads")
    def api_leads(request: Request):
        try:
            user_data_dir = _get_config_store(request.state.user).path.parent
            leads_file = user_data_dir / "outreach_leads.json"
            if not leads_file.exists():
                return []
            import json
            with open(leads_file, "r") as f:
                return json.load(f)
        except Exception as e:
            return []

    @app.post("/api/leads/{lead_id}/draft_email")
    async def api_draft_email(lead_id: str, request: Request):
        _require_macos_mail()
        try:
            body = await request.json()
            lead_name = str(body.get("name", "Recruiter") or "Recruiter")
            lead_company = str(body.get("company", "your company") or "your company")
            lead_email = str(body.get("email", "") or "")

            cfg = _get_config_store(request.state.user).load()
            sender_email = str(cfg.get("email", "") or "")
            resume_file = _resolved_resume_path_for_user(request.state.user, cfg.get("resume_path", ""))

            first_name = lead_name.split()[0] if lead_name else "there"
            email_body = (
                f"Hi {first_name},\n\n"
                f"I recently came across your post about the opening at {lead_company} and wanted to reach out. "
                "The role seems like a great fit for my background, and I would love the opportunity to contribute to the team.\n\n"
                "I have attached my resume for your reference. Looking forward to hearing from you.\n\n"
                "Best regards,"
            )

            lines = [
                'tell application "Mail"',
                f"    set newMessage to make new outgoing message with properties {{subject:{_applescript_string('Job Application')}, content:{_applescript_string(email_body + chr(10))}, visible:true}}",
                "    tell newMessage",
            ]
            if sender_email:
                lines.append(f"        set sender to {_applescript_string(sender_email)}")
            if lead_email:
                lines.append(f"        make new to recipient at end of to recipients with properties {{address:{_applescript_string(lead_email)}}}")
            if resume_file:
                lines.extend([
                    "        tell content",
                    f"            make new attachment with properties {{file name: POSIX file {_applescript_string(str(resume_file))}}} at after the last paragraph",
                    "        end tell",
                ])
            lines.extend(["    end tell", "    activate", "end tell", ""])
            script = "\n".join(lines)

            import tempfile
            with tempfile.NamedTemporaryFile(mode="w", suffix=".applescript", delete=False, encoding="utf-8") as f:
                f.write(script)
                temp_script_path = f.name

            subprocess.Popen(["osascript", temp_script_path])
            return {"success": True}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/api/leads/{lead_id}/reach")
    def api_reach_lead(lead_id: str, request: Request):
        try:
            user_data_dir = _get_config_store(request.state.user).path.parent
            leads_file = user_data_dir / "outreach_leads.json"
            if not leads_file.exists():
                raise HTTPException(status_code=404, detail="Leads file not found")
            import json
            with open(leads_file, "r") as f:
                leads = json.load(f)
            
            found = False
            for lead in leads:
                if str(lead.get("id")) == str(lead_id):
                    lead["status"] = "Reached"
                    found = True
                    break
            
            if not found:
                raise HTTPException(status_code=404, detail="Lead not found")
                
            with open(leads_file, "w") as f:
                json.dump(leads, f, indent=2)
                
            return {"ok": True}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.post("/api/leads/{lead_id}/toggle_status")
    def api_toggle_lead_status(lead_id: str, request: Request):
        try:
            user_data_dir = _get_config_store(request.state.user).path.parent
            leads_file = user_data_dir / "outreach_leads.json"
            if not leads_file.exists():
                raise HTTPException(status_code=404, detail="Leads file not found")
            import json
            with open(leads_file, "r") as f:
                leads = json.load(f)
            
            found = False
            for lead in leads:
                if str(lead.get("id")) == str(lead_id):
                    lead["status"] = "Reachout" if lead.get("status") == "Reached" else "Reached"
                    found = True
                    break
            
            if not found:
                raise HTTPException(status_code=404, detail="Lead not found")
                
            with open(leads_file, "w") as f:
                json.dump(leads, f, indent=2)
                
            return {"ok": True}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.delete("/api/leads/{lead_id}")
    def api_delete_lead(lead_id: str, request: Request):
        try:
            user_data_dir = _get_config_store(request.state.user).path.parent
            leads_file = user_data_dir / "outreach_leads.json"
            if not leads_file.exists():
                raise HTTPException(status_code=404, detail="Leads file not found")
            import json
            with open(leads_file, "r") as f:
                leads = json.load(f)
            
            initial_count = len(leads)
            leads = [lead for lead in leads if str(lead.get("id")) != str(lead_id)]
            
            if len(leads) == initial_count:
                raise HTTPException(status_code=404, detail="Lead not found")
                
            with open(leads_file, "w") as f:
                json.dump(leads, f, indent=2)
                
            return {"ok": True}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.post("/api/leads/mail_all_reachouts")
    async def api_mail_all_reachouts(request: Request):
        _require_macos_mail()
        try:
            user_data_dir = _get_config_store(request.state.user).path.parent
            leads_file = user_data_dir / "outreach_leads.json"
            if not leads_file.exists():
                return {"mailed": 0}

            import time
            with open(leads_file, "r", encoding="utf-8") as f:
                leads = json.load(f)

            cfg = _get_config_store(request.state.user).load()
            sender_email = str(cfg.get("email", "") or "")
            resume_file = _resolved_resume_path_for_user(request.state.user, cfg.get("resume_path", ""))

            mailed_count = 0
            for lead in leads:
                if lead.get("status") != "Reachout":
                    continue

                lead_name = str(lead.get("name", "Recruiter") or "Recruiter")
                lead_company = str(lead.get("company", "your company") or "your company")
                lead_email = str(lead.get("email", "") or "")
                first_name = lead_name.split()[0] if lead_name else "there"
                email_body = (
                    f"Hi {first_name},\n\n"
                    f"I recently came across your post about the opening at {lead_company} and wanted to reach out. "
                    "The role seems like a great fit for my background, and I would love the opportunity to contribute to the team.\n\n"
                    "I have attached my resume for your reference. Looking forward to hearing from you.\n\n"
                    "Best regards,"
                )

                lines = [
                    'tell application "Mail"',
                    f"    set newMessage to make new outgoing message with properties {{subject:{_applescript_string('Job Application')}, content:{_applescript_string(email_body + chr(10))}, visible:false}}",
                    "    tell newMessage",
                ]
                if sender_email:
                    lines.append(f"        set sender to {_applescript_string(sender_email)}")
                if lead_email:
                    lines.append(f"        make new to recipient at end of to recipients with properties {{address:{_applescript_string(lead_email)}}}")
                if resume_file:
                    lines.extend([
                        "        tell content",
                        f"            make new attachment with properties {{file name: POSIX file {_applescript_string(str(resume_file))}}} at after the last paragraph",
                        "        end tell",
                    ])
                lines.extend(["        delay 2", "        send", "    end tell", "end tell", ""])

                import tempfile
                with tempfile.NamedTemporaryFile(mode="w", suffix=".applescript", delete=False, encoding="utf-8") as f:
                    f.write("\n".join(lines))
                    temp_script_path = f.name

                subprocess.run(["osascript", temp_script_path], check=False)
                lead["status"] = "Reached"
                mailed_count += 1
                time.sleep(1)

            if mailed_count > 0:
                with open(leads_file, "w", encoding="utf-8") as f:
                    json.dump(leads, f, indent=2)

            return {"mailed": mailed_count}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/stats")
    def api_stats(request: Request):
        user_data_dir = _get_config_store(request.state.user).path.parent
        stats = _safe_json_load(user_data_dir / "stats.json", default={})
        bot_stats = _safe_json_load(user_data_dir / "naukri_bot_stats.json", default={})
        linkedin_stats = _safe_json_load(user_data_dir / "linkedin_stats.json", default={})
        intl_stats = _safe_json_load(user_data_dir / "intl_stats.json", default={})
        return {"naukri": stats, "bot": bot_stats, "linkedin": linkedin_stats, "intl": intl_stats}

    # ------------------------
    # System schedules (cron)
    # ------------------------
    CRON_MARKER = "naukri-automation-suite"

    def _find_crontab_bin() -> Optional[str]:
        crontab_bin = shutil.which("crontab")
        if crontab_bin:
            return crontab_bin
        # macOS GUI-launched apps sometimes have a minimal PATH.
        for candidate in ("/usr/bin/crontab", "/bin/crontab"):
            if Path(candidate).exists():
                return candidate
        return None

    def _get_cron_schedules() -> Dict[str, Any]:
        tasks: dict[str, set[str]] = {"naukri": set(), "bot": set(), "linkedin": set(), "intl_linkedin": set(), "intl_indeed": set(), "intl_reed": set(), "intl_crawler": set(), "lead_scraper": set()}
        unparsed: list[dict[str, str]] = []

        if cloud_mode:
            return {
                "available": False,
                "cloud": True,
                "tasks": {k: [] for k in tasks.keys()},
                "unparsed": [],
                "error": unsupported_detail("System cron"),
            }

        crontab_bin = _find_crontab_bin()

        if crontab_bin is None:
            return {
                "available": False,
                "tasks": {k: [] for k in tasks.keys()},
                "unparsed": [],
                "error": "crontab not found on this system",
            }

        def _parse_csv_ints(expr: str, *, lo: int, hi: int) -> Optional[list[int]]:
            vals: list[int] = []
            for part in expr.split(","):
                part = part.strip()
                if not part.isdigit():
                    return None
                vals.append(int(part))
            if any(v < lo or v > hi for v in vals):
                return None
            return vals

        try:
            res = subprocess.run(
                [crontab_bin, "-l"],
                capture_output=True,
                text=True,
                check=False,
            )
        except Exception as e:
            return {
                "available": False,
                "tasks": {k: [] for k in tasks.keys()},
                "unparsed": [],
                "error": f"Failed to read crontab: {e}",
            }

        # Exit code is non-zero when the user has no crontab; treat as empty.
        cron_text = res.stdout if res.returncode == 0 else ""
        for raw_line in cron_text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            task: Optional[str] = None
            if "intl_linkedin_applier.py" in line:
                task = "intl_linkedin"
            elif "linkedin_job_applier.py" in line:
                task = "linkedin"
            elif "intl_indeed_applier.py" in line:
                task = "intl_indeed"
            elif "intl_reed_applier.py" in line:
                task = "intl_reed"
            elif "intl_career_page_crawler.py" in line:
                task = "intl_crawler"
            elif "naukri_job_applier.py" in line or "job_applier.py" in line:
                task = "naukri"
            elif "naukri_bot.py" in line:
                task = "bot"
            elif "lead_scraper.py" in line:
                task = "lead_scraper"

            if not task:
                continue

            parts = line.split()
            if len(parts) < 6:
                unparsed.append({"task": task, "cron": "", "reason": "Invalid cron line"})
                continue

            minute, hour = parts[0], parts[1]
            mins = _parse_csv_ints(minute, lo=0, hi=59)
            hours = _parse_csv_ints(hour, lo=0, hi=23)
            if mins is None or hours is None:
                unparsed.append(
                    {"task": task, "cron": " ".join(parts[:5]), "reason": "Unsupported hour/minute format"}
                )
                continue

            for h in hours:
                for m in mins:
                    tasks[task].add(f"{h:02d}:{m:02d}")

        return {
            "available": True,
            "tasks": {k: sorted(v) for k, v in tasks.items()},
            "unparsed": unparsed,
            "error": None,
        }

    @app.get("/api/schedules/system")
    def api_system_schedules():
        cron_data = _get_cron_schedules()
        return {"ok": True, "cron": cron_data}

    def _parse_hhmm(value: str) -> Optional[tuple[int, int]]:
        normalized = normalize_hhmm(value)
        if not normalized:
            return None
        hour_s, minute_s = normalized.split(":", 1)
        return int(hour_s), int(minute_s)

    def _build_cron_line(task: str, *, user: str, hhmm: str, headless: bool) -> Optional[str]:
        parsed = _parse_hhmm(hhmm)
        if not parsed:
            return None
        hour, minute = parsed

        py = sys.executable
        cfg_store = _get_config_store(user)
        cfg_path = str(cfg_store.path)
        data_dir = str(cfg_store.path.parent)
        logs_dir = cfg_store.path.parent / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        repo = str(REPO_ROOT)

        if task == "naukri":
            script = str(REPO_ROOT / "naukri_job_applier.py")
            log_file = str(logs_dir / "job_applier.log")
            args = ["--target", "30"]
        elif task == "bot":
            script = str(REPO_ROOT / "naukri_bot.py")
            log_file = str(logs_dir / "naukri_bot.log")
            args = []
        elif task == "linkedin":
            script = str(REPO_ROOT / "linkedin_job_applier.py")
            log_file = str(logs_dir / "linkedin_job_applier.log")
            args = ["--target", "30"]
        elif task == "intl_linkedin":
            script = str(REPO_ROOT / "intl_linkedin_applier.py")
            log_file = str(logs_dir / "intl_linkedin.log")
            args = ["--target", "15"]
        elif task == "intl_indeed":
            script = str(REPO_ROOT / "intl_indeed_applier.py")
            log_file = str(logs_dir / "intl_indeed.log")
            args = ["--target", "15"]
        elif task == "intl_reed":
            script = str(REPO_ROOT / "intl_reed_applier.py")
            log_file = str(logs_dir / "intl_reed.log")
            args = ["--target", "15"]
        elif task == "intl_crawler":
            script = str(REPO_ROOT / "intl_career_page_crawler.py")
            log_file = str(logs_dir / "intl_career_crawler.log")
            args = ["--target", "10"]
        elif task == "lead_scraper":
            script = str(REPO_ROOT / "lead_scraper.py")
            log_file = str(logs_dir / "lead_scraper.log")
            args = ["--target", "30"]
        else:
            return None

        if headless:
            args.append("--headless")

        cmd = " ".join(shlex.quote(p) for p in [py, "-u", script, *args])
        q_repo = shlex.quote(repo)
        q_cfg = shlex.quote(cfg_path)
        q_data = shlex.quote(data_dir)
        q_log = shlex.quote(log_file)
        marker = f"# {CRON_MARKER} task={task} user={safe_user_slug(user)}"
        shell = f"cd {q_repo} && NAUKRI_CONFIG_PATH={q_cfg} NAUKRI_DATA_DIR={q_data} {cmd} >> {q_log} 2>&1 {marker}"
        return f"{minute} {hour} * * * {shell}"

    def _read_crontab(crontab_bin: str) -> tuple[list[str], Optional[str]]:
        try:
            res = subprocess.run(
                [crontab_bin, "-l"],
                capture_output=True,
                text=True,
                check=False,
            )
            # Exit code is non-zero when the user has no crontab; treat as empty.
            text = res.stdout if res.returncode == 0 else ""
            return text.splitlines(), None
        except Exception as e:
            return [], f"Failed to read crontab: {e}"

    def _write_crontab(crontab_bin: str, lines: list[str]) -> Optional[str]:
        new_text = "\n".join(lines).rstrip() + "\n"
        try:
            proc = subprocess.Popen([crontab_bin, "-"], stdin=subprocess.PIPE, text=True)
            proc.communicate(input=new_text)
            if proc.returncode != 0:
                return "Failed to update crontab"
            return None
        except Exception as e:
            return f"Failed to update crontab: {e}"

    def _cron_needles() -> tuple[str, ...]:
        return (
            "naukri_job_applier.py",
            "job_applier.py",
            "naukri_bot.py",
            "linkedin_job_applier.py",
            "intl_linkedin_applier.py",
            "intl_indeed_applier.py",
            "intl_reed_applier.py",
            "intl_career_page_crawler.py",
            "lead_scraper.py",
            CRON_MARKER,
        )

    def _clear_managed_cron_entries(*, user: Optional[str] = None, fail_if_unavailable: bool = False) -> Dict[str, Any]:
        """Remove cron entries managed by this suite.

        When user is provided, only marker-based lines for that user are removed.
        Legacy lines without a marker are still removed because old builds did not
        include user metadata and can otherwise keep launching jobs unexpectedly.
        """
        crontab_bin = _find_crontab_bin()
        if crontab_bin is None:
            if fail_if_unavailable:
                raise HTTPException(status_code=400, detail="crontab not found on this system")
            return {"available": False, "removed": 0, "error": "crontab not found on this system"}

        existing_lines, read_err = _read_crontab(crontab_bin)
        if read_err:
            if fail_if_unavailable:
                raise HTTPException(status_code=400, detail=read_err)
            return {"available": True, "removed": 0, "error": read_err}

        user_marker = f"user={safe_user_slug(user)}" if user else None
        kept: list[str] = []
        removed = 0
        for ln in existing_lines:
            managed = any(n in ln for n in _cron_needles())
            if not managed:
                kept.append(ln)
                continue

            if user_marker and CRON_MARKER in ln and user_marker not in ln:
                kept.append(ln)
                continue

            removed += 1

        write_err = _write_crontab(crontab_bin, kept)
        if write_err:
            if fail_if_unavailable:
                raise HTTPException(status_code=400, detail=write_err)
            return {"available": True, "removed": removed, "error": write_err}

        return {"available": True, "removed": removed, "error": None}

    @app.post("/api/schedules/system/sync")
    def api_system_schedules_sync(request: Request):
        if cloud_mode:
            raise HTTPException(status_code=400, detail=unsupported_detail("System cron sync"))
        crontab_bin = _find_crontab_bin()
        if crontab_bin is None:
            raise HTTPException(status_code=400, detail="crontab not found on this system")

        user = request.state.user
        cfg = _get_config_store(user).load()
        desired: list[str] = []
        invalid: list[dict[str, str]] = []

        def add_task(task: str, enabled_key: str, times_key: str, headless_key: str) -> None:
            enabled = bool(cfg.get(enabled_key, False))
            if not enabled:
                return
            times = cfg.get(times_key, []) or []
            if not isinstance(times, list):
                return
            for hhmm in times:
                if not isinstance(hhmm, str):
                    continue
                line = _build_cron_line(task, user=user, hhmm=hhmm, headless=bool(cfg.get(headless_key, True)))
                if line:
                    desired.append(line)
                else:
                    invalid.append({"task": task, "time": hhmm})

        add_task("naukri", "schedule_enabled_naukri", "schedule_times", "ui_headless_naukri")
        add_task("bot", "schedule_enabled_bot", "bot_schedule_times", "ui_headless_bot")
        add_task("linkedin", "schedule_enabled_linkedin", "linkedin_schedule_times", "ui_headless_linkedin")
        add_task("intl_linkedin", "schedule_enabled_intl_linkedin", "intl_linkedin_schedule_times", "ui_headless_intl_linkedin")
        add_task("intl_indeed", "schedule_enabled_intl_indeed", "intl_indeed_schedule_times", "ui_headless_intl_indeed")
        add_task("intl_reed", "schedule_enabled_intl_reed", "intl_reed_schedule_times", "ui_headless_intl_reed")
        add_task("intl_crawler", "schedule_enabled_intl_crawler", "intl_crawler_schedule_times", "ui_headless_intl_crawler")
        add_task("lead_scraper", "schedule_enabled_lead_scraper", "lead_scraper_schedule_times", "ui_headless_lead_scraper")

        existing_lines, read_err = _read_crontab(crontab_bin)
        if read_err:
            raise HTTPException(status_code=400, detail=read_err)

        needles = (
            "naukri_job_applier.py",
            "job_applier.py",
            "naukri_bot.py",
            "linkedin_job_applier.py",
            "intl_linkedin_applier.py",
            "intl_indeed_applier.py",
            "intl_reed_applier.py",
            "intl_career_page_crawler.py",
            "lead_scraper.py",
            CRON_MARKER,
        )
        kept: list[str] = []
        removed = 0
        for ln in existing_lines:
            if any(n in ln for n in needles):
                removed += 1
                continue
            kept.append(ln)

        new_lines = list(kept)
        if desired:
            if new_lines and new_lines[-1].strip():
                new_lines.append("")
            new_lines.append(f"# {CRON_MARKER} (managed by Naukri Automation Suite)")
            new_lines.extend(desired)
            new_lines.append("")

        write_err = _write_crontab(crontab_bin, new_lines)
        if write_err:
            raise HTTPException(status_code=400, detail=write_err)

        log_hub.status("scheduler", f"Synced system cron schedules (installed {len(desired)}, removed {removed}).")
        return {"ok": True, "installed": len(desired), "removed": removed, "invalid": invalid, "cron": _get_cron_schedules()}

    @app.delete("/api/schedules/system")
    def api_system_schedules_clear():
        if cloud_mode:
            return {"ok": True, "removed": 0, "cron": _get_cron_schedules()}
        result = _clear_managed_cron_entries(fail_if_unavailable=True)
        removed = int(result.get("removed", 0))
        log_hub.status("scheduler", f"Cleared system cron schedules (removed {removed}).")
        return {"ok": True, "removed": removed, "cron": _get_cron_schedules()}

    @app.get("/api/applications")
    def api_applications(request: Request):
        try:
            import json
            user = getattr(request.state, "user", None)
            if not user:
                return {"ok": False, "error": "Unauthorized", "applications": []}
                
            user_data_dir = _get_config_store(user).path.parent
            log_file = user_data_dir / "applications_log.json"
            
            if not log_file.exists():
                return {"ok": True, "applications": []}
            with open(log_file, "r") as f:
                logs = json.load(f)
            # Sort newest first
            logs.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
            return {"ok": True, "applications": logs}
        except Exception as e:
            return {"ok": False, "error": str(e), "applications": []}

    # ------------------------
    # AI Agent endpoints
    # ------------------------
    _agent_instances: dict[str, Any] = {}
    _agent_threads: dict[str, Any] = {}

    def _agent_memory(user: str):
        sys.path.insert(0, str(REPO_ROOT))
        from ai_agent.agent_memory import AgentMemory
        data_dir = _get_config_store(user).path.parent
        return AgentMemory(data_dir / "agent_memory.db")

    def _agent_config(user: str) -> dict[str, Any]:
        sys.path.insert(0, str(REPO_ROOT))
        from ai_agent.agent import DEFAULT_AGENT_CONFIG
        store = _get_config_store(user)
        main_config = store.load()
        config = dict(DEFAULT_AGENT_CONFIG)
        for key in DEFAULT_AGENT_CONFIG:
            if key in main_config:
                config[key] = main_config[key]
        for key in (
            "email", "password", "resume_path", "job_titles", "linkedin_email",
            "linkedin_password", "linkedin_phone", "reed_email", "reed_password", "ctc_inr",
            "region_naukri", "region_linkedin", "region_intl_crawler", "region_intl_linkedin",
            "region_intl_indeed", "region_intl_reed", "intl_full_name", "intl_location",
            "intl_notice_period", "intl_visa_status", "intl_expected_salary_gbp",
            "intl_expected_salary_usd", "intl_expected_salary_eur",
        ):
            config[key] = main_config.get(key, "")
        if config.get("resume_path"):
            config["resume_path"] = str(resolve_config_path(config["resume_path"], config_path=store.path))
        return config

    def _get_agent(user: str):
        if user not in _agent_instances:
            try:
                sys.path.insert(0, str(REPO_ROOT))
                from ai_agent.agent import JobApplicationAgent
                _agent_instances[user] = JobApplicationAgent(
                    config=_agent_config(user),
                    memory=_agent_memory(user),
                    on_log=lambda msg, u=user: log_hub.log(f"agent_{u}", msg + "\n"),
                )
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Agent init failed: {e}")
        return _agent_instances[user]

    @app.get("/agent")
    def agent_page():
        html_path = WEB_DIR / "agent.html"
        if not html_path.exists():
            raise HTTPException(status_code=404, detail="Agent page not found")
        html = html_path.read_text(encoding="utf-8")
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    @app.get("/agent.js")
    def agent_js():
        return FileResponse(WEB_DIR / "agent.js", headers={"Cache-Control": "no-store"})

    @app.get("/agent.css")
    def agent_css():
        return FileResponse(WEB_DIR / "agent.css", headers={"Cache-Control": "no-store"})

    @app.get("/api/agent/status")
    def api_agent_status(request: Request):
        if cloud_mode:
            return {
                "ok": True,
                "running": False,
                "status": "cloud-disabled",
                "message": unsupported_detail("AI Agent execution"),
            }
        try:
            agent = _get_agent(request.state.user)
            return {"ok": True, **agent.status}
        except Exception as e:
            return {"ok": False, "error": str(e), "running": False, "status": "error"}

    @app.post("/api/agent/start")
    async def api_agent_start(request: Request):
        if cloud_mode:
            raise HTTPException(status_code=400, detail=unsupported_detail("AI Agent execution"))
        nonlocal _agent_threads
        try:
            body = await request.json()
        except Exception:
            body = {}

        agent = _get_agent(request.state.user)
        if agent._running:
            raise HTTPException(status_code=409, detail="Agent is already running")

        # Refresh config and memory at start so settings changed in the main
        # dashboard are picked up without restarting the server.
        agent.config = _agent_config(request.state.user)
        agent.memory = _agent_memory(request.state.user)

        platform = body.get("platform", "naukri")
        target = int(body.get("target", 20))
        headless = body.get("headless", True)
        dry_run = body.get("dry_run", False)
        mode = body.get("mode", "auto")

        if mode == "review":
            agent.config["agent_mode"] = "review"

        import threading
        _agent_threads[request.state.user] = threading.Thread(
            target=agent.run_cycle,
            kwargs={"platform": platform, "target": target,
                    "headless": headless, "dry_run": dry_run},
            daemon=True,
        )
        _agent_threads[request.state.user].start()
        log_hub.status(f"agent_{request.state.user}", f"Agent started: platform={platform}, target={target}")
        return {"ok": True, "platform": platform, "target": target}

    @app.post("/api/agent/stop")
    def api_agent_stop(request: Request):
        if cloud_mode:
            return {"ok": True, "message": unsupported_detail("AI Agent execution")}
        agent = _get_agent(request.state.user)
        agent.stop()
        log_hub.status(f"agent_{request.state.user}", "Agent stop requested")
        return {"ok": True}

    def _disable_saved_schedules(user: str) -> Dict[str, Any]:
        store = _get_config_store(user)
        cfg = store.load()
        enabled_keys = (
            "schedule_enabled_naukri",
            "schedule_enabled_bot",
            "schedule_enabled_linkedin",
            "schedule_enabled_intl_linkedin",
            "schedule_enabled_intl_indeed",
            "schedule_enabled_intl_reed",
            "schedule_enabled_intl_crawler",
            "schedule_enabled_lead_scraper",
        )
        time_keys = (
            "schedule_times",
            "bot_schedule_times",
            "linkedin_schedule_times",
            "intl_schedule_times",
            "intl_linkedin_schedule_times",
            "intl_indeed_schedule_times",
            "intl_reed_schedule_times",
            "intl_crawler_schedule_times",
            "lead_scraper_schedule_times",
        )
        changed: list[str] = []
        for key in enabled_keys:
            if cfg.get(key):
                changed.append(key)
            cfg[key] = False
        for key in time_keys:
            if cfg.get(key):
                changed.append(key)
            cfg[key] = []
        cfg["schedules_paused_at"] = int(time.time())
        store.save(cfg)
        return {"disabled": len(changed), "keys": changed}

    def _stop_everything_for_user(
        user: str,
        *,
        disable_schedules: bool = True,
        clear_system_cron: bool = True,
    ) -> Dict[str, Any]:
        task_results: Dict[str, Any] = {}
        runners = _get_runners(user)
        for task, runner in runners.items():
            try:
                task_results[task] = runner.stop().__dict__
            except Exception as e:
                task_results[task] = {"running": False, "error": str(e)}

        agent_result: Dict[str, Any] = {"present": False, "stopped": False}
        try:
            agent = _agent_instances.get(user)
            if agent is not None:
                agent.stop()
                agent_result = {"present": True, "stopped": True, "status": agent.status}
        except Exception as e:
            agent_result = {"present": True, "stopped": False, "error": str(e)}

        schedule_result: Dict[str, Any] = {"disabled": 0, "keys": []}
        if disable_schedules:
            schedule_result = _disable_saved_schedules(user)

        cron_result: Dict[str, Any] = {"available": False, "removed": 0, "error": None}
        if clear_system_cron:
            # Panic stop removes every suite-managed cron entry, including legacy
            # unmarked entries that could otherwise relaunch jobs unexpectedly.
            cron_result = _clear_managed_cron_entries()

        log_hub.status(
            "scheduler",
            f"Emergency stop requested by {user}: stopped tasks, "
            f"disabled {schedule_result.get('disabled', 0)} schedule flags, "
            f"removed {cron_result.get('removed', 0)} cron entries.",
        )
        return {
            "ok": True,
            "tasks": task_results,
            "agent": agent_result,
            "schedules": schedule_result,
            "cron": cron_result,
        }

    def _summarize_stop_result(result: Dict[str, Any]) -> Dict[str, Any]:
        tasks = result.get("tasks", {}) if isinstance(result, dict) else {}
        stopped = 0
        for value in tasks.values():
            if isinstance(value, dict) and not value.get("running", False):
                stopped += 1
        schedules = result.get("schedules", {}) if isinstance(result, dict) else {}
        cron = result.get("cron", {}) if isinstance(result, dict) else {}
        result["stopped_tasks"] = stopped
        result["disabled_schedule_flags"] = int(schedules.get("disabled", 0) or 0)
        result["disabled_schedule_configs"] = 1 if int(schedules.get("disabled", 0) or 0) else 0
        result["removed_cron_entries"] = int(cron.get("removed", 0) or 0)
        return result

    @app.post("/api/control/stop_all")
    def api_control_stop_all(req: StopAllRequest, request: Request):
        result = _stop_everything_for_user(
            request.state.user,
            disable_schedules=req.disable_schedules,
            clear_system_cron=req.clear_system_cron,
        )
        return _summarize_stop_result(result)

    @app.post("/api/system/stop_all")
    def api_system_stop_all(req: StopAllRequest, request: Request):
        result = _stop_everything_for_user(
            request.state.user,
            disable_schedules=req.disable_schedules,
            clear_system_cron=req.clear_system_cron,
        )
        return _summarize_stop_result(result)

    @app.post("/api/control/shutdown")
    def api_control_shutdown(req: StopAllRequest, request: Request):
        if cloud_mode:
            result = _stop_everything_for_user(
                request.state.user,
                disable_schedules=req.disable_schedules,
                clear_system_cron=False,
            )
            result = _summarize_stop_result(result)
            result["dashboard"] = "serverless-noop"
            result["message"] = unsupported_detail("Dashboard shutdown")
            return result
        result = _stop_everything_for_user(
            request.state.user,
            disable_schedules=req.disable_schedules,
            clear_system_cron=req.clear_system_cron,
        )
        result = _summarize_stop_result(result)
        result["dashboard"] = "stopping"
        result["port"] = int(os.getenv("PORT") or os.getenv("NAUKRI_WEB_PORT") or "8787")

        def _terminate_server() -> None:
            time.sleep(0.75)
            try:
                os.kill(os.getpid(), signal.SIGTERM)
            except Exception:
                os._exit(0)

        threading.Thread(target=_terminate_server, name="dashboard-shutdown", daemon=True).start()
        return result

    @app.get("/api/control/status")
    def api_control_status(request: Request):
        tasks = {k: v.status().__dict__ for k, v in _get_runners(request.state.user).items()}
        running = [k for k, v in tasks.items() if v.get("running")]
        return {
            "ok": True,
            "pid": os.getpid(),
            "port": int(os.getenv("PORT") or os.getenv("NAUKRI_WEB_PORT") or "8787"),
            "running_tasks": running,
            "cron": _get_cron_schedules(),
        }

    def _cron_secret_value() -> str:
        return os.getenv("CRON_SECRET") or os.getenv("NAUKRI_CRON_SECRET") or ""

    def _cron_authorized(request: Request) -> bool:
        secret = _cron_secret_value()
        if not secret:
            # No-secret access is allowed only for the default no-op health cron.
            return True
        supplied = request.headers.get("authorization", "")
        return supplied == f"Bearer {secret}" or request.query_params.get("secret") == secret

    def _require_cloud_run_authorized(request: Request) -> None:
        if not _cron_secret_value():
            raise HTTPException(status_code=400, detail="Set CRON_SECRET before enabling public cloud run endpoints")
        if not _cron_authorized(request):
            raise HTTPException(status_code=401, detail="Invalid cron secret")

    def _cloud_default_user() -> Optional[str]:
        raw = os.getenv("NAUKRI_ADMIN_EMAIL") or os.getenv("ADMIN_EMAIL") or ""
        if raw:
            try:
                return normalize_email(raw)
            except Exception:
                return None
        users = auth_store.list_users()
        return users[0] if users else None

    @app.get("/api/cloud/status")
    def api_cloud_status():
        return {
            "ok": True,
            **features,
            "default_user_configured": bool(_cloud_default_user()),
            "cron_secret_configured": bool(os.getenv("CRON_SECRET") or os.getenv("NAUKRI_CRON_SECRET")),
        }

    @app.get("/api/cloud/cron")
    def api_cloud_cron(request: Request):
        if not _cron_authorized(request):
            raise HTTPException(status_code=401, detail="Invalid cron secret")
        # Vercel Hobby cron can reliably invoke this endpoint once per day, but
        # the free serverless runtime is not a durable desktop worker. Keep the
        # default behavior as a no-op health signal instead of silently starting
        # browser automation that Vercel may terminate.
        if not cloud_mode:
            return {"ok": True, "cloud": False, "ran": False, "message": "Local installs use the in-app scheduler and/or system cron."}
        if not features.get("vercel_runs_enabled"):
            return {
                "ok": True,
                "cloud": True,
                "ran": False,
                "message": "Cron reached the Vercel deployment. Set NAUKRI_ENABLE_VERCEL_RUNS=1 only if you understand Vercel duration/browser limits.",
            }
        _require_cloud_run_authorized(request)
        return _run_cloud_task(request, task=request.query_params.get("task") or os.getenv("NAUKRI_VERCEL_TASK", "naukri"))

    @app.post("/api/cloud/run")
    @app.get("/api/cloud/run")
    def api_cloud_run(request: Request, task: str = "naukri"):
        _require_cloud_run_authorized(request)
        if not cloud_mode:
            raise HTTPException(status_code=400, detail="Cloud run endpoint is intended for Vercel/serverless deployments")
        if not features.get("vercel_runs_enabled"):
            raise HTTPException(status_code=400, detail="Set NAUKRI_ENABLE_VERCEL_RUNS=1 to allow synchronous cloud runs")
        return _run_cloud_task(request, task=task)

    def _run_cloud_task(request: Request, *, task: str) -> Dict[str, Any]:
        task = (task or "naukri").strip().lower()
        script_map = {
            "naukri": "naukri_job_applier.py",
            "bot": "naukri_bot.py",
            "linkedin": "linkedin_job_applier.py",
            "intl_linkedin": "intl_linkedin_applier.py",
            "intl_indeed": "intl_indeed_applier.py",
            "intl_reed": "intl_reed_applier.py",
            "intl_crawler": "intl_career_page_crawler.py",
            "lead_scraper": "lead_scraper.py",
        }
        if task not in script_map:
            raise HTTPException(status_code=400, detail=f"Unknown task: {task}")
        user = _cloud_default_user()
        if not user:
            raise HTTPException(status_code=400, detail="NAUKRI_ADMIN_EMAIL is required for cloud runs")

        cfg_store = _get_config_store(user)
        user_data_dir = cfg_store.path.parent
        user_data_dir.mkdir(parents=True, exist_ok=True)
        timeout_s = max(5, min(int(os.getenv("NAUKRI_VERCEL_RUN_TIMEOUT", "50")), 55))
        target = str(request.query_params.get("target") or os.getenv("NAUKRI_VERCEL_TARGET", "5"))
        args = [] if task == "bot" else ["--target", target]
        args.append("--headless")
        cmd = [sys.executable, "-u", str(REPO_ROOT / script_map[task]), *args]
        env = os.environ.copy()
        env.update({"NAUKRI_CONFIG_PATH": str(cfg_store.path), "NAUKRI_DATA_DIR": str(user_data_dir), "PYTHONUNBUFFERED": "1"})
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(REPO_ROOT),
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
            )
            output = (proc.stdout or "")[-12000:]
            return {"ok": proc.returncode == 0, "cloud": True, "task": task, "exit_code": proc.returncode, "output_tail": output}
        except subprocess.TimeoutExpired as e:
            output = ((e.stdout or "") + (e.stderr or ""))[-12000:]
            return {"ok": False, "cloud": True, "task": task, "timeout": timeout_s, "output_tail": output, "detail": "Cloud run timed out before completion"}

    @app.get("/api/agent/stats")
    def api_agent_stats(request: Request):
        try:
            memory = _agent_memory(request.state.user)
            return {"ok": True, **memory.get_stats()}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @app.get("/api/agent/decisions")
    def api_agent_decisions(request: Request, limit: int = 50, platform: str = ""):
        try:
            memory = _agent_memory(request.state.user)
            return {"ok": True, "decisions": memory.get_decisions(limit=limit, platform=platform)}
        except Exception as e:
            return {"ok": False, "error": str(e), "decisions": []}

    @app.get("/api/agent/queue")
    def api_agent_queue(request: Request):
        try:
            memory = _agent_memory(request.state.user)
            return {"ok": True, "queue": memory.get_review_queue()}
        except Exception as e:
            return {"ok": False, "error": str(e), "queue": []}

    @app.post("/api/agent/queue/{item_id}/approve")
    def api_agent_approve(item_id: int, request: Request):
        try:
            memory = _agent_memory(request.state.user)
            memory.approve_review(item_id)
            return {"ok": True}
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.post("/api/agent/queue/{item_id}/reject")
    def api_agent_reject(item_id: int, request: Request):
        try:
            memory = _agent_memory(request.state.user)
            memory.reject_review(item_id)
            return {"ok": True}
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.get("/api/agent/applied")
    def api_agent_applied(request: Request, limit: int = 50):
        try:
            memory = _agent_memory(request.state.user)
            return {"ok": True, "jobs": memory.get_applied_jobs(limit=limit)}
        except Exception as e:
            return {"ok": False, "error": str(e), "jobs": []}

    # ------------------------
    # WebSocket for live logs
    # ------------------------
    @app.websocket("/ws/logs")
    async def ws_logs(ws: WebSocket):
        user = auth_store.verify_session(ws.cookies.get(SESSION_COOKIE))
        if not user:
            await ws.accept()
            await ws.close(code=1008)
            return

        await ws.accept()
        q = log_hub.subscribe()
        try:
            # Send a little history to hydrate UI (batched to avoid flooding).
            hist = log_hub.history(limit=1000)
            user_suffix = f"_{user}"
            filtered = [item for item in hist if item["task"].endswith(user_suffix) or item["task"] == "scheduler"]
            await ws.send_json(filtered[-200:])

            while True:
                first = await q.get()
                batch = [first]
                # Drain any burst so we send fewer websocket frames.
                for _ in range(199):
                    try:
                        batch.append(q.get_nowait())
                    except asyncio.QueueEmpty:
                        break
                
                # Filter batch
                batch = [item for item in batch if item["task"].endswith(user_suffix) or item["task"] == "scheduler"]
                if batch:
                    await ws.send_json(batch)
        except WebSocketDisconnect:
            pass
        finally:
            log_hub.unsubscribe(q)

    return app


app = create_app()
