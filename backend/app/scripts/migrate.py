# Path: app/scripts/migrate.py
# Description: Normalize the former schema-equivalent Alembic head, then upgrade to the canonical head.

from alembic.config import Config
from sqlalchemy import inspect, text

from alembic import command
from app.utils import egress
from app.utils.postgres import AnthropicFallbackDb, ProxyEventDb
from app.utils.postgres.base import engine, init_database

CANONICAL_REVISION = "001"
LEGACY_EQUIVALENT_HEADS = frozenset({"0011", "002", "003", "004", "005"})
KNOWN_CHAIN_REVISIONS = frozenset({"001", "007", "008", "009", "010", "011"})


def normalize_legacy_head() -> None:
    """Stamp every recognized historical head to the single canonical revision.

    The historical revision files are intentionally removed after the squash,
    so this normalization must run before Alembic resolves the current head.
    """
    init_database()
    with engine.begin() as connection:
        if not inspect(connection).has_table("alembic_version"):
            return
        revisions = connection.execute(text("SELECT version_num FROM alembic_version FOR UPDATE")).scalars().all()
        recognized_revisions = KNOWN_CHAIN_REVISIONS | LEGACY_EQUIVALENT_HEADS
        if len(revisions) == 1 and revisions[0] in recognized_revisions:
            if revisions[0] != CANONICAL_REVISION:
                connection.execute(
                    text("UPDATE alembic_version SET version_num = :canonical WHERE version_num = :legacy"),
                    {"canonical": CANONICAL_REVISION, "legacy": revisions[0]},
                )
            return
        if len(revisions) != 1 or revisions[0] not in recognized_revisions:
            rendered = ", ".join(revisions) if revisions else "empty"
            raise RuntimeError(
                f"Unsupported Alembic state ({rendered}); expected one of "
                f"{sorted(KNOWN_CHAIN_REVISIONS)} or one of {sorted(LEGACY_EQUIVALENT_HEADS)}."
            )
        connection.execute(
            text("UPDATE alembic_version SET version_num = :canonical WHERE version_num = :legacy"),
            {"canonical": CANONICAL_REVISION, "legacy": revisions[0]},
        )


def sync_canonical_schema() -> None:
    """Apply additive fields introduced after the migration history was squashed."""
    with engine.begin() as connection:
        inspector = inspect(connection)
        if not inspector.has_table("accounts"):
            return
        account_columns = {column["name"] for column in inspector.get_columns("accounts")}
        quota_columns = {
            "session_used_pct": "DOUBLE PRECISION",
            "session_reset_at": "TIMESTAMP WITH TIME ZONE",
            "weekly_used_pct": "DOUBLE PRECISION",
            "weekly_reset_at": "TIMESTAMP WITH TIME ZONE",
            "monthly_used_pct": "DOUBLE PRECISION",
            "monthly_reset_at": "TIMESTAMP WITH TIME ZONE",
        }
        for column_name, column_type in quota_columns.items():
            if column_name not in account_columns:
                connection.execute(text(f"ALTER TABLE accounts ADD COLUMN {column_name} {column_type}"))
        threshold_columns = {
            "five_hour_rotation_threshold": "DOUBLE PRECISION",
            "weekly_rotation_threshold": "DOUBLE PRECISION",
        }
        for column_name, column_type in threshold_columns.items():
            if column_name not in account_columns:
                connection.execute(text(f"ALTER TABLE accounts ADD COLUMN {column_name} {column_type} NOT NULL DEFAULT 1.0"))
                connection.execute(text(f"UPDATE accounts SET {column_name} = rotation_threshold WHERE rotation_threshold IS NOT NULL"))
        if "authenticated_override" not in account_columns:
            connection.execute(text("ALTER TABLE accounts ADD COLUMN authenticated_override BOOLEAN NOT NULL DEFAULT FALSE"))
        warmup_columns = {
            "warmup_enabled": "BOOLEAN NOT NULL DEFAULT TRUE",
            "warmup_next_at": "TIMESTAMP WITH TIME ZONE",
            "warmup_last_at": "TIMESTAMP WITH TIME ZONE",
            "warmup_last_status": "VARCHAR(32)",
            "warmup_last_error": "TEXT",
        }
        for column_name, column_type in warmup_columns.items():
            if column_name not in account_columns:
                connection.execute(text(f"ALTER TABLE accounts ADD COLUMN {column_name} {column_type}"))

        # Automatic egress rotation is intentionally disabled. Persist the
        # first enabled configured target for every account so restored or
        # upgraded databases have the same deterministic assignment as new
        # accounts and request-time fallback.
        inspector = inspect(connection)
        account_columns = {column["name"] for column in inspector.get_columns("accounts")}
        if "egress_target_id" not in account_columns:
            connection.execute(text("ALTER TABLE accounts ADD COLUMN egress_target_id VARCHAR(128)"))
        default_egress_target = egress.get_pool().default_target().id
        connection.execute(
            text("UPDATE accounts SET egress_target_id = :target_id"),
            {"target_id": default_egress_target},
        )

        user_columns = {column["name"] for column in inspector.get_columns("users")}
        user_additions = {
            "priority": "INTEGER NOT NULL DEFAULT 1",
            "fallback_enabled": "BOOLEAN NOT NULL DEFAULT FALSE",
            "lifetime_token_budget": "BIGINT",
            "monthly_spend_budget_usd": "DOUBLE PRECISION",
            "lifetime_spend_budget_usd": "DOUBLE PRECISION",
            "model_overrides_json": "TEXT NOT NULL DEFAULT '{}'",
        }
        for column_name, column_type in user_additions.items():
            if column_name not in user_columns:
                connection.execute(text(f"ALTER TABLE users ADD COLUMN {column_name} {column_type}"))

        # Reconcile fallback routing additions without inventing a second
        # migration history.
        AnthropicFallbackDb.__table__.create(connection, checkfirst=True)
        inspector = inspect(connection)
        fallback_columns = {column["name"] for column in inspector.get_columns("anthropic_fallbacks")}
        if "egress_target_id" not in fallback_columns:
            connection.execute(text("ALTER TABLE anthropic_fallbacks ADD COLUMN egress_target_id VARCHAR(128)"))
        default_egress_target = egress.get_pool().default_target().id
        connection.execute(
            text("UPDATE anthropic_fallbacks SET egress_target_id = :target_id"),
            {"target_id": default_egress_target},
        )
        inspector = inspect(connection)
        usage_columns = {column["name"] for column in inspector.get_columns("usage_records")}
        if "fallback_provider_id" not in usage_columns:
            connection.execute(
                text("ALTER TABLE usage_records ADD COLUMN fallback_provider_id UUID REFERENCES anthropic_fallbacks(id) ON DELETE SET NULL")
            )
        if "billed_cost_usd" not in usage_columns:
            connection.execute(text("ALTER TABLE usage_records ADD COLUMN billed_cost_usd DOUBLE PRECISION"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_usage_records_fallback_provider_id ON usage_records (fallback_provider_id)"))

        events_existed = inspect(connection).has_table("proxy_events")
        ProxyEventDb.__table__.create(connection, checkfirst=True)
        if not events_existed:
            connection.execute(
                text(
                    """
                    INSERT INTO proxy_events
                        (id, created_at, request_id, user_id, api_key_id, account_id,
                         fallback_provider_id, event_type, status_code, message, metadata_json)
                    SELECT gen_random_uuid(), u.created_at,
                           COALESCE(NULLIF(u.request_id, ''), 'req_legacy_' || replace(u.id::text, '-', '')),
                           u.user_id, u.account_id, u.api_key_id, u.fallback_provider_id,
                           'response.returned', u.status_code, 'Migrated from request history',
                           json_build_object('model', u.model, 'reasoning_level', u.reasoning_level,
                             'input_tokens', u.input_tokens, 'output_tokens', u.output_tokens,
                             'cache_read_input_tokens', u.cache_read_input_tokens,
                             'cache_write_tokens', u.cache_creation_input_tokens,
                             'cost_usd', u.billed_cost_usd)::text
                    FROM usage_records u
                    WHERE NOT EXISTS (
                        SELECT 1 FROM proxy_events e
                        WHERE e.event_type = 'response.returned'
                          AND e.request_id = COALESCE(NULLIF(u.request_id, ''), 'req_legacy_' || replace(u.id::text, '-', ''))
                    )
                    """
                )
            )


def main() -> None:
    normalize_legacy_head()
    command.upgrade(Config("alembic.ini"), "head")
    sync_canonical_schema()


if __name__ == "__main__":
    main()
