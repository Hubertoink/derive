from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import auth
from app.auth import password_hasher
from app.database import Base
from app.main import app, get_session
from app.models import User


def test_admin_can_invite_and_new_user_gets_an_opaque_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(User(
            username="admin", email="admin@example.org",
            password_hash=password_hasher.hash("correct-horse-battery-staple"), role="admin",
        ))
        session.commit()

    def override_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[auth.get_session] = override_session
    try:
        with TestClient(app) as client:
            login = client.post("/api/v1/auth/login", json={
                "identifier": "admin", "password": "correct-horse-battery-staple",
            })
            assert login.status_code == 200
            assert "derive_session" in login.headers["set-cookie"]
            assert client.get("/api/v1/auth/session").json()["user"]["role"] == "admin"
            assert client.get("/api/v1/setup").status_code == 200

            invitation = client.post("/api/v1/admin/invitations", json={"email": "member@example.org"})
            assert invitation.status_code == 200
            token = invitation.json()["invitation"]["url"].split("invite=", 1)[1]

        with TestClient(app) as member_client:
            register = member_client.post("/api/v1/auth/register", json={
                "username": "member", "email": "member@example.org",
                "password": "another-long-test-password", "invitation_token": token,
            })
            assert register.status_code == 200
            assert member_client.get("/api/v1/auth/session").json()["user"]["username"] == "member"
            setup = member_client.get("/api/v1/setup")
            assert setup.status_code == 200
            assert setup.json()["setup_completed"] is False
    finally:
        app.dependency_overrides.clear()
