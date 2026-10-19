# CFST Top 10 一键安装

## 一行安装

在 Linux NAS 的 SSH 终端执行：

```bash
bash <(curl -Ls https://raw.githubusercontent.com/ztesfyfi/cfst-top10/main/install.sh)
```

脚本会下载 CloudflareSpeedTest 官方 Release，设置 SSH/SCP 发布参数，生成测速/发布脚本，创建管理菜单，并设置每天本地时间 03:30 自动运行。

## 安装后怎么用

- 管理菜单：`~/CFST/cfst-manager.sh`
- 立即测速发布：`~/CFST/run-and-publish.sh`
- 本地 Top 10：`~/CFST/top10.txt`
- 自动任务日志：`~/CFST/cron.log`
- 最近测速日志：`~/CFST/cfst-run.log`

## VPS 首次授权

安装结束会显示 NAS 的 SSH 公钥。将整行公钥添加到 VPS 上传账户的 `~/.ssh/authorized_keys`。远端目录默认是 `/var/www/subconv/cfst`，必须已经存在，并且上传用户有写入权限。随后手动运行一次：

```bash
~/CFST/run-and-publish.sh
```

确认上传成功后，定时任务会每天运行。

## 默认设置

- VPS：`sha256.680675.xyz`
- SSH 端口：`12355`
- 上传用户：`cfstpub`
- 公开结果：`https://sha256.680675.xyz/cfst/top10.txt`

安装时可修改这些值。

## 安全说明

- 公共仓库只放安装代码，不包含私钥、密码或服务器令牌。
- SSH 私钥只保存在 NAS 的 `~/.ssh/cfst_publish`。
- 发布内容是测速筛选后的 IP 列表，请确认公开 URL 可公开访问。
- 安装脚本不会自动修改 VPS 的 SSH 配置、Nginx 或用户权限。

官方项目：[XIU2/CloudflareSpeedTest](https://github.com/XIU2/CloudflareSpeedTest)。
