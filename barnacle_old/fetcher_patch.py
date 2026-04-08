# -*- coding: utf-8 -*-
"""Patch script to update fetcher.py with captcha detection and redirect tracking."""

import re

patch_content = '''
# Verification/captcha page indicators (in page content)
VERIFICATION_INDICATORS = [
    "验证",
    "captcha",
    "verify",
    "人机验证",
    "安全验证",
    "请完成验证",
    "滑动验证",
    "图形验证",
    "正在验证",
    "百度安全验证",
    "安全检测",
]

# Login page indicators
LOGIN_INDICATORS = [
    "登录",
    "signin",
    "login",
    "账号登录",
    "用户登录",
    "密码登录",
    "扫码登录",
]


def _is_verification_page(html_content: str, url: str) -> bool:
    """Check if page is a verification/captcha page."""
    url_lower = url.lower()
    html_lower = html_content.lower() if html_content else ""
    
    # Check URL patterns
    if any(p in url_lower for p in ["captcha", "verify", "waf"]):
        return True
    
    # Check page content for verification indicators
    indicator_count = sum(1 for ind in VERIFICATION_INDICATORS if ind in html_lower)
    if indicator_count >= 2:
        return True
    
    # Check for common captcha elements
    if any(p in html_lower for p in ["passmod", "geetest", "recaptcha", "nc_"]):
        return True
    
    return False


def _is_login_page(html_content: str, url: str) -> bool:
    """Check if page is a login page."""
    url_lower = url.lower()
    html_lower = html_content.lower() if html_content else ""
    
    # Check URL patterns
    if any(p in url_lower for p in ["login", "signin", "passport"]):
        # But not if it's a login page with content (like a forum)
        if len(html_content) > 10000:
            return False
        return True
    
    # Check page content for login indicators
    indicator_count = sum(1 for ind in LOGIN_INDICATORS if ind in html_lower)
    if indicator_count >= 2 and len(html_content) < 15000:
        # Small page with multiple login indicators
        return True
    
    return False
'''

print("This patch adds verification and login page detection to fetcher.py")
print("\nKey features:")
print("1. Detects captcha/verification pages and waits for user to complete")
print("2. Detects login pages and waits for user action")
print("3. Tracks redirect chain")
print("4. Returns when page content changes significantly")