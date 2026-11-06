# CFST TOP10

CFST 优选 IP 管理系统，继续使用 CloudflareSpeedTest（CFST）作为底层测速引擎。新版本采用 Docker 化 Web 应用，Docker Compose 是唯一正式部署方式。

> **开发状态：Docker 第一阶段骨架已提交。** 当前已包含容器构建、非 root 运行、管理 Token、SQLite 持久化、内置 IP 库登记、TXT 来源上传/启停/删除及来源合并统计。测速执行、URL 来源、定时任务、结果管理、Gist/KV 发布仍在开发中，不能视为已交付功能。

## Docker Compose 部署（开发版）

要求：Docker Engine 和 Docker Compose Plugin。

```bash
git clone https://github.com/ztesfyfi/cfst-top10.git
cd cfst-top10
cp .env.example .env
```

编辑 `.env`，将 `CFST_ADMIN_TOKEN` 改成至少 32 位的随机密钥。可以使用：

```bash
openssl rand -hex 32
```

启动：

```bash
docker compose up -d --build
docker compose logs -f
```

默认访问地址：`http://127.0.0.1:8765`。默认只绑定本机回环地址，不建议直接暴露到公网。远程管理建议使用 SSH 隧道或可信反向代理。

停止容器但保留数据：

```bash
docker compose down
```

当前持久化数据存放在 Docker named volume `cfst_data`。不要使用 `docker compose down -v`，除非明确要删除数据卷。

## 当前实现

- Dockerfile：按目标架构下载官方 CFST v2.3.5 Linux amd64/arm64 压缩包，并校验 SHA-256。
- Compose：默认 bridge 网络、非 root 用户、只读根文件系统、临时目录、健康检查、日志轮转及持久化卷。
- 管理 API：Bearer Token 身份验证。
- 来源管理：项目自带 IP 库登记；用户 TXT 文件上传、校验、启用/停用、删除。
- 来源预览：统计各来源条目、无效条目、重复条目及合并后的 IPv4/IPv6 数量。
- CFST 执行器：手动启动/停止、互斥运行、日志与状态查询；IPv4/IPv6 分开测速。
- 结果处理：解析官方 CSV，筛选零丢包结果，按下载速度排序，使用原子替换保存 `ipv4.txt` / `ipv6.txt`；失败或空结果不覆盖旧文件。
- API 提供受 Token 保护的结果下载接口。
- 测试：IP/CIDR 规范化、无效行处理、跨来源去重、输入大小限制和 CFST CSV 解析。

## 已确认的产品方向

- 三种来源：项目自带 IP 库、用户 TXT、URL 远程来源；测速前合并、校验、去重。
- 自带 IP 库关闭测速时仍保留本地，不能被删除。
- IPv4/IPv6 独立测速和保存；支持 TOP N、零丢包过滤、下载速度排序。
- 容器内调度，不依赖宿主机 crontab。
- 发布路线为 GitHub Gist 与 Cloudflare Workers KV，两者独立运行；第一版不采用 R2。
- 结果文件为纯文本 `ipv4.txt`、`ipv6.txt`，每行一个 IP。
- 旧版 Bash 文件在迁移过渡期保留；Docker 版本完成验收后再退役旧部署路径。
- 不连接 VPS，不在本阶段部署 Cloudflare Worker 或配置 KV。

完整需求和架构约束见 [docs/PROJECT-PLAN.md](docs/PROJECT-PLAN.md)。


## 外部发布方式（开发中）

> Gist 和 Cloudflare KV 是两条独立的发布路线，可以单独启用，也可以同时启用。发布内容仅包含测速结果 TXT，不会上传 IP 来源库、来源 URL、管理配置或日志。
>
> **当前状态：** 以下内容用于说明目标部署和使用流程。Gist/KV 发布适配器及 Cloudflare Worker 尚未交付，面板中暂时不能完成实际发布。请勿把下面的示例地址当作已经上线的服务。

<details>
<summary>展开：GitHub Gist 发布方式</summary>

### 1. 创建 Gist

1. 登录 GitHub，打开 [创建 Gist](https://gist.github.com/)。
2. 新建两个文件：`ipv4.txt` 和 `ipv6.txt`。暂时没有测速结果时可以留空。
3. Gist 可选择 Secret 或 Public。Secret Gist 不等于私有仓库，获得链接的人仍可能访问，请勿存放敏感信息。
4. 创建后，从 Gist 页面 URL 中复制 Gist ID。例如：
   `https://gist.github.com/用户名/这里是GIST_ID`。

### 2. 创建 GitHub Token

1. 打开 [GitHub Personal Access Tokens](https://github.com/settings/personal-access-tokens)。
2. 创建专用于 CFST TOP10 的 Token。
3. 按 GitHub 当前权限模型授予访问 Gist 所需的权限；不要授予无关仓库权限。
4. Token 只在创建时妥善保存，之后填入 CFST TOP10 服务端的发布配置。不要写入公开仓库、前端代码或截图。

### 3. 在 CFST TOP10 中配置

Docker 版本完成发布功能后，在面板的「发布管理」中填写：

| 配置项 | 内容 |
|---|---|
| 发布方式 | GitHub Gist |
| Gist ID | 上一步复制的 ID |
| GitHub Token | 专用 Token |
| IPv4 文件名 | `ipv4.txt` |
| IPv6 文件名 | `ipv6.txt` |
| 启用状态 | 按需开启 |

保存后可单独发布 IPv4、IPv6，也可在测速完成后自动发布。发布失败时保留 Gist 上一次成功的文件，不影响本地测速结果。

### 4. 获取发布结果

成功发布后，Gist 中分别提供 IPv4 和 IPv6 的纯文本文件。最终访问链接将由面板显示，格式示意：

```text
https://gist.githubusercontent.com/<用户名>/<Gist_ID>/raw/ipv4.txt
https://gist.githubusercontent.com/<用户名>/<Gist_ID>/raw/ipv6.txt
```

以上为链接格式示意，实际链接以 Gist 页面生成的地址为准。

</details>

<details>
<summary>展开：Cloudflare Workers + KV 发布方式</summary>

### 1. 创建 KV Namespace

1. 登录 [Cloudflare Dashboard](https://dash.cloudflare.com/)。
2. 进入 Workers & Pages 的 KV 页面。
3. 创建专用 KV Namespace，例如 `CFST_RESULTS`。
4. 记录 Namespace，后续将它绑定到专用 Worker。

### 2. 部署独立 Worker

Cloudflare 发布端采用独立 Worker 项目，不把 Worker 源码或部署流程混入 CFST TOP10 主容器。

Worker 项目交付后，按其 README 部署到 Cloudflare Workers，并完成以下配置：

- 将 KV Namespace 绑定到 Worker。
- 设置专用上传密钥（Secret），用于验证 CFST TOP10 服务端的发布请求。
- 配置允许访问的文件名，仅允许写入 `ipv4.txt` 和 `ipv6.txt`。
- 启用 HTTPS；上传接口必须验证密钥，不能开放匿名写入。
- 公共读取接口只返回 TXT 内容，不暴露 KV 管理能力或上传密钥。

> Worker 项目、变量名称、绑定名称、上传 API 路径和实际部署命令，将以独立 Worker 仓库正式发布的 README 为准。当前尚未创建或部署该 Worker，因此这里不提供虚构的命令或接口地址。

### 3. 在 CFST TOP10 中配置

发布功能交付后，在面板的「发布管理」中填写：

| 配置项 | 内容 |
|---|---|
| 发布方式 | Cloudflare Workers KV |
| Worker 地址 | 已部署 Worker 的 HTTPS 地址 |
| 上传密钥 | Worker 配置的专用 Secret |
| IPv4 对象名 | `ipv4.txt` |
| IPv6 对象名 | `ipv6.txt` |
| 启用状态 | 按需开启 |

保存后可分别发布 IPv4、IPv6，也可设置测速成功后自动发布。Worker/KV 发布失败时，不覆盖远端旧结果，也不影响 Gist 路线和本地结果。

### 4. 获取发布结果

Worker 正式交付时将提供两个只读 HTTPS 地址，分别返回纯文本：

```text
https://<你的-worker-域名>/ipv4.txt
https://<你的-worker-域名>/ipv6.txt
```

具体路径以独立 Worker 项目的正式文档为准。公开读取地址不包含上传密钥。

</details>

<details>
<summary>展开：双发布、自动发布与安全说明</summary>

### 发布模式

| 模式 | 行为 |
|---|---|
| 仅 Gist | 只向 GitHub Gist 发布 |
| 仅 Cloudflare KV | 只向 Worker/KV 发布 |
| 双发布 | 两条路线分别执行，互不依赖 |

- IPv4、IPv6 分开生成、发布和记录状态。
- 支持手动发布，以及后续配置的测速完成后自动发布。
- 一条路线失败不阻断另一条路线；失败路线可以单独重试。
- 上传失败、结果为空或校验失败时，不用空文件覆盖远端已有结果。
- 外网读取已发布文件不依赖 VPS 在线；前提是对应 Gist 或 Worker/KV 服务正常。

### 文件格式

发布文件为普通 TXT，每行一个 IP 地址：

```text
192.0.2.10
192.0.2.20
```

IPv4 使用 `ipv4.txt`，IPv6 使用 `ipv6.txt`。不会生成 YAML、Base64 或代理订阅格式。

### 安全注意事项

- GitHub Token、Worker 上传密钥只保存在服务端，不发送到浏览器。
- 不要把 Token、Secret 或带密钥的配置提交到 GitHub。
- 日志不得输出 Token、Secret 或完整敏感请求头。
- Gist 与 KV 仅用于发布测速结果，不上传来源列表、URL 来源、管理配置和运行日志。
- Gist 的 Secret 属性不代表严格私有；需要控制访问范围时，应谨慎选择发布方式。

</details>

## 历史文件

仓库中的 `install.sh`、`panel/` 为旧版实现，当前 Docker 应用不调用它们。过渡期先保留，不作为新版本部署入口。`k.json` 和 `l.json` 是原仓库已有的独立数据文件，本次开发未改动。

## 上游

测速引擎：[XIU2/CloudflareSpeedTest](https://github.com/XIU2/CloudflareSpeedTest)（当前镜像构建固定使用 v2.3.5，并校验对应架构压缩包哈希）。
