#!/usr/bin/env python3
"""
SFTP web client.
"""

from __future__ import annotations

import base64
import os
import posixpath
import shutil
import sqlite3
import stat
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import paramiko
from cryptography.fernet import Fernet
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field


app = FastAPI(title="SFTP Client", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(BASE_DIR, "data"))
DB_PATH = os.path.join(DATA_DIR, "bookmarks.db")
ENCRYPTION_KEY_ENV = "SFTP_ENCRYPTION_KEY"
SESSION_TTL_SECONDS = int(os.environ.get("SESSION_TTL_SECONDS", "1800"))

os.makedirs(DATA_DIR, exist_ok=True)


def get_encryption_key() -> bytes:
    key_env = os.environ.get(ENCRYPTION_KEY_ENV)
    if key_env:
        try:
            decoded = base64.urlsafe_b64decode(key_env.encode())
            if len(decoded) != 32:
                raise ValueError("decoded key length is not 32 bytes")
            return key_env.encode()
        except Exception as exc:
            print(f"Invalid {ENCRYPTION_KEY_ENV}: {exc}")

    key_file = os.path.join(DATA_DIR, ".key")
    if os.path.exists(key_file):
        with open(key_file, "rb") as handle:
            return handle.read()

    key = Fernet.generate_key()
    with open(key_file, "wb") as handle:
        handle.write(key)
    print(f"Generated encryption key at {key_file}")
    return key


cipher_suite = Fernet(get_encryption_key())


def encrypt_password(password: str) -> str:
    return cipher_suite.encrypt(password.encode()).decode() if password else ""


def decrypt_password(encrypted: str) -> str:
    if not encrypted:
        return ""
    try:
        return cipher_suite.decrypt(encrypted.encode()).decode()
    except Exception:
        return ""


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    with get_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS bookmarks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                host TEXT NOT NULL,
                port INTEGER NOT NULL DEFAULT 22,
                username TEXT NOT NULL,
                password_encrypted TEXT DEFAULT '',
                path TEXT DEFAULT '/',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_bookmarks_host_user ON bookmarks(host, username)"
        )
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(bookmarks)").fetchall()
        }
        if "key_data_encrypted" not in columns:
            conn.execute(
                "ALTER TABLE bookmarks ADD COLUMN key_data_encrypted TEXT DEFAULT ''"
            )
        conn.commit()


init_db()


def normalize_path(path: str | None) -> str:
    if not path:
        return "/"
    normalized = posixpath.normpath(path)
    return normalized if normalized.startswith("/") else f"/{normalized}"


def join_remote_path(base: str, name: str) -> str:
    base = normalize_path(base)
    if base == "/":
        return f"/{name}"
    return posixpath.join(base, name)


def parse_private_key(key_data: str) -> Optional[paramiko.PKey]:
    if not key_data:
        return None

    with tempfile.NamedTemporaryFile("w", delete=False) as handle:
        handle.write(key_data)
        key_path = handle.name

    try:
        for key_class in (
            paramiko.RSAKey,
            paramiko.Ed25519Key,
            paramiko.ECDSAKey,
            paramiko.DSSKey,
        ):
            try:
                return key_class.from_private_key_file(key_path)
            except Exception:
                continue
    finally:
        try:
            os.remove(key_path)
        except OSError:
            pass

    raise ValueError("Unsupported or invalid SSH private key")


@dataclass
class Session:
    session_id: str
    transport: paramiko.Transport
    sftp: paramiko.SFTPClient
    host: str
    username: str
    default_path: str
    created_at: float
    last_activity: float

    def touch(self) -> None:
        self.last_activity = time.time()

    def close(self) -> None:
        try:
            self.sftp.close()
        except Exception:
            pass
        try:
            self.transport.close()
        except Exception:
            pass


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    def create(
        self,
        host: str,
        port: int,
        username: str,
        password: str = "",
        key_data: Optional[str] = None,
        default_path: str = "/",
    ) -> Session:
        transport = paramiko.Transport((host, port))
        transport.banner_timeout = 20
        transport.auth_timeout = 20

        try:
            private_key = parse_private_key(key_data) if key_data else None
            if private_key:
                transport.connect(username=username, pkey=private_key)
            elif password:
                transport.connect(username=username, password=password)
            else:
                transport.connect(username=username)

            sftp = paramiko.SFTPClient.from_transport(transport)
            session = Session(
                session_id=str(uuid.uuid4()),
                transport=transport,
                sftp=sftp,
                host=host,
                username=username,
                default_path=normalize_path(default_path),
                created_at=time.time(),
                last_activity=time.time(),
            )
            with self._lock:
                self._sessions[session.session_id] = session
            return session
        except Exception:
            try:
                transport.close()
            except Exception:
                pass
            raise

    def get(self, session_id: str) -> Optional[Session]:
        self.cleanup_expired()
        with self._lock:
            session = self._sessions.get(session_id)
            if session:
                session.touch()
            return session

    def remove(self, session_id: str) -> bool:
        with self._lock:
            session = self._sessions.pop(session_id, None)
        if session:
            session.close()
            return True
        return False

    def cleanup_expired(self) -> None:
        now = time.time()
        expired: list[Session] = []
        with self._lock:
            for session_id, session in list(self._sessions.items()):
                if now - session.last_activity > SESSION_TTL_SECONDS:
                    expired.append(self._sessions.pop(session_id))
        for session in expired:
            session.close()

    def count(self) -> int:
        self.cleanup_expired()
        with self._lock:
            return len(self._sessions)


sessions = SessionStore()


class BookmarkRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=22, ge=1, le=65535)
    username: str = Field(min_length=1, max_length=120)
    password: str = ""
    key_data: Optional[str] = None
    path: str = "/"


class ConnectRequest(BaseModel):
    host: str
    port: int = 22
    username: str
    password: str = ""
    path: str = "/"
    key_data: Optional[str] = None


class ListRequest(BaseModel):
    session_id: str
    path: str = "/"


class DownloadRequest(BaseModel):
    session_id: str
    remote_path: str


class DisconnectRequest(BaseModel):
    session_id: str


class DeleteRequest(BaseModel):
    session_id: str
    path: str


class RenameRequest(BaseModel):
    session_id: str
    old_path: str
    new_path: str


class MkdirRequest(BaseModel):
    session_id: str
    path: str


class CreateFileRequest(BaseModel):
    session_id: str
    remote_path: str
    content: str = ""


class PreviewRequest(BaseModel):
    session_id: str
    path: str
    max_bytes: int = Field(default=65536, ge=1, le=262144)


class TransferRequest(BaseModel):
    source_session_id: str
    target_session_id: str
    file_name: str
    source_path: str
    target_path: str
    conflict_mode: str = "overwrite"


def error_response(message: str, status_code: int = 400) -> JSONResponse:
    return JSONResponse({"success": False, "error": message}, status_code=status_code)


def get_session_or_404(session_id: str) -> Session | JSONResponse:
    session = sessions.get(session_id)
    if not session:
        return error_response("Session expired or not connected", 404)
    return session


def list_entries(sftp: paramiko.SFTPClient, path: str) -> list[dict]:
    entries = []
    for entry in sftp.listdir_attr(path):
        permissions = stat.filemode(entry.st_mode)
        entries.append(
            {
                "name": entry.filename,
                "size": entry.st_size,
                "modified": datetime.fromtimestamp(entry.st_mtime).isoformat(),
                "is_dir": stat.S_ISDIR(entry.st_mode),
                "permissions": permissions,
            }
        )
    return sorted(entries, key=lambda item: (not item["is_dir"], item["name"].lower()))


def remove_remote_path(sftp: paramiko.SFTPClient, path: str) -> None:
    attrs = sftp.stat(path)
    if stat.S_ISDIR(attrs.st_mode):
        for name in sftp.listdir(path):
            remove_remote_path(sftp, posixpath.join(path, name))
        sftp.rmdir(path)
    else:
        sftp.remove(path)


def remote_path_exists(sftp: paramiko.SFTPClient, path: str) -> bool:
    try:
        sftp.stat(path)
        return True
    except OSError:
        return False


def ensure_remote_directory(sftp: paramiko.SFTPClient, path: str) -> None:
    normalized = normalize_path(path)
    if normalized == "/":
        return

    parts = [part for part in normalized.split("/") if part]
    current = "/"
    for part in parts:
        current = posixpath.join(current, part) if current != "/" else f"/{part}"
        if remote_path_exists(sftp, current):
            continue
        sftp.mkdir(current)


def transfer_remote_path(
    source_sftp: paramiko.SFTPClient,
    target_sftp: paramiko.SFTPClient,
    source_path: str,
    target_path: str,
    conflict_mode: str,
    temp_dir: str,
    stats: dict[str, int],
) -> None:
    source_attrs = source_sftp.stat(source_path)
    source_is_dir = stat.S_ISDIR(source_attrs.st_mode)

    if source_is_dir:
        if remote_path_exists(target_sftp, target_path):
            target_attrs = target_sftp.stat(target_path)
            if not stat.S_ISDIR(target_attrs.st_mode):
                raise ValueError(f"Target path exists as file: {target_path}")
        else:
            ensure_remote_directory(target_sftp, target_path)

        for name in source_sftp.listdir(source_path):
            transfer_remote_path(
                source_sftp=source_sftp,
                target_sftp=target_sftp,
                source_path=posixpath.join(source_path, name),
                target_path=posixpath.join(target_path, name),
                conflict_mode=conflict_mode,
                temp_dir=temp_dir,
                stats=stats,
            )
        return

    if remote_path_exists(target_sftp, target_path):
        target_attrs = target_sftp.stat(target_path)
        if stat.S_ISDIR(target_attrs.st_mode):
            raise ValueError(f"Target path exists as directory: {target_path}")
        if conflict_mode == "skip":
            stats["skipped"] += 1
            return

    ensure_remote_directory(target_sftp, posixpath.dirname(target_path) or "/")
    temp_file = tempfile.NamedTemporaryFile(dir=temp_dir, delete=False)
    temp_path = temp_file.name
    temp_file.close()
    try:
        source_sftp.get(source_path, temp_path)
        target_sftp.put(temp_path, target_path)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
    stats["copied"] += 1


@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/bookmarks")
async def get_bookmarks():
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT id, name, host, port, username, path, created_at, updated_at,
                   CASE WHEN key_data_encrypted IS NOT NULL AND key_data_encrypted != '' THEN 1 ELSE 0 END AS has_key
            FROM bookmarks
            ORDER BY name COLLATE NOCASE
            """
        ).fetchall()
    return [dict(row) for row in rows]


@app.post("/api/bookmarks")
async def create_bookmark(request: BookmarkRequest):
    with get_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO bookmarks (name, host, port, username, password_encrypted, key_data_encrypted, path)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                request.name.strip(),
                request.host.strip(),
                request.port,
                request.username.strip(),
                encrypt_password(request.password),
                encrypt_password(request.key_data or ""),
                normalize_path(request.path),
            ),
        )
        conn.commit()
    return {"success": True, "id": str(cursor.lastrowid)}


@app.put("/api/bookmarks/{bookmark_id}")
async def update_bookmark(bookmark_id: str, request: BookmarkRequest):
    with get_db() as conn:
        row = conn.execute(
            "SELECT password_encrypted, key_data_encrypted FROM bookmarks WHERE id = ?",
            (bookmark_id,),
        ).fetchone()
        if not row:
            return error_response("Bookmark not found", 404)

        password_encrypted = (
            encrypt_password(request.password)
            if request.password
            else row["password_encrypted"]
        )
        key_data_encrypted = (
            encrypt_password(request.key_data)
            if request.key_data is not None and request.key_data != ""
            else row["key_data_encrypted"]
        )
        conn.execute(
            """
            UPDATE bookmarks
            SET name = ?, host = ?, port = ?, username = ?, password_encrypted = ?, key_data_encrypted = ?, path = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                request.name.strip(),
                request.host.strip(),
                request.port,
                request.username.strip(),
                password_encrypted,
                key_data_encrypted,
                normalize_path(request.path),
                bookmark_id,
            ),
        )
        conn.commit()
    return {"success": True}


@app.delete("/api/bookmarks/{bookmark_id}")
async def delete_bookmark(bookmark_id: str):
    with get_db() as conn:
        cursor = conn.execute("DELETE FROM bookmarks WHERE id = ?", (bookmark_id,))
        conn.commit()
    if cursor.rowcount == 0:
        return error_response("Bookmark not found", 404)
    return {"success": True}


def connect_with_saved_bookmark(
    bookmark_row: sqlite3.Row, key_data: Optional[str] = None
) -> dict:
    print(f"Decrypting password for {bookmark_row['username']}@{bookmark_row['host']}")
    password = decrypt_password(bookmark_row["password_encrypted"])
    stored_key_data = decrypt_password(bookmark_row["key_data_encrypted"] or "")
    effective_key_data = key_data or stored_key_data

    print(
        f"Password present: {bool(password)}, Key data present: {bool(effective_key_data)}"
    )

    if bookmark_row["password_encrypted"] and not password and not effective_key_data:
        print("ERROR: Cannot decrypt password and no key data available")
        raise ValueError(
            "Saved credentials could not be decrypted. Set a stable SFTP_ENCRYPTION_KEY and re-save the bookmark."
        )

    print(f"Creating session to {bookmark_row['host']}:{bookmark_row['port']}")
    session = sessions.create(
        host=bookmark_row["host"],
        port=int(bookmark_row["port"]),
        username=bookmark_row["username"],
        password=password,
        key_data=effective_key_data,
        default_path=bookmark_row["path"],
    )
    return {
        "success": True,
        "session_id": session.session_id,
        "host": session.host,
        "path": session.default_path,
        "message": f"Connected to {session.host} as {session.username}",
    }


@app.post("/api/bookmarks/{bookmark_id}/connect")
async def connect_bookmark(bookmark_id: str, request: Request):
    print(f"Connecting to bookmark {bookmark_id}")
    body = {}
    try:
        body = await request.json()
        print(f"Request body: {body}")
    except Exception as e:
        print(f"No request body or parse error: {e}")
        pass

    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM bookmarks WHERE id = ?", (bookmark_id,)
        ).fetchone()
    if not row:
        print(f"Bookmark {bookmark_id} not found")
        return error_response("Bookmark not found", 404)

    print(f"Found bookmark: {row['name']}@{row['host']}")

    try:
        result = connect_with_saved_bookmark(row, body.get("key_data"))
        print(f"Connection successful: {result}")
        return result
    except Exception as exc:
        import traceback

        print(f"Connection error: {exc}")
        traceback.print_exc()
        return error_response(f"Connection failed: {str(exc)}")


@app.post("/api/connect")
async def connect_sftp(request: ConnectRequest):
    try:
        session = sessions.create(
            host=request.host.strip(),
            port=int(request.port),
            username=request.username.strip(),
            password=request.password,
            key_data=request.key_data,
            default_path=request.path,
        )
    except Exception as exc:
        return error_response(str(exc))

    return {
        "success": True,
        "session_id": session.session_id,
        "host": session.host,
        "path": session.default_path,
        "message": f"Connected to {session.host} as {session.username}",
    }


@app.post("/api/list")
async def list_directory(request: ListRequest):
    session = get_session_or_404(request.session_id)
    if isinstance(session, JSONResponse):
        return session
    path = normalize_path(request.path)
    try:
        return {
            "success": True,
            "path": path,
            "entries": list_entries(session.sftp, path),
        }
    except Exception as exc:
        return error_response(str(exc))


@app.post("/api/preview")
async def preview_file(request: PreviewRequest):
    session = get_session_or_404(request.session_id)
    if isinstance(session, JSONResponse):
        return session

    try:
        remote_file = session.sftp.file(normalize_path(request.path), "rb")
        try:
            data = remote_file.read(request.max_bytes)
        finally:
            remote_file.close()
        text = data.decode("utf-8")
        truncated = len(data) == request.max_bytes
        return {"success": True, "content": text, "truncated": truncated}
    except UnicodeDecodeError:
        return error_response("File is not valid UTF-8 text")
    except Exception as exc:
        return error_response(str(exc))


@app.post("/api/download")
async def download_file(request: DownloadRequest):
    session = get_session_or_404(request.session_id)
    if isinstance(session, JSONResponse):
        return session

    remote_path = normalize_path(request.remote_path)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False) as handle:
            temp_path = handle.name
        session.sftp.get(remote_path, temp_path)
        return FileResponse(
            temp_path,
            filename=posixpath.basename(remote_path),
            media_type="application/octet-stream",
        )
    except Exception as exc:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)
        return error_response(str(exc))


@app.post("/api/upload")
async def upload_file(
    session_id: str = Form(...),
    remote_path: str = Form(...),
    file: UploadFile = File(...),
):
    session = get_session_or_404(session_id)
    if isinstance(session, JSONResponse):
        return session

    target_path = join_remote_path(remote_path, file.filename)
    try:
        with session.sftp.file(target_path, "wb") as remote_file:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                remote_file.write(chunk)
        return {"success": True, "message": f"Uploaded {file.filename}"}
    except Exception as exc:
        return error_response(str(exc))


@app.post("/api/mkdir")
async def make_directory(request: MkdirRequest):
    session = get_session_or_404(request.session_id)
    if isinstance(session, JSONResponse):
        return session
    try:
        session.sftp.mkdir(normalize_path(request.path))
        return {"success": True, "message": "Directory created"}
    except Exception as exc:
        return error_response(str(exc))


@app.post("/api/create-file")
async def create_file(request: CreateFileRequest):
    session = get_session_or_404(request.session_id)
    if isinstance(session, JSONResponse):
        return session
    try:
        target_path = normalize_path(request.remote_path)
        with session.sftp.file(target_path, "w") as remote_file:
            remote_file.write(request.content)
        return {"success": True, "message": "File created"}
    except Exception as exc:
        return error_response(str(exc))


@app.post("/api/rename")
async def rename_file(request: RenameRequest):
    session = get_session_or_404(request.session_id)
    if isinstance(session, JSONResponse):
        return session
    try:
        session.sftp.rename(
            normalize_path(request.old_path), normalize_path(request.new_path)
        )
        return {"success": True, "message": "Renamed successfully"}
    except Exception as exc:
        return error_response(str(exc))


@app.post("/api/delete")
async def delete_file(request: DeleteRequest):
    session = get_session_or_404(request.session_id)
    if isinstance(session, JSONResponse):
        return session
    try:
        remove_remote_path(session.sftp, normalize_path(request.path))
        return {"success": True, "message": "Deleted successfully"}
    except Exception as exc:
        return error_response(str(exc))


@app.post("/api/disconnect")
async def disconnect(request: DisconnectRequest):
    if sessions.remove(request.session_id):
        return {"success": True, "message": "Disconnected"}
    return error_response("No active connection", 404)


@app.post("/api/transfer")
async def transfer_file(request: TransferRequest):
    source_session = get_session_or_404(request.source_session_id)
    if isinstance(source_session, JSONResponse):
        return source_session
    target_session = get_session_or_404(request.target_session_id)
    if isinstance(target_session, JSONResponse):
        return target_session

    source_file_path = join_remote_path(request.source_path, request.file_name)
    target_file_path = join_remote_path(request.target_path, request.file_name)
    conflict_mode = (
        request.conflict_mode
        if request.conflict_mode in {"overwrite", "skip"}
        else "overwrite"
    )
    temp_dir = tempfile.mkdtemp(prefix="sftp-transfer-")
    stats = {"copied": 0, "skipped": 0}
    try:
        transfer_remote_path(
            source_sftp=source_session.sftp,
            target_sftp=target_session.sftp,
            source_path=source_file_path,
            target_path=target_file_path,
            conflict_mode=conflict_mode,
            temp_dir=temp_dir,
            stats=stats,
        )
        return {
            "success": True,
            "message": f"Transfer complete: copied {stats['copied']}, skipped {stats['skipped']}",
            "copied": stats["copied"],
            "skipped": stats["skipped"],
        }
    except Exception as exc:
        return error_response(str(exc))
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


# Get host home directory (for Docker)
HOST_HOME = os.environ.get("HOST_HOME", str(Path.home()))


@app.get("/api/local/list")
async def list_local(path: str = ""):
    """List local directory contents"""
    try:
        # Use HOST_HOME as base (mount point for host files in Docker)
        base_path = Path(HOST_HOME).resolve()

        # If no path specified, use base
        if not path or path == "~" or path == "/":
            target_path = base_path
        else:
            # Join with base path
            target_path = (base_path / path.lstrip("/")).resolve()

        # Security: ensure path is within base_path
        try:
            target_path.relative_to(base_path)
        except ValueError:
            target_path = base_path

        entries = []
        if target_path.exists():
            for item in target_path.iterdir():
                try:
                    stat_info = item.stat()
                    entries.append(
                        {
                            "name": item.name,
                            "is_dir": item.is_dir(),
                            "size": stat_info.st_size if item.is_file() else 0,
                            "modified": datetime.fromtimestamp(
                                stat_info.st_mtime
                            ).isoformat(),
                            "permissions": oct(stat_info.st_mode)[-3:],
                            "full_path": str(item),
                        }
                    )
                except (OSError, PermissionError):
                    continue

        # Sort: directories first, then files alphabetically
        entries.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))

        return {"success": True, "path": str(target_path), "entries": entries}
    except Exception as exc:
        return error_response(str(exc))


@app.get("/api/status")
async def status():
    return {
        "status": "running",
        "version": "2.0.0",
        "active_connections": sessions.count(),
        "session_ttl_seconds": SESSION_TTL_SECONDS,
        "encryption": "enabled",
    }


@app.post("/api/local/upload")
async def upload_local_to_remote(
    session_id: str = Form(...),
    remote_path: str = Form(...),
    local_path: str = Form(...),
):
    """Upload a local file to remote server"""
    session = get_session_or_404(session_id)
    if isinstance(session, JSONResponse):
        return session

    try:
        # Security check: ensure local_path is within HOST_HOME
        base_path = Path(HOST_HOME).resolve()
        local_file = Path(local_path).resolve()

        try:
            local_file.relative_to(base_path)
        except ValueError:
            return error_response("Access denied: file outside allowed directory", 403)

        if not local_file.exists():
            return error_response("Local file not found", 404)

        if not local_file.is_file():
            return error_response("Path is not a file", 400)

        # Upload to remote
        target_path = join_remote_path(remote_path, local_file.name)

        with open(local_file, "rb") as f:
            with session.sftp.file(target_path, "wb") as remote_file:
                while True:
                    chunk = f.read(1024 * 1024)
                    if not chunk:
                        break
                    remote_file.write(chunk)

        return {"success": True, "message": f"Uploaded {local_file.name}"}
    except Exception as exc:
        return error_response(str(exc))


@app.get("/api/local-info")
async def get_local_info():
    """Get local system info for the default local bookmark"""
    import platform
    import getpass

    # Use HOST_HOME (mount point for host files in Docker)
    home = Path(HOST_HOME).resolve()
    username = getpass.getuser()
    system = platform.system()

    return {
        "success": True,
        "name": "💻 Local Files",
        "host": "localhost",
        "path": str(home),
        "username": username,
        "system": system,
        "is_local": True,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=80)
