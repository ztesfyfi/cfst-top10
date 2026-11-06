# CFST TOP10 Cloudflare Worker

这是 CFST TOP10 的独立 Cloudflare Workers + KV 发布端。它只保存和公开读取测速结果 TXT，不接触来源库、管理配置或日志。

## 功能

- 公开读取 `GET /ipv4.txt` 和 `GET /ipv6.txt`。
- 仅允许持有上传密钥的主应用通过 `PUT` 更新结果。
- 只接受固定文件名，最大 2 MiB，拒绝空内容和格式异常内容。
- KV Namespace 使用绑定 `CFST_RESULTS`。
- 上传密钥通过 Worker Secret `CFST_UPLOAD_TOKEN` 设置，不写入代码或 wrangler 配置。

## 部署

1. 在 Cloudflare Dashboard 创建 KV Namespace。
2. 将 Namespace ID 填入本目录 `wrangler.toml` 的 `id`。
3. 安装 Wrangler 并登录：

   ```bash
   npm install -g wrangler
   npx wrangler login
   ```

4. 在本目录设置上传密钥：

   ```bash
   npx wrangler secret put CFST_UPLOAD_TOKEN
   ```

   输入一段至少 32 字符的随机密钥。主 Docker 应用与 Worker 必须使用相同密钥。

5. 部署：

   ```bash
   npx wrangler deploy
   ```

## Docker 主应用配置

在主项目 `.env` 中设置：

```dotenv
CFST_CF_WORKER_URL=https://你的-worker-域名
CFST_CF_WORKER_TOKEN=与 Worker Secret 完全相同的密钥
```

重新创建容器：

```bash
docker compose up -d
```

主应用将向 `PUT /ipv4.txt`、`PUT /ipv6.txt` 发布；外部可通过以下地址读取：

- `https://你的-worker-域名/ipv4.txt`
- `https://你的-worker-域名/ipv6.txt`

## 安全说明

- 不要把 `CFST_UPLOAD_TOKEN` 提交到 Git。
- GET 是公开只读接口；知道 URL 的任何人都可以读取结果。
- PUT 必须携带 Bearer Token；其他路径、文件名和方法均拒绝。
- 建议在 Cloudflare Dashboard 对 Worker 配置合理的请求速率限制。
