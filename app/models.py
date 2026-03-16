from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class ConnectionRequest(BaseModel):
    host: str
    port: int = 22
    username: str
    password: str


class ConnectionResponse(BaseModel):
    session_id: str
    connected: bool
    current_path: str
    message: str


class FileInfo(BaseModel):
    name: str
    path: str
    is_directory: bool
    size: int
    modified_time: Optional[datetime] = None
    permissions: str


class FileListResponse(BaseModel):
    path: str
    files: List[FileInfo]


class NavigateRequest(BaseModel):
    session_id: str
    path: str


class PathRequest(BaseModel):
    session_id: str
    path: str


class UploadRequest(BaseModel):
    session_id: str
    path: str
    filename: str
    content: str  # base64 encoded


class OperationResponse(BaseModel):
    success: bool
    message: str
