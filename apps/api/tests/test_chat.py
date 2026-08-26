import asyncio

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.chat import chat_history, chat_turn, podcast_only_request
from app.database import Base
from app.models import AppSettings


def test_chat_keeps_local_history_between_turns(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    seen: list[list[dict]] = []

    async def fake_turn(_settings, messages):
        seen.append(messages)
        return "Eine Rückfrage", "Lange Reportagen über europäische Technologiepolitik"

    monkeypatch.setattr("app.chat._compatible_turn", fake_turn)
    with Session(engine) as session:
        settings = AppSettings(
            id=1,
            ai_provider="ollama",
            ai_base_url="http://ollama:11434",
            ai_model="test-model",
        )
        session.add(settings)
        session.commit()

        asyncio.run(chat_turn(session, settings, "Mehr Technologie"))
        asyncio.run(chat_turn(session, settings, "Aber weniger Produktnews"))

        history = chat_history(session)
        assert [message.role for message in history] == ["user", "assistant", "user", "assistant"]
        assert len(seen[1]) == 3
        assert seen[1][0]["content"] == "Mehr Technologie"
        assert history[-1].profile_suggestion


def test_podcast_context_with_reportages_still_requests_texts():
    assert not podcast_only_request(
        "Ich habe einen Podcast über politische Analysen gehört und möchte drei Reportagen dazu.",
        3,
    )
