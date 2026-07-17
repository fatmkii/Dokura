# 阶段 6 验收记录

## 范围

- Compose 导航、目录层级、无限分页、300ms 搜索防抖、筛选排序和目录状态恢复。
- Retrofit/OkHttp 连接与只读请求重试，DataStore 设置、Keystore APIkey 和 Room 最近阅读状态。
- 文件详情、乐观评分、按可见范围加载的 4/5/6 列预览网格及横竖屏布局。
- 仅服务端明确返回 404 时移除对应本地阅读状态。

## 一键验收

```bash
scripts/acceptance/stage-06.sh
```

脚本先运行 JVM 测试、Compose 仪器测试源码编译、lint 和 APK 构建，再通过 Windows SDK 的 `adb.exe` 在 `emulator-5554` 安装并执行仪器测试。可使用 `ADB_EXE` 和 `ANDROID_DEVICE` 覆盖默认路径与设备。

JVM 测试使用 MockWebServer，不会连接或修改真实 Dokura 服务；`Content/` 不会被读取、修改或删除。

## 2026-07-17 验收结果

- 环境：WSL2 Ubuntu 24.04.1、JDK 17、Gradle 9.5、Android SDK 36、Windows `emulator-5554`（Android 36）。
- `testDebugUnitTest`：12 项通过，覆盖五类连接失败、成功身份与鉴权、1/2/5 秒重试、分页去重、预览档位和 404 本地状态规则。
- `lintDebug`、`assembleDebug`、`assembleDebugAndroidTest`：通过。
- Windows 模拟器仪器测试：4 项通过，覆盖主导航、APIkey 密码语义、主题切换表单保持、横竖屏旋转、200% 字体缩放和 4/5/6 列设置保持。
- 数据集：MockWebServer 响应和空本地 Room 数据库；阶段 6 验收没有读取或修改仓库 `Content/` ZIP。

已知范围边界：全屏阅读器、阅读进度写入时机、原图预读取和磁盘缓存属于阶段 7，本阶段只建立其 Room 最近阅读/进度状态入口，详情页的阅读按钮保持禁用。
