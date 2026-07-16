# 开发环境简述

- 开发系统：WSL2，Ubuntu 24.04.1 LTS。
- Docker：29.4.3；Docker Compose：v5.1.4；Docker Desktop daemon 已验证可用。
- Python 包和虚拟环境必须使用 `uv`，不要直接使用系统 Python 或 `pip`。已安装 `uv 0.11.16` 和 uv 管理的 CPython 3.14.5。
- Node.js：24.16.0；npm：11.13.0；Corepack：0.35.0。
- Java：OpenJDK 17.0.19，`JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64`。

## Android 开发环境

WSL 内已安装 Android SDK：

```text
ANDROID_HOME=/home/fat/Android/Sdk
平台：android-35、android-36
Build Tools：36.0.0
Command-line Tools：20.0
```

## Windows Android 虚拟机

Android 虚拟机运行在 Windows 宿主机上。WSL 中应调用 Windows 版 `adb.exe`：

```text
/mnt/c/Users/47155/AppData/Local/Android/Sdk/platform-tools/adb.exe
```

模拟器设备为 `emulator-5554`。


## 验证用的内容

./Content文件夹中准备了约200个zip文档，项目验证时可以使用。但主要只读，不要变更或删除。