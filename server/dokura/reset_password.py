from __future__ import annotations

import argparse
import getpass

from dokura.config import Settings
from dokura.metadata.database import WriteScheduler, create_database_engine
from dokura.metadata.migrations import upgrade_database
from dokura.security import AuthService, CredentialStore, validate_new_password


def main() -> int:
    parser = argparse.ArgumentParser(description="重置 Dokura 管理员密码并撤销全部 Web 会话")
    parser.add_argument("--password", help="新密码；省略时从终端安全读取")
    args = parser.parse_args()
    password = args.password if args.password is not None else getpass.getpass("新密码: ")
    validate_new_password("", password)

    settings = Settings.from_env()
    settings.prepare()
    upgrade_database(settings.database_path)
    engine = create_database_engine(settings.database_path)
    try:
        writer = WriteScheduler(engine)
        credentials = CredentialStore(settings.config_dir)
        credentials.set_password(password)
        AuthService(engine, writer, credentials).revoke_all()
    finally:
        engine.dispose()
    print("管理员密码已重置，全部 Web 会话已撤销；Android APIkey 未改变")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
