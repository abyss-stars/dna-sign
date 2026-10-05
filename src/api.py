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

# ─── 长期 refreshToken（Secret: DNA_REFRESH_TOKEN）────────────────────────────
# access token 有效期约 14 天（2026-10-01 实测：9/16 签发 → 10/1 起全接口 220），
# 但设备 user_data.xml → login_data 里的 refreshToken 长期稳定不变。
# 存下来即可在 access token 到期时自动续期，免去人工更新 Secret。
REFRESH_TOKEN = os.environ.get('DNA_REFRESH_TOKEN', '').strip()

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


def refresh_access_token(token: Optional[str] = None) -> Optional[str]:
    """
    用长期 refreshToken 换取新的 access token。
    POST /user/refreshToken { gameId, refreshToken, source: android }（需签名）

    实测（2026-10-01，见经验总结 §14）：
      - access token 约 14 天到期，到期后所有身份接口统一返回 220；
      - 本接口**只校验 refreshToken 参数**，header 里的 access token 已过期也能成功；
      - refreshToken 长期稳定（设备 user_data.xml → login_data.refreshToken 一直未变），
        因此把它存进 Secret 即可实现"到期自动续期"。
      - 注意：续期后旧 access token 立即失效（同一账号同时只有一个有效 access token）。

    成功返回新 token；未配置 refreshToken 或被拒（如 222）返回 None。
    """
    refresh_token = REFRESH_TOKEN or (token or '')
    if not refresh_token:
        logger.warning("未配置 DNA_REFRESH_TOKEN，无法自动续期")
        return None

    url = urllib.parse.urljoin(BASE_URL, 'user/refreshToken')
    payload = {'gameId': GAME_ID, 'refreshToken': refresh_token, 'source': 'android'}

    pub_key = fetch_rsa_public_key(token or refresh_token)
    if not pub_key:
        logger.warning("续期失败：无法获取RSA公钥")
        return None

    headers, body = build_signed_request(pub_key, payload, token or refresh_token)
    try:
        resp = requests.post(url, headers=headers, data=body, timeout=15)
        result = resp.json()
    except Exception as e:
        logger.error(f"Error refreshing access token: {e}")
        return None

    data = result.get('data') if isinstance(result, dict) else None
    new_token = data.get('token') if isinstance(data, dict) else None
    if _code_of(result) == 200 and new_token:
        logger.info("access token 已用 DNA_REFRESH_TOKEN 自动续期")
        return new_token

    logger.warning(f"刷新 access token 被服务器拒绝: {result}")
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


# ─── 福利签到 payload 形态（实测顺序，勿调换）─────────────────────────────────
# 服务器对 encourage/signin/signin 的参数校验反复变更，以"领取后重查日历
# todaySignin==True"为唯一成功判据，形态按序尝试：
#   - 2026-08-29 起：带 signInType → 200 无 data（假成功，日历不登记）；
#     仅 signinType → 200 + data:{signinTimeNow, sendDayAward:True}（真登记）。
#   - 2026-08-23~26：需 gameId+signInType 齐备才登记（缺 signInType → 500）。
WELFARE_SIGN_FORMS = [
    ('signinType_only', {'signinType': 1}),
    ('signinType+signInType', {'signinType': 1, 'signInType': 1}),
]

# 福利签"200 无 data 假成功"时的重试间隔（秒），逐档执行。
# 实测 2026-09-05 / 2026-10-05：每日 08:00 时段接口返回瞬时假成功，稍后同一调用可真登记
# （10-05 的 08:00 整段假成功，11:12 手动调用即真登记），因此假成功后延时重试而非立即判失败。
# 只对主候选（今日 dayAwardId）重试；投机候选（dayInPeriod）不重试。
WELFARE_RETRY_DELAYS = (30, 120)


def game_welfare_sign(token: str, pub_key: str, day_award_id: int, period_id: int,
                      extra_payload: Optional[dict] = None) -> dict:
    """
    Daily game welfare (福利) sign-in.
    POST /encourage/signin/signin { gameId, dayAwardId, periodId, signinType:1[, signInType:1] }
    Needs signing (in sign_api_urls).

    ⚠️ payload 形态由 WELFARE_SIGN_FORMS 驱动（extra_payload 追加），
    成功判据永远是领取后重查日历 todaySignin==True（见 do_daily_signin）：
      - 2026-08-29 实测：signInType 变成"破坏参数"，带上反而 200 无 data 不登记；
        仅 signinType → 200 + data:{signinTimeNow, sendDayAward:True} 真登记。
      - 2026-08-23~26 实测：需要 gameId + signInType 齐备才登记。
    """
    url = urllib.parse.urljoin(BASE_URL, 'encourage/signin/signin')
    payload = {
        'gameId': GAME_ID,
        'dayAwardId': day_award_id,
        'periodId': period_id,
    }
    payload.update(extra_payload or {})
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


def _code_of(resp) -> Optional[int]:
    """Normalize a response 'code' (server sometimes returns str like '220') to int."""
    if not isinstance(resp, dict):
        return None
    try:
        return int(resp.get('code'))
    except (TypeError, ValueError):
        return None


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

    # 鉴权失败码：220 用户身份校验失败（实测 2026-09-01，token 失效/重新登录后旧 token 全作废，
    # 且服务端返回的是字符串 '220'）；101 身份验证失败；10000 签名/参数错误。
    #
    # 2026-10-01（§14）：access token 有效期约 14 天，到期后统一 220。此时若配置了长期
    # refreshToken（Secret DNA_REFRESH_TOKEN），先自动续期再用新 token 重查一次——
    # 这样"每两周断一次"就无需人工介入。10000 是签名/参数问题，续期无用，不在此列。
    auth_code = _code_of(status)
    if auth_code in (220, 101):
        new_token = refresh_access_token(token)
        if new_token:
            token = new_token
            status = check_signin_status(token)
            logger.info(f"续期后签到状态响应: {status}")
            data = status.get('data')
            bbs_already_signed = bool(
                isinstance(data, dict) and (data.get('haveSignIn') or data.get('haveRoleSignIn'))
            )
            auth_code = _code_of(status)

    has_auth_error = auth_code in (10000, 101, 220)
    if has_auth_error:
        if auth_code == 220:
            if REFRESH_TOKEN:
                msg = ("Token已失效且自动续期失败（220 用户身份校验失败）——请检查 GitHub Secrets 中的 "
                       "DNA_REFRESH_TOKEN 是否为最新 refreshToken，或在 App 重新登录后更新 DNA_TOKEN / DNA_DEVICE_CODE")
            else:
                msg = ("Token已失效（220 用户身份校验失败）——请在 App 重新登录获取新 Token，"
                       "并更新 GitHub Secrets 中的 DNA_TOKEN / DNA_DEVICE_CODE"
                       "（另建议配置 DNA_REFRESH_TOKEN 以自动续期）")
        elif auth_code == 101:
            msg = "身份验证失败 - Token可能已过期"
        else:
            msg = "参数错误，可能需要更新签名算法"
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
        # payload 形态（WELFARE_SIGN_FORMS）服务器端反复横跳：
        #   2026-08-29 起 signInType 反成破坏参数（200 无 data 假成功），仅 signinType 可登记。
        candidates = []
        if day_award_id is not None:
            candidates.append(('awardId', day_award_id))
        if day_in_period is not None and day_in_period != day_award_id:
            candidates.append(('dayInPeriod', day_in_period))

        if not candidates:
            logs.append("福利签到：无法解析今日奖励信息")
        else:
            registered = False
            auth_broken = False
            welfare_result = {}

            def _try_sign(param, period_id, extra_payload, strict=True):
                """
                单次调用福利签并立即验证是否登记。返回 'registered'/'fake'/'broken'/'skip'。

                strict=True （主候选＝今日 dayAwardId）：10000 视为签名/参数致命错误 → 'broken'。
                strict=False（投机候选＝dayInPeriod 序号）：该形态本就不一定被服务端接受，
                             10000 属预期 → 只放弃这个候选（'skip'），继续后续候选与顺序探测兜底。

                ⚠️ 2026-10-05 实测 bug：投机候选返回的 10000 曾把 auth_broken 置位，
                导致整段"顺序探测兜底"被跳过（今天的福利签就是这样丢的）。
                """
                nonlocal welfare_result
                welfare_result = game_welfare_sign(token, pub_key, param, period_id,
                                                   extra_payload=extra_payload)
                code = _code_of(welfare_result)
                logger.info(f"福利签到结果: {welfare_result}")
                # 220 = 用户身份校验失败（token 失效，致命）——任何候选都不再继续。
                if code == 220:
                    logger.warning("福利签到被服务器拒绝(code=220 用户身份校验失败)，Token 疑似失效")
                    return 'broken'
                if code in (101, 10000):
                    if strict:
                        logger.warning(f"福利签到被服务器拒绝(code={code})，停止尝试")
                        return 'broken'
                    logger.info(f"福利签到该参数形态不被接受(code={code})，跳过此候选")
                    return 'skip'
                if _check_welfare_registered(token):
                    return 'registered'
                return 'fake'

            for label, param in candidates:
                strict = (label == 'awardId')
                for form_label, extra_payload in WELFARE_SIGN_FORMS:
                    logger.info(f"执行福利签到 dayAwardId({label})={param} periodId={period_id} [{form_label}]...")
                    state = _try_sign(param, period_id, extra_payload, strict=strict)
                    # 'fake'：返回 200 无 data、日历未登记。这是服务器"瞬时假成功"——
                    # 实测 2026-09-05 与 2026-10-05 的 08:00 时段全假成功，稍后同一调用却真登记。
                    # 主候选按 WELFARE_RETRY_DELAYS 逐档延时重试；投机候选不浪费时间重试。
                    for delay in (WELFARE_RETRY_DELAYS if strict else ()):
                        if state != 'fake':
                            break
                        logger.info(f"福利签到返回 200 但日历未登记，{delay}s 后重试...")
                        time.sleep(delay)
                        state = _try_sign(param, period_id, extra_payload, strict=strict)
                    if state == 'registered':
                        registered = True
                        break
                    if state == 'broken':
                        auth_broken = True
                        break
                if registered or auth_broken:
                    break

            # 防御性兜底（实测 2026-08-25）：直接调用未登记时，按当天奖励顺序逐个探测
            # （每次带全套参数并验证），常能触发登记。机制可能是服务端对 signin/signin
            # 存在顺序/状态依赖。
            #
            # ⚠️ 2026-10-05 修正：探测范围必须取自日历里【当前周期】的 dayAward id
            # （period 20 是 1092..今天），不能像旧代码那样硬编码 range(970, 当天id)——
            # 那会把上一周期的 id 也打上百次（全是无效请求），而且它们常返回 10000/711，
            # 又会把探测本身打断。
            if not registered and not auth_broken and day_in_period is not None:
                probe_ids = sorted({
                    d.get('id') for d in (cal_data.get('dayAward') or [])
                    if d.get('periodId') == period_id
                    and isinstance(d.get('dayInPeriod'), int)
                    and d['dayInPeriod'] <= day_in_period
                    and d.get('id') is not None
                })
                if not probe_ids:
                    logger.info("福利签到兜底探测：日历里没有可用的当前周期奖励，跳过探测")
                else:
                    logger.info(f"福利签到直接调用未登记，按当前周期奖励顺序探测（{len(probe_ids)} 个）触发登记...")
                for probe in probe_ids:
                    for form_label, extra_payload in WELFARE_SIGN_FORMS:
                        probe_result = game_welfare_sign(token, pub_key, probe, period_id,
                                                         extra_payload=extra_payload)
                        probe_code = _code_of(probe_result)
                        # 探测阶段只有鉴权类错误才中止（220/101）；10000 等是单条奖励的
                        # 参数/状态反馈，不代表签名坏了，继续探测。
                        if probe_code == 220:
                            logger.warning("探测被服务器拒绝(code=220 用户身份校验失败)，Token 疑似失效，中止探测")
                            auth_broken = True
                            break
                        if probe_code == 101:
                            logger.warning("探测被服务器拒绝(code=101 鉴权失败)，中止探测")
                            auth_broken = True
                            break
                        registered = _check_welfare_registered(token)
                        logger.info(f"探测 dayAwardId={probe} [{form_label}]: code={probe_result.get('code')} "
                                    f"todaySignin={registered}")
                        if registered:
                            break
                    if registered or auth_broken:
                        if registered:
                            logger.info(f"顺序探测触发登记成功于 dayAwardId={probe}")
                        break

            if registered:
                logs.append("福利签到成功！")
            elif auth_broken:
                logs.append("福利签到失败: 服务器拒绝（见上方日志，220=Token失效 / 10000=签名或参数错误）")
            else:
                # 主候选与兜底探测都跑完仍未登记：绝大多数是 08:00 时段的"200 无 data 假成功"
                # （§12 / §15 实测：9-05、10-05 的 08:00 全假，10:00 后同一调用即真登记）。
                # 脚本幂等，稍后重跑一次即可补上——文案直接给出可执行动作，别让人去猜签名/token。
                logs.append(f"福利签到失败: 日历未登记（接口返回 {welfare_result.get('code')}，"
                            f"多为 08:00 时段性假成功）——稍后重跑一次 Auto Sign 即可补上（脚本幂等，已完成的会跳过）")

    # Step 3: Daily community tasks (browse, like, share, reply)
    logger.info("开始执行每日任务...")
    task_logs = do_daily_tasks(token)
    logs.extend(task_logs)

    return success, logs
