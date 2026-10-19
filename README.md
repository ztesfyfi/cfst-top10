# CFST 优选 IP 一键安装

## 一行安装

在支持 Bash 的 Linux NAS 或 Linux 服务器终端执行：

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/ztesfyfi/cfst-top10/main/install.sh)
```

安装程序会引导你选择使用方式。不会预设项目作者的 VPS、域名、端口、用户名或公开地址。

## 两种使用模式

### 1. 本地使用（不需要 VPS）

选择“本地使用”即可。程序会下载 CFST、建立运行脚本和管理菜单，优选结果保存在：

- 结果文件：`~/CFST/ips.txt`
- 最近测速日志：`~/CFST/cfst-run.log`
- 定时任务日志：`~/CFST/cron.log`

无需配置 SSH、域名、Nginx 或 HTTPS。

### 2. VPS 远程发布（可选）

选择“VPS 远程发布”后，按提示填写自己的：

- VPS 主机名或 IP
- SSH 端口和登录用户名
- VPS 上已经创建且允许该用户写入的目录
- 可选的结果公开 URL

安装程序会生成专用 SSH 密钥，并显示公钥。将公钥添加到 VPS 对应登录用户的 `~/.ssh/authorized_keys` 后，脚本即可通过 SCP 上传 `ips.txt`。

如果希望通过网页访问结果，需要自行准备 Web 服务，并将公开 URL 指向上传后的文件。安装程序不会替你购买 VPS/域名，也不会自动创建云服务器或配置未知系统上的 Nginx/HTTPS。

## 优选数量不限制为 10 个

安装时输入想保留的 IP 数量，默认 10 个，允许输入 1 到 100000 的正整数。程序筛选零丢包地址并按下载速度从高到低排序；实际结果数量取决于测速结果。

之后也可在管理菜单中修改数量。

## 安装后怎么用

启动管理菜单：

```bash
~/CFST/cfst-manager.sh
```

菜单支持：

1. 立即测速并保存/发布
2. 查看本地 IP 列表
3. 修改每次保留的 IP 数量
4. 查看最近测速日志
5. 查看自动任务日志
6. 查看定时任务

安装程序会设置每天凌晨 03:30 自动测速。运行时间可在系统 crontab 中自行调整。

## 注意事项

- 支持 Linux x86_64 和 ARM64（aarch64）。
- 需要 Bash、curl、tar、Python 3 和 crontab；远程模式还需要 SSH/SCP。
- 不要把 SSH 私钥上传到 GitHub。私钥仅保存在运行安装程序的本机。
- 本项目只负责在本机运行 CFST、筛选结果及按需上传；IP 的连通性和速度受网络环境影响。

上游项目：[XIU2/CloudflareSpeedTest](https://github.com/XIU2/CloudflareSpeedTest)。
