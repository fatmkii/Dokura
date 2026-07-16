# 阶段 1 验收报告

- 验收日期：2026-07-16
- 环境：WSL2 Ubuntu 24.04.1 LTS；Python 3.14.5；uv 0.11.16
- Server 依赖：SQLAlchemy 2.0.51、Alembic 1.18.5、Pillow 12.1.1、SQLite 3.51.3
- 数据集：仓库 `content/` 中 201 个 ZIP，只读分析；破坏性 ZIP 全部在 pytest 临时目录生成

## 验收入口

```bash
scripts/acceptance/stage-01.sh
```

脚本依次验证：

1. 锁定依赖下的 Alembic 初始迁移；
2. `tags-rules.md` 样例、异常括号、Unicode NFC/casefold 与路径分段自然排序；
3. 路径穿越、加密/损坏 ZIP、CRC、声明大小、压缩比、像素炸弹和封面参数；
4. SQLite WAL/外键/FULL synchronous/busy timeout/连接上限、数据库事务边界及分析中 ZIP 变化；
5. `content/` 全部 ZIP 的只读分析，并比较分析前后完整树快照。

## 验收结果

执行 `scripts/acceptance/stage-01.sh`，结果通过：

- Alembic 初始迁移可从空数据库升级到 head，模型漂移检查无待生成操作。
- 文件名解析与自然排序 16 项测试通过。
- ZIP 安全、CRC、图片预检和封面 13 项测试通过。
- 数据库配置、单写者、事务边界、原子替换和失败状态 7 项测试通过。
- 201 个真实 ZIP 全部得到结论：199 个 `ready`，2 个 `failed`；两个失败分别为无效 ZIP 结构和无法打开的损坏 ZIP，均有稳定错误码。
- 1 个非 ZIP 文件被忽略；分析前后 `content/` 的路径、类型、大小和 mtime 快照完全相同。
- 阶段 0 完整回归同时通过：Server、Web、Android 构建以及 Docker 健康、自检和持久化均未回归。

真实内容逐文件报告默认写入 `/tmp/dokura-stage-01-content-report.json`，避免验收过程改写仓库。可用 `DOKURA_STAGE_01_REPORT` 指定其他仓库外路径。报告中的失败也属于“已处理且可解释状态”，但 `all_zips_accounted_for` 和 `content_tree_unchanged` 必须均为 `true`。

## 已知边界

- 阶段 1 提供单文件分析与原子元数据提交能力；目录发现、稳定性调度、监听和自动重试属于阶段 2。
- 初次分析只解码到第一张有效封面；后续页面在被读取时才形成确定性不可用结论。
