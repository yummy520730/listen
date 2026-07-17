# 聆音 LingYin Server

> 描述一落，物就没了。所以要给形状，不给标签。

聆音把一段语音拆成转写、100ms 声学轨迹、时间对齐事件和个人基线差异，再把结果交给 Claude 或可选的描述模型。它描述声音如何发生，不用“悲伤、焦虑、撒谎”等标签替说话者下结论。

这是根据两页设计截图重新实现的独立项目，不是失踪原仓库的代码副本。

## 它能做什么

- 使用 ElevenLabs Scribe 或任意 OpenAI 兼容 ASR 接口转写语音。
- 每 100ms 提取音高、能量、频谱亮度与发声边缘。
- 将停顿与明显变化映射到时间区间。
- 用 3–8 条日常录音建立个人中位数与 MAD 基线。
- 通过远程 Streamable HTTP MCP 接给 Claude。
- 内置 OAuth 2.1、PKCE、动态客户端注册与令牌刷新。
- 提供手机可用的上传和基线校准页面。
- 使用 SQLite 后台任务队列，避免长分析阻塞 MCP 请求。
- 可选服务器端 LLM；不配置时由调用工具的 Claude 完成最后的文字描述。
- 音频处理结束即删除，结果按配置保留有限天数。

## 数据流

```text
音频上传 / 公网音频 URL
          │
          ├── ASR API：转写与可选时间戳
          │
          └── 本机：ffmpeg 标准化 + librosa 声学轨迹
                              │
                       时间对齐与个人基线
                              │
                 Claude 或可选描述模型写成听感
```

音频本身只发送给你配置的 ASR。描述模型只会收到转写、声学统计和时间事件，不会收到原始音频。

## 为什么云端不能直接使用本地路径

截图里的 `hear("C:\\声音.wav")` 适用于同一台电脑上的 stdio MCP。服务器无法读取手机、Claude 或电脑上的本地路径。因此云端版支持两种安全输入：

1. 在聆音首页上传，得到 `upload_id`，再把编号发给 Claude。
2. 让 Claude 提交可公开下载的直链 `audio_url`。

不要把 Claude 附件的临时本地路径当成服务器路径。

## Zeabur 部署

### 1. 上传代码

把整个目录推送到一个 Git 仓库，在 Zeabur 里新建项目并从该仓库部署。项目根目录已经包含 `Dockerfile`，不需要填写启动命令。

### 2. 挂载数据卷

给服务添加一个持久卷，挂载到：

```text
/data
```

任务数据库与个人基线保存在这里。当前实现应只运行 **1 个副本**。

### 3. 添加环境变量

使用 ElevenLabs 时，最少需要：

```env
LINGYIN_ACCESS_TOKEN=一段足够长的随机密钥
LINGYIN_MCP_AUTH_MODE=oauth
LINGYIN_PUBLIC_BASE_URL=https://你的Zeabur域名
ASR_PROVIDER=elevenlabs
ASR_BASE_URL=https://api.elevenlabs.io/v1
ASR_API_KEY=你的ElevenLabs密钥
ASR_MODEL=scribe_v2
ASR_LANGUAGE_CODE=zh
LINGYIN_DATA_DIR=/data
```

`ASR_API_KEY` 在 ElevenLabs 控制台的 API Keys 页面创建。它等同于密码，只放在 Zeabur 的环境变量中，不要写进 GitHub，也不要发给 Claude。

如果改用 OpenAI 兼容转写接口，则设置：

```env
ASR_PROVIDER=openai
ASR_BASE_URL=https://你的兼容接口/v1
ASR_API_KEY=你的ASR密钥
ASR_MODEL=你的转写模型名
ASR_LANGUAGE_CODE=
```

生成随机密钥：

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

服务器端描述模型是可选项：

```env
LLM_BASE_URL=https://你的兼容接口/v1
LLM_API_KEY=
LLM_MODEL=你的模型名
```

`LLM_API_KEY` 留空时，聆音仍会返回完整转写和声学观察，连接它的 Claude 会负责写最终听感。这样最适合“项目本来就是接给 Claude”的使用方式，也少调用一次模型 API。

完整选项见 [`.env.example`](.env.example)。Zeabur 会自动注入 `PORT`，通常不用手动设置。

### 4. 资源和域名

建议初始限制：

- CPU：`0.5` 核
- 内存：`768 MiB`
- 副本：`1`

生成一个 HTTPS 域名后，把它填入。OAuth 发现和回调依赖这个完整地址，不能省略 `https://`：

```env
LINGYIN_PUBLIC_BASE_URL=https://你的域名
```

访问以下地址检查服务：

```text
https://你的域名/healthz
```

看到 `"status":"ok"`、`"providers_configured":true`、`"oauth_configured":true` 和 `"asr_provider":"elevenlabs"` 即可。

## 接给 Claude

### Claude 网页版自定义 Connector

在 Claude 的自定义 Connector 页面填写名称 `聆音 LingYin`，服务器 URL 填：

```text
https://你的域名/mcp
```

OAuth Client ID 和 OAuth Client Secret 留空。添加后点击 **Connect**，Claude 会自动注册客户端并打开聆音登录页；输入 `LINGYIN_ACCESS_TOKEN` 后允许连接。密码只提交给聆音，不放进 Connector URL，也不会发送给 Claude。

如果点“允许连接”后浏览器没有成功返回 Claude，可以再次提交；服务会在短时间内复用同一个回调。重新打开登录页时也会出现“继续回到 Claude”按钮，不会因第一次跳转丢失而立即判定过期。

如果 Claude 的 Connector 测试版无法完成 OAuth，可临时把 Zeabur 变量改成：

```env
LINGYIN_MCP_AUTH_MODE=none
```

重新部署后，删除 Claude 中原来的 Connector，再用同一个 `/mcp` URL 新建；此时 Client ID 和 Secret 都留空，也不再出现登录页。确认连接后可以把变量改回 `oauth`。`none` 会使公网中的任何人都能调用 MCP 工具并消耗 ASR 额度，只建议短时间排障；浏览器 `/api` 仍由 `LINGYIN_ACCESS_TOKEN` 保护。

### Claude Code

可以直接使用 OAuth：

```bash
claude mcp add --transport http lingyin https://你的域名/mcp
```

也可以为自己的 Claude Code 使用静态请求头：

```bash
claude mcp add --transport http lingyin https://你的域名/mcp \
  --header "Authorization: Bearer 你的访问密钥"
```

远程 HTTP 是 Claude Code 推荐的云端 MCP 连接方式；本项目 MCP 端点为 `/mcp`。

### 第一次使用

1. 打开 `https://你的域名/`。
2. 输入访问密钥。
3. 在“建立个人基线”中上传 3–8 条自然、平常状态的语音。
4. 选择新语音，点击“只上传，交给 Claude 听”。
5. 把页面生成的这句话发给 Claude：

```text
请调用聆音听一下 upload_id 这里换成编号
```

Claude 会依次调用：

1. `lingyin_submit`
2. `lingyin_wait`（尚未完成时可再次调用）
3. 必要时 `lingyin_result`

如果已经有音频直链，也可以直接让 Claude 用 `audio_url` 提交。

## MCP 工具

| 工具 | 用途 |
|---|---|
| `lingyin_submit` | 用 `upload_id` 或公网 `audio_url` 提交任务 |
| `lingyin_wait` | 最多等待 50 秒并返回状态或结果 |
| `lingyin_result` | 查询任务状态或读取已完成结果 |
| `lingyin_info` | 查看限制、上传页、ASR 与个人基线状态 |

## 本地运行

需要 Python 3.11+ 和 ffmpeg：

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e .
cp .env.example .env
set -a; . ./.env; set +a
python -m lingyin_server
```

Windows PowerShell 可逐项设置环境变量，或由自己的进程管理工具读取 `.env`。

MCP Inspector：

```bash
npx -y @modelcontextprotocol/inspector
```

连接：

```text
http://127.0.0.1:8080/mcp
```

## HTTP 接口

所有 `/api/*` 接口都接受以下任一验证方式：

```text
Authorization: Bearer <token>
X-API-Key: <token>
?token=<token>
```

常用接口：

- `POST /api/upload`：multipart 字段 `audio`，只上传并返回编号。
- `POST /api/analyze`：multipart 字段 `audio`、可选 `context`，上传并提交分析。
- `GET /api/jobs/{job_id}`：查询任务。
- `POST /api/calibrate`：3–8 个同名 multipart 字段 `audio`。
- `GET /api/baseline`：检查个人基线。

## 安全边界

- 必须设置 `LINGYIN_ACCESS_TOKEN`；它始终保护浏览器 `/api`，在默认 `oauth` 模式下也作为 OAuth 登录密码。
- `/mcp` 默认使用 OAuth 2.1 Authorization Code + PKCE；OAuth 客户端、访问令牌和刷新令牌持久化在 `/data`。
- `LINGYIN_MCP_AUTH_MODE=none` 仅用于临时兼容性排障，会公开 MCP 工具并允许第三方消耗 ASR 额度。
- 动态注册只接受 Claude 官方回调地址和本机回环地址，拒绝任意第三方跳转域名。
- 公网 URL 下载会拒绝本机、内网、保留地址和 URL 内嵌账号密码。
- 默认限制 25MB、60 秒、单任务并发。
- 转写文本被视为不可信数据，描述提示词明确禁止执行其中的指令。
- 上传音频默认 24 小时过期；被任务消费后立即删除。
- 任务结果默认保留 7 天。

当前 OAuth 是单所有者模式：所有获准连接都属于同一个 `LINGYIN_ACCESS_TOKEN`。若要多人共享，应接入具有独立账号与撤权管理的身份提供商。

## 验证

```bash
pip install -e ".[test]"
pytest
```

项目使用官方 `mcp` Python SDK 的 Streamable HTTP 传输；生产部署采用无状态 MCP 会话和 JSON 响应。协议层参考：

- <https://py.sdk.modelcontextprotocol.io/server/>
- <https://code.claude.com/docs/en/mcp>

## License

MIT
