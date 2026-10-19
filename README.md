# CFST IP 优选一键安装

## 一行安装

在支持 Bash 的 Linux NAS SSH 终端执行：

```bash
bash <(curl -Ls https://raw.githubusercontent.com/ztesfyfi/cfst-top10/main/install.sh)
```

脚本会下载 CloudflareSpeedTest 官方 Release，设置测速与发布脚本、管理菜单和每天 03:30 的定时任务。

## 发布数量不限于 10 个

安装时会询问每次发布多少个 IP，默认 10 个；输入任意正整数，最多 10000 个。程序会筛选零丢包 IP，按下载速度从高到低排序后发布。实际可发布数量取决于测速结果。

## 安装后怎么用

- 管理菜单：`~/CFST/cfst-manager.sh`
- 立即测速并发布：`~/CFST/run-and-publish.sh`
- 本地结果：`~/CFST/ips.txt`
- 自动任务日志：`~/CFST/cron.log`
- 最近测速日志：`~/CFST/cfst-run.log`

## VPS 首次授权

安装结束会显示 NAS 的 SSH 公钥。需要将公钥添加到 VPS 上传账户的 `~/.ssh/authorized_keys`，并确保远端目录已存在且上传用户有写入权限。完成后手动执行：

```bash
~/CFST/run-and-publish.sh
```

## 默认设置

- VPS：`sha256.680675.xyz`
- SSH 端口：`12355`
- 上传用户：`cfstpub`
- 公开结果：`https://sha256.680675.xyz/cfst/ips.txt`

安装时可以修改连接参数、发布数量和公开地址。

## 安全与当前限制

- 公共仓库不存放私钥、密码或服务器令牌。
- SSH 私钥保存在 NAS 本机的 `~/.ssh/cfst_publish`。
- **此版本仍要求你已有可用的 VPS、上传账户、远端目录和可访问的公开 URL；它不会从零创建 VPS、SSH 用户、目录权限或 Nginx/HTTPS 配置。** 如果目标是任何人从全新环境开始部署，这些 VPS 端初始化步骤还需要补齐。

官方项目：[XIU2/CloudflareSpeedTest](https://github.com/XIU2/CloudflareSpeedTest)。
