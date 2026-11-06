# CFST TOP10

CFST 优选 IP 管理系统。项目计划从现有脚本形态升级为 Docker 化 Web 应用，继续使用 CloudflareSpeedTest（CFST）作为底层测速引擎。

> **当前状态：架构规划阶段。** Docker Compose 版本尚未交付。仓库中现存的旧版 Bash 安装脚本属于历史实现，不代表新版本部署方式；新版本不再提供 Bash 宿主机安装或运行方案。

## 正式部署方向

新版本确定采用 **Docker + Docker Compose**，作为唯一正式部署方式：

- 提供 Dockerfile、Compose 配置和环境变量示例。
- 目标支持 `linux/amd64`、`linux/arm64`，以实际 CI 构建和测试结果为准。
- Web 面板、后端 API、CFST 测速引擎、来源管理和定时任务在容器内运行。
- 使用 Docker Volume 或 bind mount 持久化配置、来源、缓存、测速结果、任务状态和日志。
- 定时任务由容器内调度器管理，不依赖宿主机 crontab。
- 容器默认非 root 运行，提供健康检查、日志轮转、备份恢复和升级/回滚流程。
- 默认使用普通 Docker 网络，不强制 host 网络或 privileged 权限。

## 规划功能

- Web 管理面板：仪表盘、IP 来源、测速、结果、日志、发布和定时任务。
- IP 来源：项目自带 IP 库、用户 TXT 文件、URL 来源；测速前统一校验、合并和去重。
- 自带 IP 库关闭测速时仍保留本地，不会被删除。
- 支持 IPv4、IPv6、TOP N、零丢包过滤、下载速度排序。
- 支持手动测速、停止测速、实时进度和定时任务。
- 测速结果分别生成 `ipv4.txt`、`ipv6.txt`，每行一个纯 IP，不生成代理订阅 YAML 或 Base64。
- 发布采用 GitHub Gist 与 Cloudflare Workers KV 两条独立路线，可单独启用或双发布；第一版不采用 R2。
- 发布失败不影响本地结果，也不破坏另一条路线已经成功发布的结果。

## 部署和迁移原则

- Docker Compose 是新版本唯一正式部署入口。
- 不再开发新的 Bash 宿主机安装器、宿主机管理菜单或宿主机 Cron 部署方式。
- 旧版 Bash 脚本仅在迁移过渡期保留；Docker 版本完成后，新版本文档和发布流程将以 Compose 为准。
- 规划提供旧版 `~/CFST` 配置、IP 来源、测速结果和旧定时任务迁移到 Docker 持久化目录的方案。
- 默认不删除旧数据；迁移前备份，迁移成功后再由用户确认停用旧任务。

## 项目升级方案

完整需求、架构约束、安全要求、Docker 运行规范及开发顺序见：

[docs/PROJECT-PLAN.md](docs/PROJECT-PLAN.md)

## 当前范围说明

当前提交仅记录项目规划和架构决策，不代表 Web 面板、Docker 镜像、Compose 部署或 Gist/KV 发布功能已经实现。Cloudflare Worker 独立项目及 Cloudflare 侧配置暂缓处理。

上游测速引擎：[XIU2/CloudflareSpeedTest](https://github.com/XIU2/CloudflareSpeedTest)。
