# dna-sign - 二重螺旋 皎皎角 自动签到

二重螺旋（Duet Night Abyss）皎皎角官方社区每日自动签到脚本。

支持通过 GitHub Actions 免费每日自动运行。

## 使用方式 (GitHub Actions)

### 1. Fork / 创建自己的仓库

将本仓库的代码上传到你的 GitHub 仓库。

### 2. 获取 Token

浏览器打开 [皎皎角社区](https://dnabbs.yingxiong.com/) 并登录你的账号。

**方法一：从浏览器提取 Token**
1. 登录后按 F12 打开开发者工具或者右键页面后点击检查
2. 进入 应用 / 存储 → cookie → 点击`dnabbs.yingxiong.com`
3. 找到 `token`的键，复制其值

### 3. 设置 GitHub Secrets

在仓库的 **Settings → Secrets and variables → Actions** 中配置：

| Secret | 说明 |
|--------|------|
| `DNA_TOKEN` | **必填** - 从浏览器提取的登录 Token |
| `SC3_SENDKEY` | 可选 - [Server酱³](https://sc3.ft07.com/) SendKey (手机推送通知) |

在 Variables 中可设置:

| Variable | 说明 |
|----------|------|
| `EXIT_WHEN_FAIL` | 设为 `on` 使签到失败时 GitHub 发送邮件通知 |

### 4. 启用 Actions

进入仓库的 Actions 页面，启用 GitHub Actions。

脚本会每天 UTC 00:00（北京时间 8:00）自动运行,由于github action队列的原因，每日运行时间可能会有半小时左右的延后。

你也可以手动触发: Actions → Auto Sign → Run workflow。

## 本地运行

```bash
pip install -r requirements.txt
export DNA_TOKEN="your_token_here"
python src/main.py
```

## 技术说明

本脚本通过逆向分析 [dna-api](https://www.npmjs.com/package/dna-api) npm 包实现。

### API 端点

| 端点 | 说明 | 是否需要签名 |
|------|------|------------|
| `POST /user/signIn` | 社区签到 | 是 |
| `POST /encourage/signin/isHaveSignin` | 检查签到状态 | 否 |
| `POST /encourage/signin/show` | 签到日历 | 否 |
| `POST /encourage/signin/signin` | 游戏签到 | 是 |

### 签名算法 (H5 Mode)

1. 生成 16 位随机 rk 和 30 位 SA
2. 将 token 和 SA 加入请求参数后排序拼接
3. MD5 → MD5位置混淆 → XOR编码(rk) → 拼接 RSA加密(rk)
4. 结果放入 `tn` 和 `sa` 请求头

## 免责声明

本项目仅供学习研究，请勿用于商业用途。使用本脚本产生的任何后果由使用者自行承担。

## License

MIT
