"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-09-12

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "project",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("repository", sa.String(), nullable=False),
        sa.Column("branch", sa.String(), nullable=False),
        sa.Column("runtime", sa.String(), nullable=False),
        sa.Column("deployment_path", sa.String(), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("domain", sa.String(), nullable=True),
        sa.Column("service_name", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_project_name"), "project", ["name"], unique=True)

    op.create_table(
        "deployment",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("commit_sha", sa.String(), nullable=True),
        sa.Column("branch", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("release_path", sa.String(), nullable=True),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_deployment_project_id"), "deployment", ["project_id"], unique=False)
    op.create_index(op.f("ix_deployment_status"), "deployment", ["status"], unique=False)

    op.create_table(
        "deploymentlog",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("deployment_id", sa.Integer(), nullable=False),
        sa.Column("message", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["deployment_id"], ["deployment.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_deploymentlog_deployment_id"), "deploymentlog", ["deployment_id"], unique=False
    )

    op.create_table(
        "domain",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("hostname", sa.String(), nullable=False),
        sa.Column("www_enabled", sa.Boolean(), nullable=False),
        sa.Column("ssl_enabled", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_domain_project_id"), "domain", ["project_id"], unique=False)

    op.create_table(
        "environmentvariable",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("value", sa.String(), nullable=False),
        sa.Column("secret", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_environmentvariable_project_id"),
        "environmentvariable",
        ["project_id"],
        unique=False,
    )

    op.create_table(
        "githubinstallation",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("app_id", sa.String(), nullable=True),
        sa.Column("installation_id", sa.String(), nullable=True),
        sa.Column("configured", sa.Boolean(), nullable=False),
        sa.Column("webhook_path", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "systemevent",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("message", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_systemevent_event_type"), "systemevent", ["event_type"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_systemevent_event_type"), table_name="systemevent")
    op.drop_table("systemevent")
    op.drop_table("githubinstallation")
    op.drop_index(op.f("ix_environmentvariable_project_id"), table_name="environmentvariable")
    op.drop_table("environmentvariable")
    op.drop_index(op.f("ix_domain_project_id"), table_name="domain")
    op.drop_table("domain")
    op.drop_index(op.f("ix_deploymentlog_deployment_id"), table_name="deploymentlog")
    op.drop_table("deploymentlog")
    op.drop_index(op.f("ix_deployment_status"), table_name="deployment")
    op.drop_index(op.f("ix_deployment_project_id"), table_name="deployment")
    op.drop_table("deployment")
    op.drop_index(op.f("ix_project_name"), table_name="project")
    op.drop_table("project")
