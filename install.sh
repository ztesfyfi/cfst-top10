#!/usr/bin/env bash
set -Eeuo pipefail

REPO="ztesfyfi/cfst-top10"
BASE="$HOME/CFST"
BIN_DIR="$BASE/cfst_linux_amd64"
CONFIG="$BASE/config"
PUBLISHER="$BASE/run.sh"
MANAGER="$BASE/cfst-manager.sh"

say(){ printf '\n==> %s\n' "$*"; }
fail(){ printf '\n错误：%s\n' "$*" >&2; exit 1; }

[[ "$(uname -s)" == Linux ]] || fail "此脚本仅支持 Linux NAS/服务器。"

# 缺少依赖时，尽可能通过系统自带包管理器自动安装。
PKG_KIND=""
if command -v opkg >/dev/null 2>&1; then PKG_KIND=opkg
elif command -v apk >/dev/null 2>&1; then PKG_KIND=apk
elif command -v apt-get >/dev/null 2>&1; then PKG_KIND=apt
elif command -v dnf >/dev/null 2>&1; then PKG_KIND=dnf
elif command -v yum >/dev/null 2>&1; then PKG_KIND=yum
fi

pkg_install() {
  local package="$1"
  case "$PKG_KIND" in
    opkg) opkg install "$package" ;;
    apk) apk add "$package" ;;
    apt) DEBIAN_FRONTEND=noninteractive apt-get install -y "$package" ;;
    dnf) dnf install -y "$package" ;;
    yum) yum install -y "$package" ;;
    *) return 1 ;;
  esac
}

ensure_cmd() {
  local cmd="$1" package="$2"
  command -v "$cmd" >/dev/null 2>&1 && return 0
  [[ -n "$PKG_KIND" ]] || fail "缺少依赖 $cmd，且未检测到可用包管理器，无法自动安装。"
  say "检测到缺少依赖 $cmd，尝试自动安装软件包：$package"
  if [[ "$PKG_KIND" == opkg ]]; then opkg update || fail "opkg 更新软件源失败，无法安装 $package。"
  elif [[ "$PKG_KIND" == apt ]]; then apt-get update || fail "apt 更新软件源失败，无法安装 $package。"
  fi
  pkg_install "$package" || fail "自动安装 $package 失败。请检查软件源、网络和磁盘空间后重试。"
  command -v "$cmd" >/dev/null 2>&1 || fail "已尝试安装 $package，但仍找不到命令 $cmd。"
}

# 先确保脚本运行和下载所需工具可用；OpenWrt 优先使用轻量 Python 包。
ensure_cmd curl curl
ensure_cmd tar tar
if ! command -v python3 >/dev/null 2>&1; then
  if [[ "$PKG_KIND" == opkg ]]; then
    # OpenWrt 通常提供轻量 Python 包；若仓库不提供该包，明确报错并提示检查软件源。
    ensure_cmd python3 python3-light
  else
    ensure_cmd python3 python3
  fi
fi
if ! command -v crontab >/dev/null 2>&1; then
  case "$PKG_KIND" in
    opkg) ensure_cmd crontab cronie ;;
    apk) ensure_cmd crontab dcron ;;
    apt) ensure_cmd crontab cron ;;
    dnf|yum) ensure_cmd crontab cronie ;;
    *) fail "缺少 crontab，且无法自动安装定时任务组件。" ;;
  esac
fi
case "$(uname -m)" in
  x86_64|amd64) ASSET_RE='(linux_amd64|amd64).*\.tar\.gz$' ;;
  aarch64|arm64) ASSET_RE='(linux_arm64|arm64).*\.tar\.gz$' ;;
  *) fail "暂不支持 CPU 架构：$(uname -m)" ;;
esac

mkdir -p "$BASE" "$HOME/.ssh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

say "选择使用方式"
echo "1) 本地使用（不需要 VPS、域名或 SSH）"
echo "2) VPS 远程发布（需要自己的 VPS 和 Web 发布目录）"
read -r -p "请选择 [1/2，默认 1]: " MODE
MODE="${MODE:-1}"
[[ "$MODE" == 1 || "$MODE" == 2 ]] || fail "请选择 1 或 2。"

IP_COUNT_DEFAULT=10
read -r -p "每次保留多少个优选 IP [默认 10]: " IP_COUNT
IP_COUNT="${IP_COUNT:-$IP_COUNT_DEFAULT}"
[[ "$IP_COUNT" =~ ^[1-9][0-9]*$ ]] || fail "数量必须是正整数。"
(( IP_COUNT <= 100000 )) || fail "单次数量最多 100000。"

VPS_HOST="" VPS_PORT="" VPS_USER="" REMOTE_DIR="" PUBLIC_URL="" PUBLIC_DOMAIN="" PUBLISH_SLUG=""
if [[ "$MODE" == 2 ]]; then
  ensure_cmd ssh openssh-client
  ensure_cmd scp openssh-client
  ensure_cmd ssh-keygen openssh-client
  echo "请输入你自己的 VPS 参数，不会使用项目作者的服务器。"
  read -r -p "VPS 主机名或 IP: " VPS_HOST
  read -r -p "SSH 端口 [默认 22]: " VPS_PORT
  VPS_PORT="${VPS_PORT:-22}"
  read -r -p "SSH 登录用户名: " VPS_USER
  read -r -p "自定义域名（只填域名，例如 sub.example.com；没有可留空）: " PUBLIC_DOMAIN
  [[ -n "$VPS_HOST" && "$VPS_HOST" =~ ^[A-Za-z0-9.-]+$ ]] || fail "VPS 主机名/IP 格式不正确。"
  [[ "$VPS_PORT" =~ ^[0-9]+$ ]] && (( VPS_PORT >= 1 && VPS_PORT <= 65535 )) || fail "SSH 端口无效。"
  [[ "$VPS_USER" =~ ^[A-Za-z_][A-Za-z0-9_-]*$ ]] || fail "SSH 用户名格式不正确。"
  if [[ -n "$PUBLIC_DOMAIN" ]]; then
    PUBLIC_DOMAIN="${PUBLIC_DOMAIN#https://}"
    PUBLIC_DOMAIN="${PUBLIC_DOMAIN#http://}"
    PUBLIC_DOMAIN="${PUBLIC_DOMAIN%%/*}"
    [[ "$PUBLIC_DOMAIN" =~ ^([A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?\\.)*[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?$ ]] || fail "域名格式不正确，请只填写域名，不要带路径。"
    PUBLISH_SLUG="cfst-$(( (RANDOM << 15 | RANDOM) % 900000 + 100000 ))"
    REMOTE_DIR="/var/www/html/$PUBLISH_SLUG"
    PUBLIC_URL="https://$PUBLIC_DOMAIN/$PUBLISH_SLUG/ips.txt"
    echo "自动生成发布目录：$REMOTE_DIR"
    echo "自动生成完整公开 URL：$PUBLIC_URL"
    echo "注意：该 URL 适用于 Web 根目录为 /var/www/html 的常见配置；若你的 Nginx/Apache 使用其他根目录，需调整映射。"
  else
    PUBLISH_SLUG="cfst-$(( (RANDOM << 15 | RANDOM) % 900000 + 100000 ))"
    REMOTE_DIR="$HOME/CFST-REMOTE-$PUBLISH_SLUG"
    echo "未填写域名，将仅上传到 VPS 用户目录：$REMOTE_DIR"
  fi
fi

say "从 CloudflareSpeedTest 官方 GitHub 下载最新版本"
META="$(curl -fsSL --retry 3 https://api.github.com/repos/XIU2/CloudflareSpeedTest/releases/latest)" || fail "无法读取官方 Release。"
ASSET_URL="$(printf '%s' "$META" | python3 -c 'import json,re,sys; d=json.load(sys.stdin); p=re.compile(sys.argv[1],re.I); a=[x["browser_download_url"] for x in d.get("assets",[]) if p.search(x.get("name",""))]; print(a[0] if a else "")' "$ASSET_RE")"
[[ -n "$ASSET_URL" ]] || fail "官方 Release 中没有找到适合当前架构的 tar.gz 文件。"
curl -fL --retry 3 "$ASSET_URL" -o "$TMP/cfst.tar.gz"
mkdir -p "$TMP/unpack" "$BIN_DIR"
tar -xzf "$TMP/cfst.tar.gz" -C "$TMP/unpack"
BIN="$(find "$TMP/unpack" -type f \( -name CloudflareST -o -name cfst \) | head -n1 || true)"
[[ -n "$BIN" ]] || fail "压缩包中没有找到 CloudflareST 可执行文件。"
install -m 755 "$BIN" "$BIN_DIR/cfst"
if [[ ! -s "$BIN_DIR/ip.txt" ]]; then
  IP_LIST="$(find "$TMP/unpack" -type f -iname ip.txt | head -n1 || true)"
  [[ -z "$IP_LIST" ]] || install -m 644 "$IP_LIST" "$BIN_DIR/ip.txt"
fi
[[ -s "$BIN_DIR/ip.txt" ]] || fail "未找到 ip.txt。请检查官方 Release 包或手动将 IP 段文件放到 $BIN_DIR/ip.txt。"

KEY="$HOME/.ssh/cfst_publish"
if [[ "$MODE" == 2 && ! -s "$KEY" ]]; then
  say "生成专用 SSH 密钥（私钥只保存在本机）"
  ssh-keygen -t ed25519 -N '' -f "$KEY" -C 'cfst-ip-list-publisher'
fi
[[ "$MODE" != 2 ]] || chmod 600 "$KEY"

cat > "$CONFIG" <<EOF
MODE='$MODE'
IP_COUNT='$IP_COUNT'
VPS_HOST='$VPS_HOST'
VPS_PORT='$VPS_PORT'
VPS_USER='$VPS_USER'
REMOTE_DIR='$REMOTE_DIR'
PUBLIC_URL='$PUBLIC_URL'
PUBLIC_DOMAIN='$PUBLIC_DOMAIN'
PUBLISH_SLUG='$PUBLISH_SLUG'
EOF
chmod 600 "$CONFIG"

say "安装测速与结果处理脚本"
cat > "$PUBLISHER" <<'SH'
#!/usr/bin/env bash
set -Eeuo pipefail
BASE="$HOME/CFST"
BIN_DIR="$BASE/cfst_linux_amd64"
CONFIG="$BASE/config"
KEY="$HOME/.ssh/cfst_publish"
CSV="$BIN_DIR/result.csv"
OUT="$BASE/ips.txt"
TMP="$BASE/ips.txt.tmp"
LOCK="$BASE/.run.lock"
[[ -r "$CONFIG" ]] || { echo "配置文件不存在：$CONFIG" >&2; exit 1; }
# shellcheck disable=SC1090
source "$CONFIG"
mkdir "$LOCK" 2>/dev/null || { echo "任务正在运行，退出。"; exit 1; }
trap 'rmdir "$LOCK" 2>/dev/null || true; rm -f "$TMP"' EXIT
cd "$BIN_DIR"
echo "[$(date '+%F %T')] 开始测速"
./cfst > "$BASE/cfst-run.log" 2>&1 || { tail -20 "$BASE/cfst-run.log"; exit 1; }
[[ -s "$CSV" ]] || { echo "result.csv 不存在或为空；保留之前的结果。" >&2; exit 1; }
python3 - "$CSV" "$TMP" "$IP_COUNT" <<'PY'
import csv, ipaddress, sys
src, dst, limit = sys.argv[1], sys.argv[2], int(sys.argv[3])
rows = []
with open(src, encoding='utf-8-sig', newline='') as f:
    for r in csv.DictReader(f):
        try:
            ip = r.get('IP 地址', r.get('IP', '')).strip()
            ipaddress.ip_address(ip)
            loss = float(r.get('丢包率', r.get('丢包', '100')).strip().rstrip('%'))
            speed = float(r.get('下载速度(MB/s)', r.get('下载速度', '0')).strip())
            if loss == 0 and speed >= 0: rows.append((speed, ip))
        except (ValueError, AttributeError, TypeError): continue
rows.sort(key=lambda x: (-x[0], x[1]))
ips, seen = [], set()
for _, ip in rows:
    if ip not in seen:
        seen.add(ip); ips.append(ip)
    if len(ips) >= limit: break
if not ips: raise SystemExit('未找到零丢包 IP；保留之前的结果。请检查 CSV 列名和测速结果。')
with open(dst, 'w', encoding='ascii', newline='\n') as f: f.write('\n'.join(ips) + '\n')
print(f'筛选完成：{len(ips)} 个 IP（设置目标 {limit} 个）。')
PY
mv "$TMP" "$OUT"
echo "本地结果已保存：$OUT"
if [[ "$MODE" == 2 ]]; then
  ssh -i "$KEY" -p "$VPS_PORT" -o BatchMode=yes -o ConnectTimeout=10 "$VPS_USER@$VPS_HOST" "mkdir -p '$REMOTE_DIR'" || { echo "远端目录创建失败：请确认 SSH 公钥已授权，且登录用户有权限创建 $REMOTE_DIR" >&2; exit 1; }
  scp -i "$KEY" -P "$VPS_PORT" -o BatchMode=yes -o ConnectTimeout=10 "$OUT" "$VPS_USER@$VPS_HOST:$REMOTE_DIR/ips.txt"
  echo "远程上传成功：$VPS_HOST:$REMOTE_DIR/ips.txt"
  [[ -z "$PUBLIC_URL" ]] || echo "公开地址：$PUBLIC_URL"
fi
echo "[$(date '+%F %T')] 任务完成。"
SH
chmod 700 "$PUBLISHER"

cat > "$MANAGER" <<'SH'
#!/usr/bin/env bash
set -u
BASE="$HOME/CFST"
PUBLISHER="$BASE/run.sh"
while true; do
  echo
  echo '===== CFST 优选 IP 管理菜单 ====='
  echo '1) 立即测速并保存/发布'
  echo '2) 查看本地 IP 列表'
  echo '3) 修改每次保留的 IP 数量'
  echo '4) 查看最近测速日志'
  echo '5) 查看自动任务日志'
  echo '6) 查看定时任务'
  echo '0) 退出'
  read -r -p '请选择: ' c
  case "$c" in
    1) "$PUBLISHER" >> "$BASE/cron.log" 2>&1; rc=$?; echo "退出码=$rc"; read -r -p '回车继续...' _ ;;
    2) cat "$BASE/ips.txt" 2>/dev/null || echo '还没有结果，请先执行测速。'; read -r -p '回车继续...' _ ;;
    3)
      read -r -p '新的 IP 数量（正整数）: ' n
      if [[ "$n" =~ ^[1-9][0-9]*$ ]] && (( n <= 100000 )); then
        sed -i "s/^IP_COUNT=.*/IP_COUNT='$n'/" "$BASE/config"
        echo "已更新为 $n 个。"
      else echo '数量无效。'; fi
      read -r -p '回车继续...' _ ;;
    4) tail -30 "$BASE/cfst-run.log" 2>/dev/null || echo '暂无日志'; read -r -p '回车继续...' _ ;;
    5) tail -30 "$BASE/cron.log" 2>/dev/null || echo '暂无日志'; read -r -p '回车继续...' _ ;;
    6) crontab -l 2>/dev/null | grep -F "$PUBLISHER" || echo '未找到定时任务'; read -r -p '回车继续...' _ ;;
    0) exit 0 ;;
    *) echo '无效选项' ;;
  esac
done
SH
chmod 700 "$MANAGER"

say "设置每天凌晨 03:30 自动测速"
OLD_CRON="$(crontab -l 2>/dev/null || true)"
NEW_CRON="$(printf '%s\n' "$OLD_CRON" | grep -vF '# cfst-ip-list managed job' || true)"
printf '%s\n%s\n' "$NEW_CRON" "30 3 * * * $PUBLISHER >> $BASE/cron.log 2>&1 # cfst-ip-list managed job" | sed '/^[[:space:]]*$/d' | crontab -

say "安装完成"
echo "管理菜单：$MANAGER"
echo "立即测速：$PUBLISHER"
echo "本地结果：$BASE/ips.txt"
echo "自动任务日志：$BASE/cron.log"
if [[ "$MODE" == 2 ]]; then
  echo
  echo "远程模式：请将下面公钥添加到 VPS 登录用户的 ~/.ssh/authorized_keys："
  cat "$KEY.pub"
  echo
  echo "远端目录会在首次运行时自动创建；请先将显示的 SSH 公钥添加到 VPS 的 ~/.ssh/authorized_keys。"
  if [[ -n "$PUBLIC_URL" ]]; then
    echo "自动生成的公开 URL：$PUBLIC_URL"
    echo "请确认域名已解析到 VPS，且 Web 服务将 /$PUBLISH_SLUG/ 映射到 $REMOTE_DIR。"
  fi
fi
echo
echo "启动管理菜单：$MANAGER"
echo "现在执行一次测速：$PUBLISHER"
