# 阶段 0 验收报告

- 验收日期：2026-07-16
- 环境：WSL2 Ubuntu 24.04.1 LTS；Docker Desktop 29.4.3；JDK 17.0.19
- 数据集：Docker 验收使用一次性 Content/MetaData/Config 目录；仓库 `content/` 样例只读且未参与写入测试

## 固定版本

- Server：Python 3.14.5、FastAPI 0.138.2、uv 0.11.16
- Web：Node.js 24.16.0、Vue 3.5.40、Naive UI 2.44.1、TypeScript 5.9.3、Vite 7.3.6
- Android：Kotlin 2.4.10、Compose BOM 2026.06.01、Android Gradle Plugin 9.3.0、Gradle Wrapper 9.5.0
- Docker SQLite：3.51.3，源码归档 SHA-256 `81f5be397049b0cae1b167f2225af7646fc0f82e4a9b3c48c9ea3a533e21d77a`

## 验收结果

执行 `scripts/acceptance/stage-00.sh`，结果通过：

- Server：9 项单元/集成测试通过；OpenAPI 漂移检查通过。
- Web：1 项单元测试通过；类型检查和生产构建通过；Playwright 能发现 1 项 Chromium E2E 测试。
- Android：lint、JVM 测试、debug APK 构建通过；仪器测试源码编译通过。
- Docker：健康接口和同源 Web 页面可用；运行时报告 SQLite 3.51.3 且 FTS5 trigram 自检通过；强制重建容器后，三个挂载中的验证数据仍存在，Content 挂载保持只读。
- OpenAPI：连续生成 SHA-256 均为 `cecf5c04259a0cf1b6ebbbac1100977811af14e6e91fda0a7e3978fa9acafeb8`。

构建产物：

- debug APK：`android/app/build/outputs/apk/debug/app-debug.apk`
- APK 大小：11,568,658 字节
- APK SHA-256：`7418aeb8b589b32768bdd0d9c244a4b5848453b3bbae8c4b3b78f91291bc8cba`
- Docker 镜像：`dokura:stage-00`，镜像 ID `sha256:8871a067ff14bd357dfdae188de1b5c8bbe33ab4000b30a05fe9d63e2368c3c4`

## 已知边界

阶段 0 只建立工程、契约和测试入口。扫描、元数据模型、鉴权、业务页面及 Android 设备仪器测试执行属于后续阶段；本阶段未将这些功能伪装为可用。
