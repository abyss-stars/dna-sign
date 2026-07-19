"""Server酱³ push notification."""

import logging
import os

import requests

logger = logging.getLogger(__name__)


def push_serverchan3(logs: list[str]):
    sendkey = os.environ.get('SC3_SENDKEY')
    uid = os.environ.get('SC3_UID')
    if not sendkey:
        logger.info("SC3_SENDKEY not set, skipping ServerChan push")
        return

    title = '二重螺旋签到'
    content = '\n'.join(logs) if logs else '无日志'

    url = f'https://sctapi.ftqq.com/{sendkey}.send'
    try:
        resp = requests.post(url, json={
            'title': title,
            'desp': content,
        }, timeout=10)
        data = resp.json()
        if data.get('code') == 0:
            logger.info("ServerChan push success")
        else:
            logger.warning(f"ServerChan push failed: {data}")
    except Exception as e:
        logger.error(f"ServerChan push error: {e}")
