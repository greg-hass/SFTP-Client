import uuid
import asyncio
import asyncssh
from datetime import datetime, timedelta
from typing import Dict, Optional
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class SFTPSession:
    def __init__(self, session_id: str, conn: asyncssh.SSHClientConnection, sftp: asyncssh.SFTPClient):
        self.session_id = session_id
        self.conn = conn
        self.sftp = sftp
        self.current_path = "/"
        self.created_at = datetime.now()
        self.last_activity = datetime.now()
        self.host: str = ""
        self.username: str = ""
    
    def touch(self):
        self.last_activity = datetime.now()
    
    def is_expired(self, timeout_minutes: int = 30) -> bool:
        return datetime.now() - self.last_activity > timedelta(minutes=timeout_minutes)


class SessionManager:
    def __init__(self):
        self.sessions: Dict[str, SFTPSession] = {}
        self._cleanup_task: Optional[asyncio.Task] = None
    
    async def start(self):
        """Start the cleanup background task"""
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("Session manager started")
    
    async def stop(self):
        """Stop the cleanup task and close all sessions"""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        
        # Close all active sessions
        for session in list(self.sessions.values()):
            await self.close_session(session.session_id)
        logger.info("Session manager stopped")
    
    async def _cleanup_loop(self):
        """Background task to clean up expired sessions"""
        while True:
            try:
                await asyncio.sleep(60)  # Check every minute
                await self._cleanup_expired()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Cleanup error: {e}")
    
    async def _cleanup_expired(self):
        """Close expired sessions"""
        expired = [
            sid for sid, session in self.sessions.items()
            if session.is_expired()
        ]
        for sid in expired:
            logger.info(f"Closing expired session: {sid}")
            await self.close_session(sid)
    
    async def create_session(
        self,
        host: str,
        port: int,
        username: str,
        password: str
    ) -> SFTPSession:
        """Create a new SFTP session"""
        try:
            conn = await asyncssh.connect(
                host=host,
                port=port,
                username=username,
                password=password,
                known_hosts=None,  # Allow unknown hosts (use with caution)
                connect_timeout=30
            )
            sftp = await conn.start_sftp_client()
            
            session_id = str(uuid.uuid4())
            session = SFTPSession(session_id, conn, sftp)
            session.host = host
            session.username = username
            
            # Get initial directory
            session.current_path = await sftp.getcwd() or "/"
            
            self.sessions[session_id] = session
            logger.info(f"Created session {session_id} for {username}@{host}")
            return session
            
        except asyncssh.Error as e:
            logger.error(f"SSH connection failed: {e}")
            raise ConnectionError(f"Failed to connect: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            raise ConnectionError(f"Connection error: {str(e)}")
    
    async def close_session(self, session_id: str):
        """Close a specific session"""
        session = self.sessions.pop(session_id, None)
        if session:
            try:
                session.conn.close()
                await session.conn.wait_closed()
                logger.info(f"Closed session {session_id}")
            except Exception as e:
                logger.error(f"Error closing session {session_id}: {e}")
    
    def get_session(self, session_id: str) -> Optional[SFTPSession]:
        """Get a session by ID"""
        session = self.sessions.get(session_id)
        if session:
            session.touch()
        return session
    
    def session_exists(self, session_id: str) -> bool:
        """Check if a session exists"""
        return session_id in self.sessions


# Global session manager instance
session_manager = SessionManager()
