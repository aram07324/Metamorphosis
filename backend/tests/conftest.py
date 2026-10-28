from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.db.base import Base
from app.db.session import create_database_engine
from app.main import create_app
from app.models import ChatTurn, Conversation, Message, Workspace


@pytest.fixture
def client() -> Iterator[TestClient]:
    engine = create_database_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    settings = Settings(
        _env_file=None,
        ai_provider="mock",
        cors_origins=["http://localhost:3000"],
    )
    with TestClient(create_app(settings=settings, engine=engine)) as test_client:
        yield test_client
