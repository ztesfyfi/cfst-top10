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

## 历史文件

仓库中的 `install.sh`、`panel/` 为旧版实现，当前 Docker 应用不调用它们。过渡期先保留，不作为新版本部署入口。`k.json` 和 `l.json` 是原仓库已有的独立数据文件，本次开发未改动。

## 上游

测速引擎：[XIU2/CloudflareSpeedTest](https://github.com/XIU2/CloudflareSpeedTest)（当前镜像构建固定使用 v2.3.5，并校验对应架构压缩包哈希）。
