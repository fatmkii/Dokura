# Dokura 部署、备份恢复与升级

## 首次部署

Dokura 的生产容器固定使用 Python 3.14.5、Node.js 24.16.0、uv 0.11.16 和 SQLite 3.51.3；Dockerfile 中的基础镜像同时固定了多架构摘要。容器以固定的非特权用户 `10001:10001` 运行，根文件系统只读且不保留 Linux capabilities。

```bash
mkdir -p content MetaData Config
sudo chown -R 10001:10001 MetaData Config
docker compose build --pull
docker compose up -d
docker compose ps
```

`content` 是 ZIP 原文件目录。默认按只读卷挂载；如果要使用 Web 文件管理功能，应在 `compose.yaml` 中移除该卷的 `:ro`，并只授予 UID/GID 10001 管理该目录所需的最小权限。不要开放符号链接目录。`MetaData` 和 `Config` 必须位于支持可靠文件锁的持久化本地或块存储上，不能随容器重建删除。

浏览器打开 `http://服务器地址:8000`，首次使用 `admin` / `admin` 登录，并立即在设置页改为至少 8 个 Unicode 字符的新密码。默认密码只用于首次登录。

## Android APIkey

在 Web 设置页输入当前管理员密码、确认所有 Android 客户端都需要重新配置，再生成 APIkey。完整 key 只显示一次；记录后在 Android 的连接设置中填写。重新生成后旧 key 立即失效。不要把 key 放入 URL、Compose 环境变量、截图或普通日志。

## 冷备份与恢复

Content 不属于 Dokura 配置备份，应由 NAS 的独立策略保护。MetaData 和 Config 必须来自同一个备份批次，不能混用时间点。创建冷备份：

```bash
docker compose stop dokura
scripts/dokura-backup.sh /安全的备份目录
docker compose start dokura
```

备份脚本在容器运行时会拒绝执行，并通过同一非特权镜像读取权限为 0600 的凭据文件，再为归档生成 SHA-256 文件。恢复会完整替换现有状态，因此先为当前状态另建冷备份作为回退，然后执行：

```bash
docker compose stop dokura
scripts/dokura-restore.sh /安全的备份目录/dokura-时间戳.tar.gz
docker compose start dokura
```

恢复脚本先校验旁边的 SHA-256 文件和归档路径，再在容器临时目录展开；只有验证成功后才清空并替换两个卷的内容。它不会修改 bind mount 根目录的所有者或权限。

启动后检查 `/api/v1/health` 和管理页扫描状态。服务会按当前 Content 重新对账：备份后新增或替换的 ZIP 遵循现有身份规则。`MetaData/covers` 可以不恢复；下一次扫描会为仍存在的 ZIP 排队重新生成缺失封面。

## 升级与故障恢复

升级前先完成上述冷备份，然后拉取指定发布版本并重建。启动时 Alembic 会在开放管理功能前自动迁移数据库；不要同时运行两个 Dokura 实例指向同一 MetaData。

```bash
docker compose stop dokura
scripts/dokura-backup.sh /安全的备份目录
git checkout <经过审核的发布版本>
docker compose build --pull
docker compose up -d
docker compose ps
```

健康检查不等待扫描完成。扫描期间或 Content 暂时不可访问时，容器仍应保持健康；不可访问记录会被标记为存储不可用，不会推断为删除。恢复 Content 权限或挂载后触发重新扫描即可。

如果迁移后需要回退，停止新容器，切回旧发布版本，并按冷恢复步骤同时恢复升级前的 MetaData 和 Config。不要用新版本迁移后的数据库直接启动旧版本。

忘记管理员密码时，在容器停止后运行一次性重置命令；该操作撤销全部 Web 会话，但不轮换 Android APIkey：

```bash
docker compose run --rm dokura .venv/bin/dokura-reset-password --password '新的长密码'
```
