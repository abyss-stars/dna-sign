"""
二重螺旋 (Duet Night Abyss) 自动签到脚本

在 GitHub Actions 上每日定时运行，自动签到皎皎角社区。
"""

import logging
import os
import sys
import time

from api import do_daily_signin
from push import push

logger = logging.getLogger(__name__)


def setup_logger():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
        ]
    )


def main():
    setup_logger()

    print('二重螺旋 皎皎角 自动签到')
    print('项目地址: https://github.com/your-repo/dna-sign')

    token = os.environ.get('DNA_TOKEN')
    if not token:
        logging.error('DNA_TOKEN 环境变量未设置！')
        print('错误: 请在 GitHub Secrets 中设置 DNA_TOKEN')
        sys.exit(1)

    exit_when_fail = os.environ.get('EXIT_WHEN_FAIL', '').lower() == 'on'

    logging.info('========== 开始签到 ==========')
    start_time = time.time()

    success, logs = do_daily_signin(token)

    # Push notification
    push(logs)

    elapsed = (time.time() - start_time) * 1000
    logging.info(f'签到完成，耗时 {elapsed:.0f} ms')
    logging.info('========== 结束 ==========')

    if exit_when_fail and not success:
        logging.error('签到失败，退出码 1')
        sys.exit(1)


if __name__ == '__main__':
    main()
