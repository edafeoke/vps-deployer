from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


class Project(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    repository: str
    branch: str = "main"
    runtime: str = "nextjs"
    deployment_path: str
    port: int
    domain: str | None = None
    service_name: str
    enabled: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Deployment(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(index=True, foreign_key="project.id")
    commit_sha: str | None = None
    branch: str = "main"
    status: str = Field(default="QUEUED", index=True)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_seconds: int | None = None
    release_path: str | None = None
    error_message: str | None = None


class DeploymentLog(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    deployment_id: int = Field(index=True, foreign_key="deployment.id")
    message: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Domain(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(index=True, foreign_key="project.id")
    hostname: str
    www_enabled: bool = False
    ssl_enabled: bool = False


class EnvironmentVariable(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(index=True, foreign_key="project.id")
    key: str
    value: str
    secret: bool = True


class GitHubInstallation(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    app_id: str | None = None
    installation_id: str | None = None
    configured: bool = False
    webhook_path: str = "/api/github/webhook"


class SystemEvent(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    event_type: str = Field(index=True)
    message: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
