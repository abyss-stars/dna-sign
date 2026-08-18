# dna-sign - 二重螺旋 皎皎角 自动签到

二重螺旋（Duet Night Abyss）皎皎角官方社区每日自动签到脚本。

支持通过 GitHub Actions 免费每日自动运行，自动完成：**社区签到 + 游戏福利签到 + 每日任务**（浏览 3 篇帖子、点赞 5 次、分享 1 篇、回复 5 次、签到）。

> ⚠️ **重要：必须使用 App（客户端）token，不要用网页 token。**
> 网页(H5) token 在服务端是无效/不同身份，用它签到会全部返回 **403**；只有 **App token + App devCode** 配合 App 安卓签名模式才能正常签到。本项目默认即按 Android App 模式运行。

---

## 原理简述

脚本会自动完成三件事：

1. **社区签到** `POST /user/signIn`（皎皎角 BBS 签到）
2. **游戏福利签到** `POST /encourage/signin/signin`（按签到日历领取当日奖励）
3. **每日任务**（浏览/点赞/分享/回复，见 `src/daily_tasks.py`）

所有需要签名的请求都使用与 App 一致的 **Android v1.4.0 签名算法**（30 位纯数字 SA + JavaRandom 种子 + fe() 洗牌 + MD5/XOR/RSA），并携带 `devCode`、`countrycode:CN`、`source:android` 等 App 特有的请求头。

---

## 使用方式 (GitHub Actions)

### 1. Fork / 创建自己的仓库

把本仓库代码上传到你的 GitHub 仓库。

### 2. 获取 App Token 与 devCode

需要从 **皎皎角手机客户端**（Android 模拟器）登录后提取，而不是浏览器。两种方式任选：

**方法 A：抓包 / 提取 App 数据（推荐，较准确）**

1. 在 Android 模拟器安装并登录 皎皎角 App（1.4.0）
2. 登录后从 App 数据目录（`adb root` 后可读）提取会话：
   - **token**：`/data/data/com.hero.dna/shared_prefs/user_data.xml` 中的登录会话值
   - **devCode**：`/data/data/com.hero.dna/shared_prefs/g_hu_sp.xml` 的 `dv_id` / `androidIdSysKey`（或 `spUtils.xml` 的 `im_init_data`）
3. 若想用抓包方式，可使用抓包工具（如 PCAPdroid）抓取 App 登录或请求头里的 `token` 与 `devCode`。注意 HTTPS 流量需配置证书解密才能看到明文。

**方法 B：已有 token 但不确定是哪个会话**

用下面的接口验证（脚本启动时会自动检测，若 token 无效会报 `身份验证失败`）：

```
POST https://dnabbs-api.yingxiong.com/user/haveSignInNew   body: gameId=268
```

- 返回 `code:200` + `haveSignIn:true` → token 有效（App 会话）
- 返回 `403 forbidden` 或 `220 用户身份校验失败` → token 不是 App 会话，需重新提取

### 3. 设置 GitHub Secrets

在仓库的 **Settings → Secrets and variables → Actions** 中配置：

| Secret | 说明 |
|--------|------|
| `DNA_TOKEN` | **必填** - **App** 登录 Token |
| `DNA_DEVICE_CODE` | **必填** - 与 token 配套的 App 设备码（devCode） |
| `SC3_SENDKEY` | 可选 - [Server酱³](https://sc3.ft07.com/) SendKey (手机推送通知) |
| `SC3_UID` | 可选 - Server酱³ UID |

在 Variables 中可设置:

| Variable | 说明 |
|----------|------|
| `EXIT_WHEN_FAIL` | 设为 `on` 使签到失败时 GitHub 发送邮件通知 |

> 设置了 `DNA_DEVICE_CODE` 后脚本自动切到 App 模式；也可通过环境变量 `DNA_SIGN_MODE=h5|app` 强制指定签名模式。

### 4. 启用 Actions

进入仓库的 Actions 页面，启用 GitHub Actions。

脚本会每天 UTC 00:00（北京时间 8:00）自动运行，由于 GitHub Actions 队列原因，每日运行时间可能有半小时左右的延后。

你也可以手动触发: Actions → Auto Sign → Run workflow。

---

## Token 稳定吗？（要不要反复登录）

**结论：只要不重复登录，token 就保持不变，可以长期使用。**

- token 是登录会话凭证，只有**重新登录 / 登出 / 被服务端强制下线**时才会刷新成新值。平时放着不动，GitHub Actions 可以一直用同一个 token。
- **不要反复登录**。每次重新登录都会换一个新 token，旧 token 立即失效，你就得去 GitHub Secrets 里重新填。
- 若 App 内重新登录过（或清数据/刷机/设备被风控下线），token 会变，务必同步更新 Secret 里的 `DNA_TOKEN`（最好连 `DNA_DEVICE_CODE` 一起更新）。

---

## 本地运行

```bash
pip install -r requirements.txt

# Windows (PowerShell)
$env:DNA_TOKEN="your_app_token"
$env:DNA_DEVICE_CODE="your_device_code"
python src/main.py

# Linux / macOS
export DNA_TOKEN="your_app_token"
export DNA_DEVICE_CODE="your_device_code"
python src/main.py
```

可选环境变量：

- `DNA_SIGN_MODE=h5|app`：强制签名模式（默认：设置了 `DNA_DEVICE_CODE` 则为 `app`）
- `EXIT_WHEN_FAIL=on`：失败时以非零码退出（供调度/CI 判断）

---

## 技术说明

本脚本通过逆向分析官方 [dna-api](https://www.npmjs.com/package/dna-api) npm 包 及 Android 客户端（`com.hero.dna`）实现。

### API 端点

| 端点 | 说明 | 是否需要签名 |
|------|------|------------|
| `POST /user/signIn` | 社区签到 | 是 |
| `POST /user/haveSignInNew` | 检查签到状态 | 是 |
| `POST /encourage/signin/show` | 签到日历 | 是 |
| `POST /encourage/signin/signin` | 游戏福利签到 | 是 |
| `POST /encourage/level/getTaskProcess` | 每日任务进度 | 是 |
| `POST /forum/like` | 点赞 | 是 |
| `POST /forum/comment/createComment` | 回复评论 | 是 |
| `POST /config/getRsaPublicKey` | 获取 RSA 公钥（启动时） | 否 |

### 签名算法

**H5 / Web 模式（`te()`）**

1. 生成 16 位随机 `rk` 和 30 位数字 SA（`Ce()` + `Le()` 洗牌）
2. 将 token 和原始 SA 加入请求参数后排序拼接
3. MD5 → MD5 位置混淆 → XOR 编码(rk) → 拼接 RSA 加密(rk)
4. 结果放入 `tn` 和 `sa` 请求头，`source:h5`

**App 模式（`re()`，默认）**

1. 用 `JavaRandom(int(time.time()*1000))` 生成 30 位纯数字 SA（`De()`），再经 `fe()` 洗牌（插入时间戳到 8/16/22 位）
2. 相同的 MD5/XOR/RSA 签名流程
3. 请求头带 `devCode`、`countrycode:CN`、`version:1.4.0`、`versioncode:10`、`source:android`、`lang:zh-Hans`，UA 为 `okhttp/3.10.0`

RSA 为 1024-bit / PKCS1v15，分块（117 字节）加密后 base64。

---

## 目录结构

```
.
├── .github/workflows/auto_sign.yaml   # GitHub Actions 每日定时
├── src/
│   ├── main.py                        # 入口，读取环境变量
│   ├── dna_sign.py                    # 签名算法（H5 + App 双模式）
│   ├── api.py                         # 签到 / 福利 / 日历 API
│   ├── daily_tasks.py                 # 每日任务执行
│   └── push/                          # 推送通知（Server酱）
└── requirements.txt
```

---

## 免责声明

本项目仅供学习研究，请勿用于商业用途。使用本脚本产生的任何后果由使用者自行承担。

## License

MIT
