"""
二重螺旋 DNA API Client

Handles interactions with the dnabbs-api.yingxiong.com community API.
"""

import logging
import os
import urllib.parse
from typing import Optional, Tuple

import requests

from dna_sign import (
    build_signed_request,
    build_unsigned_request,
)
from daily_tasks import do_daily_tasks

logger = logging.getLogger(__name__)

BASE_URL = 'https://dnabbs-api.yingxiong.com/'
GAME_ID = 268  # 二重螺旋 CN game ID

# ─── RSA Public Key ──────────────────────────────────────────────────────────
# This can be fetched dynamically from config/getRsaPublicKey
# But we provide a fallback constant
DEFAULT_RSA_PUBLIC_KEY = None  # Will be fetched at runtime


def fetch_rsa_public_key(token: str) -> Optional[str]:
    """Fetch the RSA public key from the server."""
    url = urllib.parse.urljoin(BASE_URL, 'config/getRsaPublicKey')
    headers = build_unsigned_request(token)
    try:
        resp = requests.post(url, headers=headers, timeout=10)
        data = resp.json()
        if data.get('code') == 200 or data.get('code') == 0:
            key = data.get('data', {}).get('key')
            logger.info(f"Got RSA public key: {key[:50]}...")
            return key
        else:
            logger.warning(f"Failed to get RSA public key: {data}")
            return None
    except Exception as e:
        logger.warning(f"Error fetching RSA public key: {e}")
        return None


def check_signin_status(token: str) -> dict:
    """
    Check if already signed in today.
    GET/POST /encourage/signin/isHaveSignin { gameId: 268 }
    This endpoint does NOT need signing (not in sign_api_urls).
    """
    url = urllib.parse.urljoin(BASE_URL, 'encourage/signin/isHaveSignin')
    payload = {'gameId': GAME_ID}
    headers = build_unsigned_request(token)

    try:
        resp = requests.post(url, headers=headers, data=payload, timeout=15)
        return resp.json()
    except Exception as e:
        logger.error(f"Error checking signin status: {e}")
        return {'code': -1, 'msg': str(e)}


def show_signin_calendar(token: str) -> dict:
    """
    Show sign-in calendar info.
    GET/POST /encourage/signin/show { gameId: 268 }
    This endpoint does NOT need signing.
    """
    url = urllib.parse.urljoin(BASE_URL, 'encourage/signin/show')
    payload = {'gameId': GAME_ID}
    headers = build_unsigned_request(token)

    try:
        resp = requests.post(url, headers=headers, data=payload, timeout=15)
        return resp.json()
    except Exception as e:
        logger.error(f"Error getting signin calendar: {e}")
        return {'code': -1, 'msg': str(e)}


def bbs_sign(token: str, pub_key: str) -> dict:
    """
    Daily BBS sign-in.
    POST /user/signIn { gameId: 268 }
    Needs signing (in sign_api_urls).
    """
    url = urllib.parse.urljoin(BASE_URL, 'user/signIn')
    payload = {'gameId': GAME_ID}

    headers, body = build_signed_request(pub_key, payload, token)

    try:
        resp = requests.post(url, headers=headers, data=body, timeout=15)
        return resp.json()
    except Exception as e:
        logger.error(f"Error during BBS sign-in: {e}")
        return {'code': -1, 'msg': str(e)}


def do_daily_signin(token: str) -> Tuple[bool, list]:
    """
    Perform the daily sign-in for 二重螺旋.

    Flow:
    1. Check BBS sign-in status — if not done, perform community sign-in
    2. Daily community tasks (browse, like, share, reply)

    Returns:
        (success: bool, logs: list[str])
    """
    logs = []
    success = True

    # Step 0: Get RSA public key
    pub_key = fetch_rsa_public_key(token)
    if not pub_key:
        logs.append("无法获取RSA公钥")

    # Step 1: Check BBS sign-in status
    logger.info("检查今日社区签到状态...")
    status = check_signin_status(token)
    logger.info(f"签到状态响应: {status}")

    bbs_already_signed = False
    data = status.get('data')
    if data and isinstance(data, dict):
        bbs_already_signed = data.get('haveSignin', False) or data.get('signInStatus', False)

    has_auth_error = status.get('code') in (10000, 101)
    if has_auth_error:
        msg = "身份验证失败 - Token可能已过期" if status.get('code') == 101 else "参数错误，可能需要更新签名算法"
        logs.append(msg)
        return False, logs

    # Step 2: BBS sign-in (community)
    if not bbs_already_signed:
        if not pub_key:
            logs.append("无法执行社区签到：缺少RSA公钥")
            success = False
        else:
            logger.info("执行社区签到...")
            bbs_result = bbs_sign(token, pub_key)
            logger.info(f"社区签到结果: {bbs_result}")

            if bbs_result.get('code') == 0 or bbs_result.get('code') == 200:
                logs.append("社区签到成功！")
            else:
                msg = bbs_result.get('msg', '未知错误')
                logs.append(f"社区签到失败: {msg}")
    else:
        logs.append("社区签到：今日已签到")

    # Step 3: Daily community tasks (browse, like, share, reply)
    logger.info("开始执行每日任务...")
    task_logs = do_daily_tasks(token)
    logs.extend(task_logs)

    return success, logs
