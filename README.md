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

生成一个 HTTPS 域名后，把它填入：

```env
LINGYIN_PUBLIC_BASE_URL=https://你的域名
```

访问以下地址检查服务：

```text
https://你的域名/healthz
```

看到 `"status":"ok"` 且 `"providers_configured":true` 即可。

## 接给 Claude

### Claude 网页版自定义 Connector

在 Claude 的自定义 Connector 页面填写：

```text
https://你的域名/mcp?token=你的访问密钥
```

查询参数是为不支持自定义请求头的个人 Connector 准备的。这个地址等同于密码，不要公开截图或分享。

### Claude Code

推荐用请求头，不把密钥放进 URL：

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
http://127.0.0.1:8080/mcp?token=你的访问密钥
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

- 必须设置 `LINGYIN_ACCESS_TOKEN`，未设置时 `/api` 与 `/mcp` 返回 503。
- 公网 URL 下载会拒绝本机、内网、保留地址和 URL 内嵌账号密码。
- 默认限制 25MB、60 秒、单任务并发。
- 转写文本被视为不可信数据，描述提示词明确禁止执行其中的指令。
- 上传音频默认 24 小时过期；被任务消费后立即删除。
- 任务结果默认保留 7 天。

若要多人共享或公开发布，应在前面增加正式 OAuth 2.1，而不是继续使用个人静态密钥。

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
