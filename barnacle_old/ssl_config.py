# -*- coding: utf-8 -*-
"""
SSL Certificate Configuration for curl_cffi.

curl_cffi has known SSL certificate issues on Windows:
1. Windows doesn't have a built-in CA bundle that curl can use
2. Unicode characters in paths cause certificate loading failures
3. certifi's PEM format may not work with curl_cffi on Windows

This module provides automatic SSL configuration across platforms.
"""

import os
import platform
import logging
from typing import Optional, Union

logger = logging.getLogger(__name__)


def get_ssl_verify_setting() -> Union[bool, str]:
    """
    Get the appropriate SSL verification setting for the current platform.

    Returns:
        - str path: Path to CA bundle if found
        - True: Fallback to system default

    Platform-specific behavior:
        - Windows: Try certifi, fallback to True
        - Linux: Use system CA bundle or certifi
        - macOS: Use system CA bundle or certifi
    """
    system = platform.system()

    # Check for environment variable override
    env_verify = os.environ.get('BARNACLE_SSL_VERIFY', '').lower()
    if env_verify in ('0', 'false', 'no'):
        logger.debug("SSL verification disabled by environment variable")
        return False
    elif env_verify in ('1', 'true', 'yes'):
        logger.debug("SSL verification enabled by environment variable")
        return True
    elif env_verify:
        # Treat as custom CA path
        if os.path.exists(env_verify):
            logger.debug(f"Using custom CA bundle: {env_verify}")
            return env_verify
        else:
            logger.warning(f"Custom CA bundle not found: {env_verify}")

    # Try certifi first (works on all platforms)
    try:
        import certifi
        certifi_path = certifi.where()
        if os.path.exists(certifi_path):
            logger.debug(f"Using certifi CA bundle: {certifi_path}")
            return certifi_path
    except ImportError:
        pass

    # Platform-specific CA paths
    if system == "Linux":
        linux_ca_paths = [
            "/etc/ssl/certs/ca-certificates.crt",  # Debian/Ubuntu
            "/etc/pki/tls/certs/ca-bundle.crt",    # RHEL/CentOS
            "/etc/ssl/ca-bundle.pem",               # OpenSUSE
            "/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem",  # Fedora
        ]
        for path in linux_ca_paths:
            if os.path.exists(path):
                logger.debug(f"Using system CA bundle: {path}")
                return path

    elif system == "Darwin":  # macOS
        mac_ca_paths = [
            "/etc/ssl/cert.pem",  # Homebrew openssl
            "/usr/local/etc/openssl@1.1/cert.pem",
            "/usr/local/etc/openssl/cert.pem",
        ]
        for path in mac_ca_paths:
            if os.path.exists(path):
                logger.debug(f"Using macOS CA bundle: {path}")
                return path

    # Fallback to True (let curl_cffi try its default)
    logger.debug("Using default SSL verification")
    return True


def configure_curl_cffi_ssl():
    """
    Configure curl_cffi SSL settings globally.

    This sets environment variables that curl_cffi respects.
    Call this before importing curl_cffi for best results.
    """
    verify = get_ssl_verify_setting()

    if isinstance(verify, str):
        # Set CURL_CA_BUNDLE for curl
        os.environ['CURL_CA_BUNDLE'] = verify
        os.environ['SSL_CERT_FILE'] = verify
        logger.info(f"Configured curl_cffi to use CA bundle: {verify}")
    elif verify is False:
        logger.warning(
            "SSL verification is disabled. "
            "For production, set BARNACLE_SSL_VERIFY=/path/to/ca.pem"
        )

    return verify


# Pre-computed default for performance
DEFAULT_VERIFY = get_ssl_verify_setting()


if __name__ == "__main__":
    # Test the configuration
    print(f"Platform: {platform.system()}")
    print(f"Default SSL verify setting: {DEFAULT_VERIFY}")

    # Test with curl_cffi
    try:
        from curl_cffi.requests import Session

        verify = DEFAULT_VERIFY
        print(f"\nTesting with verify={verify}")

        with Session() as s:
            r = s.get("https://example.com", impersonate="chrome136", verify=verify, timeout=10)
            print(f"Success! Status: {r.status_code}")
    except Exception as e:
        print(f"Error: {e}")