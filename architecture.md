# Belfast SFTP Web Client - Architecture Plan

## Overview
A self-hosted, containerized SFTP web client built with Python/FastAPI and a vanilla JavaScript frontend.

## Technology Stack
- **Backend:** Python 3.11 + FastAPI
- **SFTP Library:** asyncssh (native SSH/SFTP protocol implementation)
- **Frontend:** Vanilla HTML5 + CSS3 + JavaScript (no frameworks)
- **Container:** Single Docker image based on python:3.11-slim

## Architecture Components

### 1. Backend (FastAPI)
```
/app/
├── main.py              # FastAPI app, routes
├── sftp_client.py       # SSH/SFTP connection handler
├── session_manager.py   # In-memory session store
└── models.py            # Pydantic models
```

**Key Endpoints:**
- `POST /api/connect` - Establish SFTP connection
- `POST /api/disconnect` - Close connection
- `GET /api/files?path=` - List directory contents
- `POST /api/navigate` - Change directory
- `POST /api/download` - Download file (streaming)
- `POST /api/upload` - Upload file
- `POST /api/delete` - Delete file/directory
- `POST /api/mkdir` - Create directory

### 2. Frontend
- Single-page application
- Dark mode Belfast aesthetic (#0d1117 background, #58a6ff accents)
- File browser with drag-and-drop upload
- Real-time connection status

### 3. Session Management
- In-memory session store (UUID → SSH connection)
- Sessions auto-expire after 30 minutes
- No persistence (security + simplicity)

### 4. Security
- No external dependencies (pure Python)
- No SSH keys stored server-side
- Credentials only in memory during active session
- Optional: Basic auth for the web interface itself

## Timeline (1 Week)

| Day | Task |
|-----|------|
| Day 1 | Core backend structure, SFTP client wrapper |
| Day 2 | API endpoints (connect, list, navigate) |
| Day 3 | File operations (upload, download, delete) |
| Day 4 | Frontend UI, Belfast theme implementation |
| Day 5 | Integration testing, bug fixes |
| Day 6 | Docker containerization, optimization |
| Day 7 | Documentation, final polish |

## Docker Strategy
Single container with:
- Python runtime
- App code
- Static files served via FastAPI
- Port 8080 exposed
- No volume mounts required (stateless)
