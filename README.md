# 小米智能存储一键开启 ssh + root
<img width="919" height="869" alt="image" src="https://github.com/user-attachments/assets/2bb0f8f1-8b5d-4a8f-ba0c-35040c9fa75d" />

## 食用步骤：
### EXE 一键食用（Windows）：
- 登录小米智能存储客户端，以拉取证书文件
- 下载 [Release 下的 exe 文件](https://github.com/scruel/xiaomi-storage-nas-enable-ssh/releases/tag/exe)，双击执行
- 提示执行完毕，输出 root 信息即成功，APP 文件中也能看到 SUCCESS。

### 终端折腾食用：
- 登录小米智能存储客户端，以拉取证书文件
- 打开终端（Windows 下请使用 WSL Ubuntu 终端）
- 终端执行 bash <(curl -s https://raw.githubusercontent.com/scruel/xiaomi-storage-nas-enable-ssh/refs/heads/main/xiaomi-storage-open-ssh_via-wsl.sh)
- 提示执行完毕，输出 root 信息即成功，APP 文件中也能看到 SUCCESS。

## 免责声明
仅供技术交流，
