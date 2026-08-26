"""
二重螺旋 DNA API Client

Handles interactions with the dnabbs-api.yingxiong.com community API.
"""

import logging
import os
import time
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
    Check if already BBS-signed in today.
    POST /user/haveSignInNew { gameId: 268 }
    Note: this endpoint IS in sign_api_urls (needs signing).
    Returns data like {"haveSignIn": bool, "haveRoleSignIn": bool, ...}
    """
    url = urllib.parse.urljoin(BASE_URL, 'user/haveSignInNew')
    payload = {'gameId': GAME_ID}

    pub_key = fetch_rsa_public_key(token)
    if pub_key:
        headers, body = build_signed_request(pub_key, payload, token)
        try:
            resp = requests.post(url, headers=headers, data=body, timeout=15)
            return resp.json()
        except Exception as e:
            logger.error(f"Error checking signin status: {e}")
            return {'code': -1, 'msg': str(e)}
    return {'code': -1, 'msg': 'no rsa key'}


def show_signin_calendar(token: str) -> dict:
    """
    Show sign-in calendar info.
    POST /encourage/signin/show { gameId: 268 }
    Observed: unsigned web-style requests return 403; signed h5 requests return 200.
    """
    url = urllib.parse.urljoin(BASE_URL, 'encourage/signin/show')
    payload = {'gameId': GAME_ID}

    pub_key = fetch_rsa_public_key(token)
    if not pub_key:
        return {'code': -1, 'msg': 'no rsa key'}
    headers, body = build_signed_request(pub_key, payload, token)

    try:
        resp = requests.post(url, headers=headers, data=body, timeout=15)
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


def _check_welfare_registered(token: str) -> bool:
    """领取后重新查询福利日历，确认 todaySignin 是否真的变为 True。"""
    verify_calendar = show_signin_calendar(token)
    vdata = verify_calendar.get('data') if isinstance(verify_calendar, dict) else None
    return bool(vdata.get('todaySignin')) if isinstance(vdata, dict) else False


def game_welfare_sign(token: str, pub_key: str, day_award_id: int, period_id: int) -> dict:
    """
    Daily game welfare (福利) sign-in.
    POST /encourage/signin/signin { gameId, dayAwardId, periodId, signinType:1, signInType:1 }
    Needs signing (in sign_api_urls).

    ⚠️ 实测（2026-08-22/23）——该接口必须同时携带 gameId 与 signInType，
    否则返回 {'code':200} 无 data（日历 todaySignin 仍为 False = 假成功/未登记）：
      - 缺 gameId   → 200 无 data，未登记
      - 有 gameId 但缺 signInType → 200 无 data，未登记
      - gameId + signInType 齐备 → 200 + data:{signinTimeNow, sendDayAward:True}，
        todaySignin 变 True（真登记）
    服务器自 2026-08-20 之后开始强制校验这两个参数。
    """
    url = urllib.parse.urljoin(BASE_URL, 'encourage/signin/signin')
    payload = {
        'gameId': GAME_ID,
        'dayAwardId': day_award_id,
        'periodId': period_id,
        'signinType': 1,
        'signInType': 1,  # 隐藏必填参数（2026-08-23 实测确认）
    }
    headers, body = build_signed_request(pub_key, payload, token)
    try:
        resp = requests.post(url, headers=headers, data=body, timeout=15)
        return resp.json()
    except Exception as e:
        logger.error(f"Error during game welfare sign-in: {e}")
        return {'code': -1, 'msg': str(e)}


def _to_seconds(ts) -> int:
    """Coerce a timestamp to seconds; treat ms timestamps (>1e12) as ms."""
    try:
        ts = int(ts)
    except (TypeError, ValueError):
        return 0
    if ts > 1_000_000_000_000:  # ms
        ts //= 1000
    return ts


def resolve_today_day_award(calendar_data: dict) -> Tuple[Optional[int], Optional[int]]:
    """
    From a signCalendar `data` payload, determine (dayAwardId, periodId) for today.

    Uses period.startDate (period start, local midnight) vs the CURRENT date to
    compute dayInPeriod for today; does NOT rely on `signinTime` (which is the
    last-signed day index, not a timestamp).
    """
    day_in_period, period_id = resolve_today_day_in_period(calendar_data)
    if day_in_period is None:
        return None, None
    day_awards = calendar_data.get('dayAward') or []
    for d in day_awards:
        if d.get('dayInPeriod') == day_in_period and d.get('periodId') == period_id:
            return d.get('id'), period_id
    # Fallback: the largest dayInPeriod that is <= target_day (or just the max)
    fallback = None
    best_day = -1
    for d in day_awards:
        if d.get('periodId') != period_id:
            continue
        dip = d.get('dayInPeriod', 0)
        if dip > day_in_period:
            continue
        if dip > best_day:
            best_day = dip
            fallback = d
    if fallback is None:
        # Last resort: first entry
        fallback = day_awards[0]
    return fallback.get('id'), period_id


def resolve_today_day_in_period(calendar_data: dict) -> Tuple[Optional[int], Optional[int]]:
    """
    Return (dayInPeriod, periodId) for TODAY, computed from period.startDate
    vs the current UTC date. dayInPeriod=1 corresponds to startDate day.
    """
    if not isinstance(calendar_data, dict):
        return None, None
    period = calendar_data.get('period') or {}
    period_id = period.get('id')
    start_date = _to_seconds(period.get('startDate', 0))
    if start_date <= 0 or period_id is None:
        return None, None
    now = time.time()
    if now < start_date:
        return None, None
    target_day = int((now - start_date) // 86400) + 1
    return target_day, period_id


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
        bbs_already_signed = bool(data.get('haveSignIn', False) or data.get('haveRoleSignIn', False))

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

    # Step 2.5: Game welfare sign-in (福利签到)
    logger.info("检查游戏福利签到状态...")
    calendar = show_signin_calendar(token)
    cal_data = calendar.get('data') if isinstance(calendar, dict) else None
    today_signed = bool(cal_data.get('todaySignin')) if isinstance(cal_data, dict) else False
    if today_signed:
        logs.append("福利签到：今日已签到")
    elif not pub_key:
        logs.append("无法执行福利签到：缺少RSA公钥")
        success = False
    elif not isinstance(cal_data, dict):
        logs.append(f"福利签到失败: {calendar.get('msg', '日历数据异常')}")
    else:
        day_award_id, period_id = resolve_today_day_award(cal_data)
        day_in_period, _ = resolve_today_day_in_period(cal_data)

        # ⚠️ 实测（2026-08-21）：encourage/signin/signin 返回 code==200 并不代表
        # 领取登记成功——8/20 成功时响应带 data: {signinTimeNow:'20', sendDayAward:True}，
        # 8/21 失败时响应只有 {'code':200} 无 data（日历 todaySignin 仍为 False）。
        # 因此必须以"领取后重新查询日历 todaySignin"为唯一成功判据。
        #
        # 参数语义实测：dayAwardId 传【奖励记录 id】（如 990）或【dayInPeriod 序号】
        # （如 21）都可能被接受；为稳妥起见依次尝试两种形式，每种都验证 todaySignin。
        candidates = []
        if day_award_id is not None:
            candidates.append(('awardId', day_award_id))
        if day_in_period is not None and day_in_period != day_award_id:
            candidates.append(('dayInPeriod', day_in_period))

        if not candidates:
            logs.append("福利签到：无法解析今日奖励信息")
        else:
            registered = False
            welfare_result = {}
            for label, param in candidates:
                logger.info(f"执行福利签到 dayAwardId({label})={param} periodId={period_id}...")
                welfare_result = game_welfare_sign(token, pub_key, param, period_id)
                logger.info(f"福利签到结果({label}={param}): {welfare_result}")

                # 领取后验证：重新查询日历，确认 todaySignin 真正变为 True
                registered = _check_welfare_registered(token)
                logger.info(f"福利签到登记校验({label}={param}): todaySignin={registered}")
                if registered:
                    break

            # 防御性兜底（实测 2026-08-25）：有时直接调用返回 200 无 data、日历未登记，
            # 但按 970→当天 顺序逐个探测（每次带全套参数并验证）后，再重试当天即可登记。
            # 8/23（992）与 8/25（994）均验证此模式有效。机制可能是服务器对
            # signin/signin 存在顺序/状态依赖。
            if not registered and day_in_period is not None:
                logger.info("福利签到直接调用未登记，尝试顺序探测触发登记...")
                # 探测范围用 dayAwardId（970=dayInPeriod1 ... 当天 id），
                # 不是 dayInPeriod 序号！range(970, dayInPeriod) 是空范围（bug 2026-08-26）。
                probe_end = day_award_id if day_award_id is not None else 970 + day_in_period - 1
                for probe in range(970, probe_end + 1):
                    probe_result = game_welfare_sign(token, pub_key, probe, period_id)
                    registered = _check_welfare_registered(token)
                    logger.info(f"探测 dayAwardId={probe}: code={probe_result.get('code')} "
                                f"todaySignin={registered}")
                    if registered:
                        logger.info(f"顺序探测触发登记成功于 dayAwardId={probe}")
                        break

            if registered:
                logs.append("福利签到成功！")
            else:
                logs.append(f"福利签到失败: {welfare_result.get('msg', '未知错误')} "
                            f"(接口返回 {welfare_result.get('code')} 但日历未登记，"
                            f"可能需要 App 手动补签/补签接口)")

    # Step 3: Daily community tasks (browse, like, share, reply)
    logger.info("开始执行每日任务...")
    task_logs = do_daily_tasks(token)
    logs.extend(task_logs)

    return success, logs
