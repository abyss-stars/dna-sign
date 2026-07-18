"""
二重螺旋 皎皎角 每日任务模块

完成社区每日任务以获取经验/金币奖励：
1. 浏览3篇帖子 - viewCommunity / viewCount
2. 点赞5次 - forum/like
3. 分享1篇内容 - encourage/level/shareTask
4. 回复评论区5次 - forum/comment/createComment
"""

import json
import logging
import random
import urllib.parse
from typing import Optional

import requests

from dna_sign import build_unsigned_request

logger = logging.getLogger(__name__)

BASE_URL = 'https://dnabbs-api.yingxiong.com/'
GAME_ID = 268

# Reply content pool — neutral, varied messages
REPLY_MESSAGES = [
    "签到打卡",
    "水水水",
    "111",
    "每日一签",
    "支持一下",
    "好帖顶一个",
    "感谢分享",
    "路过看看",
    "加油加油",
    "来了来了",
]


def _request(url_path: str, data: dict = None, token: str = None) -> dict:
    """Helper: make a POST request with H5 headers."""
    url = urllib.parse.urljoin(BASE_URL, url_path)
    headers = build_unsigned_request(token)
    try:
        resp = requests.post(url, headers=headers, data=data, timeout=15)
        return resp.json()
    except Exception as e:
        logger.error(f"Request error {url_path}: {e}")
        return {'code': -1, 'msg': str(e)}


def get_task_process(token: str) -> dict:
    """
    Get current daily task progress.
    POST /encourage/level/getTaskProcess { gameId: 268 }
    """
    return _request('encourage/level/getTaskProcess', {'gameId': GAME_ID}, token)


def get_recommend_posts(token: str, size: int = 15) -> list:
    """
    Get recommended post list.
    POST /forum/recommend/list { gameId, recIndex, newIndex, size, history }
    """
    data = {
        'gameId': GAME_ID,
        'recIndex': 0,
        'newIndex': 0,
        'size': size,
        'history': '',
    }
    result = _request('forum/recommend/list', data, token)
    posts = result.get('data', {}).get('postVoList', [])
    logger.info(f"获取到 {len(posts)} 篇推荐帖子")
    return posts


def view_community(token: str) -> dict:
    """
    Browse community (counts toward browse task).
    POST /encourage/level/viewCommunity
    """
    return _request('encourage/level/viewCommunity', token=token)


def view_post(token: str, post_id: str) -> dict:
    """
    View a specific post (counts toward browse task).
    POST /forum/viewCount { gameId, postId }
    """
    return _request('forum/viewCount', {'gameId': GAME_ID, 'postId': post_id}, token)


def like_post(token: str, post: dict) -> dict:
    """
    Like a post.
    POST /forum/like
    """
    data = {
        'forumId': post.get('gameForumId', ''),
        'gameId': GAME_ID,
        'likeType': '1',
        'operateType': '1',
        'postCommentId': '',
        'postCommentReplyId': '',
        'postId': post.get('postId', ''),
        'postType': str(post.get('postType', '1')),
        'toUserId': post.get('userId', ''),
    }
    return _request('forum/like', data, token)


def share_task(token: str) -> dict:
    """
    Complete share task.
    POST /encourage/level/shareTask { gameId: 268 }
    """
    return _request('encourage/level/shareTask', {'gameId': GAME_ID}, token)


def create_comment(token: str, post: dict, content: str) -> dict:
    """
    Reply to a post.
    POST /forum/comment/createComment
    """
    content_json = json.dumps([{'content': content, 'contentType': '1'}], ensure_ascii=False)
    data = {
        'postId': post.get('postId', ''),
        'forumId': post.get('gameForumId', ''),
        'postType': '1',
        'content': content_json,
    }
    return _request('forum/comment/createComment', data, token)


def do_daily_tasks(token: str) -> list:
    """
    Execute all daily community tasks.

    1. Get task progress to determine what's already done
    2. Browse 3 posts (viewCommunity)
    3. Like 5 different posts
    4. Share 1 post
    5. Reply to 5 different posts

    Returns:
        logs (list[str]): summary messages for each action
    """
    logs = []

    # Step 0: Get current task progress
    logger.info("获取每日任务进度...")
    task_data = get_task_process(token)
    if task_data.get('code') != 200:
        logs.append("获取任务进度失败，跳过每日任务")
        return logs

    daily_tasks = task_data.get('data', {}).get('dailyTask', [])
    if not daily_tasks:
        logs.append("未找到每日任务数据")
        return logs

    # Parse task progress by remark keywords
    task_map = {}
    for t in daily_tasks:
        remark = t.get('remark', '')
        progress = t.get('process', 0)
        complete = t.get('completeTimes', 0)
        total = t.get('times', 1)
        task_map[remark] = {'progress': progress, 'complete': complete, 'total': total}

    for remark, info in task_map.items():
        logger.info(f"  任务 [{remark}]: {info['complete']}/{info['total']} (进度 {info['progress']})")

    def is_task_done(keyword: str) -> bool:
        """Check if the task matching keyword is already completed."""
        for remark, info in task_map.items():
            if keyword in remark:
                return info['complete'] >= info['total']
        return False

    def get_remaining_count(keyword: str) -> int:
        """Get remaining count for a task."""
        for remark, info in task_map.items():
            if keyword in remark:
                return max(0, info['total'] - info['complete'])
        return 0

    # Step 1: Browse community (浏览3篇帖子)
    if is_task_done('浏览'):
        logs.append("浏览任务：今日已完成")
    else:
        remaining = get_remaining_count('浏览')
        logger.info(f"执行浏览任务 (还需 {remaining} 次)...")
        # viewCommunity can be called multiple times
        success_count = 0
        for i in range(remaining):
            result = view_community(token)
            if result.get('code') == 200:
                success_count += 1
            else:
                logger.warning(f"浏览第 {i+1} 次失败: {result.get('msg')}")
        if success_count > 0:
            logs.append(f"浏览任务：完成 {success_count} 次浏览")
        else:
            logs.append("浏览任务失败")

    # Step 2: Get posts for interaction
    logger.info("获取推荐帖子列表...")
    posts = get_recommend_posts(token, size=20)
    if not posts:
        logs.append("无法获取推荐帖子，跳过点赞/回复任务")
        return logs

    # Step 3: Like posts (点赞5次)
    if is_task_done('点赞'):
        logs.append("点赞任务：今日已完成")
    else:
        remaining = get_remaining_count('点赞')
        logger.info(f"执行点赞任务 (还需 {remaining} 次)...")
        # Find unliked posts
        unliked = [p for p in posts if p.get('isLike') == 0]
        if len(unliked) < remaining:
            logger.warning(f"未点赞帖子不足 ({len(unliked)} < {remaining})，将点赞所有可用帖子")

        like_count = 0
        for post in unliked[:max(remaining, len(unliked))]:
            if like_count >= remaining:
                break
            result = like_post(token, post)
            if result.get('code') == 200:
                like_count += 1
            else:
                logger.warning(f"点赞失败 postId={post.get('postId')}: {result.get('msg')}")

        if like_count > 0:
            logs.append(f"点赞任务：完成 {like_count} 次点赞")
        else:
            logs.append("点赞任务失败")

    # Step 4: Share task (分享1篇内容)
    if is_task_done('分享'):
        logs.append("分享任务：今日已完成")
    else:
        logger.info("执行分享任务...")
        result = share_task(token)
        if result.get('code') == 200:
            logs.append("分享任务：完成 1 次分享")
        else:
            logs.append(f"分享任务失败: {result.get('msg', '')}")

    # Step 5: Reply to posts (回复评论区5次)
    if is_task_done('回复'):
        logs.append("回复任务：今日已完成")
    else:
        remaining = get_remaining_count('回复')
        logger.info(f"执行回复任务 (还需 {remaining} 次)...")

        reply_count = 0
        # Pick posts with existing comments to reply to (or just reply to any)
        reply_posts = posts[:max(remaining * 3, len(posts))]  # enough candidates
        available_messages = list(REPLY_MESSAGES)
        random.shuffle(available_messages)

        for post in reply_posts:
            if reply_count >= remaining:
                break
            msg = available_messages[reply_count % len(available_messages)]
            result = create_comment(token, post, msg)
            if result.get('code') == 200:
                reply_count += 1
            else:
                logger.warning(f"回复失败 postId={post.get('postId')}: {result.get('msg')}")

        if reply_count > 0:
            logs.append(f"回复任务：完成 {reply_count} 次回复")
        else:
            logs.append("回复任务失败")

    return logs
