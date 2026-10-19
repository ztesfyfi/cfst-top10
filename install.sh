#!/usr/bin/env bash
set -Eeuo pipefail

REPO="ztesfyfi/cfst-top10"
BASE="$HOME/CFST"
BIN_DIR="$BASE/cfst_linux_amd64"
KEY="$HOME/.ssh/cfst_publish"
CONFIG="$BASE/publish.conf"
PUBLISHER="$BASE/run-and-publish.sh"
MANAGER="$BASE/cfst-manager.sh"
URL_DEFAULT="https://sha256.680675.xyz/cfst/top10.txt"
REMOTE_DIR="/var/www/subconv/cfst"

say(){ printf '\n==> %s\n' "$*"; }
fail(){ printf '\nERROR: %s\n' "$*" >&2; exit 1; }
for cmd in curl tar python3 ssh scp ssh-keygen crontab; do
  command -v "$cmd" >/dev/null 2>&1 || fail "缺少依赖：$cmd。请先在 NAS 安装它。"
done
[[ "$(uname -s)" == Linux ]] || fail "此脚本只支持 Linux NAS。"
ARCH="$(uname -m)"
case "$ARCH" in
  x86_64|amd64) ASSET_RE='(linux_amd64|amd64).*\.tar\.gz$' ;;
  aarch64|arm64) ASSET_RE='(linux_arm64|arm64).*\.tar\.gz$' ;;
  *) fail "暂不支持 CPU 架构：$ARCH" ;;
esac

mkdir -p "$BASE" "$HOME/.ssh"
chmod 700 "$HOME/.ssh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

say "从 CloudflareSpeedTest 官方 GitHub 获取最新版本"
META="$(curl -fsSL --retry 3 https://api.github.com/repos/XIU2/CloudflareSpeedTest/releases/latest)" || fail "无法读取官方 Release。"
ASSET_URL="$(printf '%s' "$META" | python3 -c 'import json,re,sys; d=json.load(sys.stdin); p=re.compile(sys.argv[1],re.I); a=[x["browser_download_url"] for x in d.get("assets",[]) if p.search(x.get("name",""))]; print(a[0] if a else "")' "$ASSET_RE")"
[[ -n "$ASSET_URL" ]] || fail "官方 Release 中没有找到适合 $ARCH 的 tar.gz 文件。"
curl -fL --retry 3 "$ASSET_URL" -o "$TMP/cfst.tar.gz"
mkdir -p "$TMP/unpack" "$BIN_DIR"
tar -xzf "$TMP/cfst.tar.gz" -C "$TMP/unpack"
BIN="$(find "$TMP/unpack" -type f \( -name CloudflareST -o -name cfst \) | head -n1 || true)"
[[ -n "$BIN" ]] || fail "压缩包中没有找到 CloudflareST/cfst 可执行文件。"
install -m 755 "$BIN" "$BIN_DIR/cfst"
# Preserve existing files; install the official IP list when one is not already present.
if [[ ! -s "$BIN_DIR/ip.txt" ]]; then
  IP_LIST="$(find "$TMP/unpack" -type f -iname 'ip.txt' | head -n1 || true)"
  if [[ -n "$IP_LIST" ]]; then install -m 644 "$IP_LIST" "$BIN_DIR/ip.txt"; fi
fi
[[ -s "$BIN_DIR/ip.txt" ]] || fail "官方压缩包未提供 ip.txt，且 $BIN_DIR/ip.txt 不存在。请检查官方 Release 包。"

say "设置 VPS 上传参数"
read -r -p "VPS 主机名 [sha256.680675.xyz]: " VPS_HOST
VPS_HOST="${VPS_HOST:-sha256.680675.xyz}"
read -r -p "SSH 端口 [12355]: " VPS_PORT
VPS_PORT="${VPS_PORT:-12355}"
read -r -p "上传用户 [cfstpub]: " VPS_USER
VPS_USER="${VPS_USER:-cfstpub}"
read -r -p "远端目录 [$REMOTE_DIR]: " INPUT_REMOTE
REMOTE_DIR="${INPUT_REMOTE:-$REMOTE_DIR}"
read -r -p "公开 TXT 地址 [$URL_DEFAULT]: " PUBLIC_URL
PUBLIC_URL="${PUBLIC_URL:-$URL_DEFAULT}"
[[ "$VPS_PORT" =~ ^[0-9]+$ ]] || fail "SSH 端口必须是数字。"
[[ "$VPS_HOST" =~ ^[A-Za-z0-9.-]+$ ]] || fail "主机名格式不正确。"
[[ "$VPS_USER" =~ ^[A-Za-z_][A-Za-z0-9_-]*$ ]] || fail "上传用户名格式不正确。"
[[ "$REMOTE_DIR" =~ ^/[A-Za-z0-9_./-]+$ ]] || fail "远端目录只允许普通路径字符。"
[[ "$PUBLIC_URL" =~ ^https://[A-Za-z0-9.-]+(/[A-Za-z0-9_./-]*)?$ ]] || fail "公开 URL 格式不正确。"

if [[ ! -s "$KEY" ]]; then
  say "生成专用 SSH 密钥（私钥只保存在本机）"
  ssh-keygen -t ed25519 -N '' -f "$KEY" -C 'cfst-top10-publisher'
fi
chmod 600 "$KEY"
cat > "$CONFIG" <<EOF
VPS_HOST='$VPS_HOST'
VPS_PORT='$VPS_PORT'
VPS_USER='$VPS_USER'
REMOTE_DIR='$REMOTE_DIR'
PUBLIC_URL='$PUBLIC_URL'
EOF
chmod 600 "$CONFIG"

say "安装测速与发布脚本"
cat > "$PUBLISHER" <<'SH'
#!/usr/bin/env bash
set -Eeuo pipefail
BASE="$HOME/CFST"
BIN_DIR="$BASE/cfst_linux_amd64"
CONFIG="$BASE/publish.conf"
KEY="$HOME/.ssh/cfst_publish"
CSV="$BIN_DIR/result.csv"
OUT="$BASE/top10.txt"
TMP="$BASE/top10.txt.tmp"
LOCK="$BASE/.run.lock"
[[ -r "$CONFIG" ]] || { echo '缺少 publish.conf，请重新运行安装脚本。' >&2; exit 1; }
# shellcheck disable=SC1090
source "$CONFIG"
mkdir "$LOCK" 2>/dev/null || { echo '测速任务正在运行，退出。'; exit 1; }
trap 'rmdir "$LOCK" 2>/dev/null || true; rm -f "$TMP"' EXIT
cd "$BIN_DIR"
echo "[$(date '+%F %T')] 开始测速"
./cfst > "$BASE/cfst-run.log" 2>&1 || { tail -20 "$BASE/cfst-run.log"; exit 1; }
[[ -s "$CSV" ]] || { echo 'result.csv 不存在或为空；保留之前的公开结果。' >&2; exit 1; }
python3 - "$CSV" "$TMP" <<'PY'
import csv, ipaddress, sys
src, dst = sys.argv[1:3]
rows = []
with open(src, encoding='utf-8-sig', newline='') as f:
    reader = csv.DictReader(f)
    for r in reader:
        try:
            ip = r.get('IP 地址', r.get('IP', '')).strip()
            ipaddress.ip_address(ip)
            loss = float(r.get('丢包率', r.get('丢包', '100')).strip().rstrip('%'))
            speed = float(r.get('下载速度(MB/s)', r.get('下载速度', '0')).strip())
            if loss == 0 and speed >= 0:
                rows.append((speed, ip))
        except (ValueError, AttributeError, TypeError):
            continue
rows.sort(key=lambda x: (-x[0], x[1]))
ips, seen = [], set()
for _, ip in rows:
    if ip not in seen:
        seen.add(ip)
        ips.append(ip)
    if len(ips) == 10:
        break
if not ips:
    raise SystemExit('未找到零丢包 IP；保留之前的公开结果。请检查 CFST CSV 列名/测速结果。')
with open(dst, 'w', encoding='ascii', newline='\n') as f:
    f.write('\n'.join(ips) + '\n')
print(f'已筛选 {len(ips)} 个零丢包 IP。')
PY
mv "$TMP" "$OUT"
scp -i "$KEY" -P "$VPS_PORT" -o BatchMode=yes -o ConnectTimeout=10 "$OUT" "$VPS_USER@$VPS_HOST:$REMOTE_DIR/top10.txt"
echo "[$(date '+%F %T')] 发布成功：$(wc -l < "$OUT") 个 IP"
echo "公开地址：$PUBLIC_URL"
SH
chmod 700 "$PUBLISHER"

cat > "$MANAGER" <<'SH'
#!/usr/bin/env bash
set -u
BASE="$HOME/CFST"
PUBLISHER="$BASE/run-and-publish.sh"
CONFIG="$BASE/publish.conf"
URL="$(sed -n "s/^PUBLIC_URL='\(.*\)'$/\1/p" "$CONFIG" 2>/dev/null | head -n1)"
URL="${URL:-https://sha256.680675.xyz/cfst/top10.txt}"
while true; do
  clear 2>/dev/null || true
  echo '===== CFST Top 10 管理菜单 ====='
  echo '1) 立即测速并发布'
  echo '2) 查看公开 Top 10'
  echo '3) 查看自动任务日志'
  echo '4) 查看最近一次测速日志'
  echo '5) 查看定时任务'
  echo '0) 退出'
  read -r -p '请选择: ' c
  case "$c" in
    1) "$PUBLISHER" >> "$BASE/cron.log" 2>&1; echo "退出码=$?"; tail -20 "$BASE/cron.log" 2>/dev/null || true; read -r -p '回车继续...' _ ;;
    2) echo "地址：$URL"; curl -fsSL --max-time 15 "$URL" || true; echo; read -r -p '回车继续...' _ ;;
    3) tail -30 "$BASE/cron.log" 2>/dev/null || echo '暂无日志'; read -r -p '回车继续...' _ ;;
    4) tail -30 "$BASE/cfst-run.log" 2>/dev/null || echo '暂无日志'; read -r -p '回车继续...' _ ;;
    5) crontab -l 2>/dev/null | grep -F "$PUBLISHER" || echo '未找到定时任务'; read -r -p '回车继续...' _ ;;
    0) exit 0 ;;
    *) echo '无效选项'; sleep 1 ;;
  esac
done
SH
chmod 700 "$MANAGER"

say "设置每天凌晨 03:30 自动测速并发布"
OLD_CRON="$(crontab -l 2>/dev/null || true)"
NEW_CRON="$(printf '%s\n' "$OLD_CRON" | grep -vF '# cfst-top10 managed job' || true)"
printf '%s\n%s\n' "$NEW_CRON" "30 3 * * * $PUBLISHER >> $BASE/cron.log 2>&1 # cfst-top10 managed job" | sed '/^[[:space:]]*$/d' | crontab -

say "安装完成"
echo "管理菜单：$MANAGER"
echo "立即测速：$PUBLISHER"
echo "本地结果：$BASE/top10.txt"
echo "公开地址：$PUBLIC_URL"
echo
echo "请将以下公钥添加到 VPS 上传用户的 ~/.ssh/authorized_keys："
cat "$KEY.pub"
echo
echo "远端目录 $REMOTE_DIR 必须已存在，并且上传用户有写入权限。"
echo "完成 VPS 授权后，执行：$PUBLISHER"
echo "进入菜单：$MANAGER"
