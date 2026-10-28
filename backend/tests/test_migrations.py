from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.core.config import get_settings


def test_initial_migration_creates_workspace_table(
    tmp_path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "migration-test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path.as_posix()}")
    get_settings.cache_clear()
    config = Config("alembic.ini")

    try:
        command.upgrade(config, "head")
    finally:
        get_settings.cache_clear()

    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    try:
        table_names = inspect(engine).get_table_names()
        assert "workspaces" in table_names
        assert "conversations" in table_names
        assert "messages" in table_names
        assert "chat_turns" in table_names
        assert "alembic_version" in table_names
    finally:
        engine.dispose()
