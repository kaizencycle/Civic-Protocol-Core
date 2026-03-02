# sdk/python/db_utils.py
"""
Database utilities for Mobius services.

Handles common database connection issues, particularly:
- IPv6 connectivity issues on platforms like Render.com
- Supabase connection configuration
- Connection pooling settings for serverless environments
"""

import os
import socket
import logging
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

logger = logging.getLogger(__name__)


def resolve_hostname_to_ipv4(hostname: str) -> str | None:
    """
    Resolve a hostname to its IPv4 address.
    Returns None if resolution fails.
    """
    try:
        # Force IPv4 resolution using AF_INET
        result = socket.getaddrinfo(hostname, None, socket.AF_INET, socket.SOCK_STREAM)
        if result:
            ipv4_address = result[0][4][0]
            logger.info(f"Resolved {hostname} to IPv4: {ipv4_address}")
            return ipv4_address
    except socket.gaierror as e:
        logger.warning(f"Failed to resolve {hostname} to IPv4: {e}")
    return None


def normalize_database_url(database_url: str, driver: str = "psycopg2") -> str:
    """
    Normalize a database URL for SQLAlchemy compatibility.
    
    Handles:
    - postgres:// -> postgresql:// conversion
    - Driver specification (psycopg2 vs psycopg3)
    
    Args:
        database_url: The original DATABASE_URL
        driver: Either "psycopg2" (default, uses postgresql://) or "psycopg3" (uses postgresql+psycopg://)
    
    Returns:
        Normalized database URL
    """
    if database_url.startswith("https://") or database_url.startswith("http://"):
        raise ValueError(
            "Invalid DATABASE_URL format. You provided an HTTP(S) URL, but SQLAlchemy "
            "requires a PostgreSQL connection string.\n\n"
            "For Supabase, use the connection string from:\n"
            "  Project Settings > Database > Connection string\n\n"
            "Format: postgresql://postgres.[project-ref]:[password]@aws-0-[region].pooler.supabase.com:6543/postgres\n"
            "Or direct: postgresql://postgres:[password]@db.[project-ref].supabase.co:5432/postgres"
        )
    
    if driver == "psycopg3":
        # psycopg3 uses postgresql+psycopg://
        if database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql+psycopg://", 1)
        elif database_url.startswith("postgresql://"):
            database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    else:
        # psycopg2 uses postgresql://
        if database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql://", 1)
    
    return database_url


def get_connect_args_for_ipv4(database_url: str) -> dict:
    """
    Get connect_args that force IPv4 connection for psycopg2.
    
    This solves the common issue on Render.com and other platforms
    where IPv6 connections fail to Supabase.
    
    Args:
        database_url: The database URL to analyze
    
    Returns:
        A dict of connect_args to pass to create_engine()
    """
    connect_args = {}
    
    if not database_url.startswith("postgresql"):
        return connect_args
    
    try:
        parsed = urlparse(database_url)
        hostname = parsed.hostname
        
        if not hostname:
            return connect_args
        
        # Only apply IPv4 forcing for remote hosts (not localhost/127.0.0.1)
        if hostname in ("localhost", "127.0.0.1", "::1"):
            return connect_args
        
        # Resolve to IPv4
        ipv4_addr = resolve_hostname_to_ipv4(hostname)
        
        if ipv4_addr:
            # Use hostaddr to force IPv4 connection
            # This bypasses DNS resolution in libpq and uses the specified IP directly
            connect_args["options"] = f"-c statement_timeout=30000"
            
            # For psycopg2, we can use the 'hostaddr' parameter directly
            # But it requires modifying the DSN, so we'll use a different approach
            # We'll set the hostaddr in connect_args
            connect_args["hostaddr"] = ipv4_addr
            
            logger.info(f"Configured IPv4 connection to {hostname} via {ipv4_addr}")
    except Exception as e:
        logger.warning(f"Error configuring IPv4 connection: {e}")
    
    return connect_args


def get_engine_kwargs(database_url: str, is_serverless: bool = True) -> dict:
    """
    Get recommended engine kwargs for SQLAlchemy create_engine().
    
    Args:
        database_url: The database URL
        is_serverless: Whether running in a serverless environment (affects pool settings)
    
    Returns:
        Dict of kwargs to pass to create_engine()
    """
    kwargs = {}
    
    if not database_url.startswith("postgresql"):
        return kwargs
    
    # Connection pool settings optimized for serverless/Supabase
    if is_serverless:
        kwargs.update({
            "pool_size": 5,
            "max_overflow": 10,
            "pool_timeout": 30,
            "pool_recycle": 300,  # Recycle connections after 5 minutes
            "pool_pre_ping": True,  # Verify connections before use
        })
    
    # Add IPv4-forcing connect_args
    connect_args = get_connect_args_for_ipv4(database_url)
    if connect_args:
        kwargs["connect_args"] = connect_args
    
    return kwargs


def create_database_engine(database_url: str | None = None, 
                          env_var: str = "DATABASE_URL",
                          default: str = "sqlite:///./app.db",
                          driver: str = "psycopg2",
                          is_serverless: bool = True):
    """
    Create a SQLAlchemy engine with proper configuration for Supabase/Render.
    
    This is a convenience function that handles:
    - URL normalization
    - IPv4 forcing for remote connections
    - Connection pool configuration
    
    Args:
        database_url: The database URL (if None, reads from env_var)
        env_var: Environment variable name to read URL from
        default: Default URL if env var is not set
        driver: Either "psycopg2" or "psycopg3"
        is_serverless: Whether running in serverless (affects pool settings)
    
    Returns:
        SQLAlchemy Engine instance
    """
    from sqlalchemy import create_engine
    
    if database_url is None:
        database_url = os.getenv(env_var, default)
    
    # Normalize URL for the driver
    database_url = normalize_database_url(database_url, driver=driver)
    
    # Get engine kwargs
    engine_kwargs = get_engine_kwargs(database_url, is_serverless=is_serverless)
    
    logger.info(f"Creating database engine with driver={driver}, serverless={is_serverless}")
    
    return create_engine(database_url, **engine_kwargs)


# For backwards compatibility and simple imports
__all__ = [
    "normalize_database_url",
    "get_connect_args_for_ipv4", 
    "get_engine_kwargs",
    "create_database_engine",
    "resolve_hostname_to_ipv4",
]
