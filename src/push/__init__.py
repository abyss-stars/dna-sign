"""Push notification dispatcher."""
import logging
import os

logger = logging.getLogger(__name__)

# Try to import available push modules
try:
    from .serverchan3 import push_serverchan3
except ImportError:
    push_serverchan3 = None

__available_pusher = {}


def init_pushers():
    if push_serverchan3:
        __available_pusher['serverchan3'] = push_serverchan3


def push(all_logs: list[str]):
    init_pushers()
    if not all_logs:
        all_logs = ['签到完成']

    logger.info("开始推送结果")
    for name, func in __available_pusher.items():
        try:
            func(all_logs)
        except Exception as e:
            logger.error(f"[Push] {name} error: {e}")
    logger.info("推送结束")
