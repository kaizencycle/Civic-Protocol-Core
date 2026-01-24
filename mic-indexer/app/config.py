from pydantic import BaseModel
from urllib.parse import urlparse
import socket
import logging
import os

logger = logging.getLogger(__name__)

# =============================================================================
# Database Configuration with IPv4 Forcing
# =============================================================================
# This fixes connectivity issues on platforms like Render.com that don't support
# IPv6 outbound connections to Supabase.

def resolve_hostname_to_ipv4(hostname: str) -> str | None:
    """Resolve a hostname to its IPv4 address."""
    try:
        result = socket.getaddrinfo(hostname, None, socket.AF_INET, socket.SOCK_STREAM)
        if result:
            ipv4_address = result[0][4][0]
            logger.info(f"Resolved {hostname} to IPv4: {ipv4_address}")
            return ipv4_address
    except socket.gaierror as e:
        logger.warning(f"Failed to resolve {hostname} to IPv4: {e}")
    return None


def get_engine_kwargs(database_url: str) -> dict:
    """Get engine kwargs with IPv4 forcing for PostgreSQL connections."""
    kwargs = {}
    
    if not database_url.startswith("postgresql"):
        return kwargs
    
    # Connection pool settings optimized for serverless/Supabase
    kwargs.update({
        "pool_size": 5,
        "max_overflow": 10,
        "pool_timeout": 30,
        "pool_recycle": 300,  # Recycle connections after 5 minutes
        "pool_pre_ping": True,  # Verify connections before use
    })
    
    # Force IPv4 connections to fix Render.com/Supabase connectivity
    try:
        parsed = urlparse(database_url)
        hostname = parsed.hostname
        
        if hostname and hostname not in ("localhost", "127.0.0.1", "::1"):
            ipv4_addr = resolve_hostname_to_ipv4(hostname)
            if ipv4_addr:
                # Use hostaddr to bypass DNS and force IPv4
                kwargs["connect_args"] = {"hostaddr": ipv4_addr}
                logger.info(f"Configured IPv4 connection to {hostname} via {ipv4_addr}")
    except Exception as e:
        logger.warning(f"Error configuring IPv4 connection: {e}")
    
    return kwargs


class Settings(BaseModel):
    DB_URL: str = os.getenv("MIC_DB_URL", "sqlite:///./mic.db")
    API_KEY: str | None = os.getenv("MIC_API_KEY")
    XP_TO_MIC_RATIO: float = float(os.getenv("MIC_XP_TO_MIC_RATIO", "0.001"))
    CORS_ALLOW_ORIGINS: str = os.getenv("CORS_ALLOW_ORIGINS", "*")

settings = Settings()
engine_kwargs = get_engine_kwargs(settings.DB_URL)
