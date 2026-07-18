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
    rsa_encrypt,
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


def game_sign_in(token: str, pub_key: str, day_award_id: int, period_id: int) -> dict:
    """
    Game sign-in (claim daily reward).
    POST /encourage/signin/signin { dayAwardId, periodId, signinType: 1 }
    Needs signing (in sign_api_urls).
    """
    url = urllib.parse.urljoin(BASE_URL, 'encourage/signin/signin')
    payload = {
        'dayAwardId': day_award_id,
        'periodId': period_id,
        'signinType': 1,
    }

    headers, body = build_signed_request(pub_key, payload, token)

    try:
        resp = requests.post(url, headers=headers, data=body, timeout=15)
        return resp.json()
    except Exception as e:
        logger.error(f"Error during game sign-in: {e}")
        return {'code': -1, 'msg': str(e)}


def do_daily_signin(token: str) -> Tuple[bool, list]:
    """
    Perform the daily sign-in for 二重螺旋.

    Flow:
    1. Check BBS sign-in status — if not done, perform community sign-in
    2. Get calendar (period info + today's game sign-in status)
    3. If game sign-in not done today, claim the daily reward

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

    # Step 3: Get calendar and check game sign-in status
    logger.info("获取签到日历...")
    calendar = show_signin_calendar(token)
    logger.info(f"签到日历: {calendar}")

    cal_data = calendar.get('data', {})
    if cal_data:
        today_game_signed = cal_data.get('todaySignin', False)

        if today_game_signed:
            logs.append("游戏签到：今日已签到")
        else:
            if not pub_key:
                logs.append("无法执行游戏签到：缺少RSA公钥")
                success = False
            else:
                # Determine correct dayAwardId
                period_id = cal_data.get('period', {}).get('id', 0)
                signin_time = cal_data.get('signinTime', 0)
                today_day = signin_time + 1  # Next unclaimed day
                day_award_list = cal_data.get('dayAward', [])

                day_award_id = None
                for award in day_award_list:
                    if isinstance(award, dict) and award.get('dayInPeriod') == today_day:
                        day_award_id = award.get('id')
                        break

                if period_id and day_award_id:
                    logger.info(f"执行游戏签到 (dayAwardId={day_award_id}, periodId={period_id})...")
                    game_result = game_sign_in(token, pub_key, day_award_id, period_id)
                    logger.info(f"游戏签到结果: {game_result}")
                    if game_result.get('code') == 0 or game_result.get('code') == 200:
                        logs.append("游戏签到成功！")
                    else:
                        logs.append(f"游戏签到: {game_result.get('msg', '')}")
                else:
                    logs.append("游戏签到：无可用签到数据")
    else:
        logs.append("获取签到日历失败")

    # Step 4: Daily community tasks (browse, like, share, reply)
    logger.info("开始执行每日任务...")
    task_logs = do_daily_tasks(token)
    logs.extend(task_logs)

    return success, logs
