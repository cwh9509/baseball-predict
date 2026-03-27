"""Initial schema - teams, players, games, predictions, weather_logs

Revision ID: 001
Revises:
Create Date: 2026-03-25
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # EXTENSIONS
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

    # TEAMS
    op.create_table(
        "teams",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("league", sa.String(10), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("short_name", sa.String(20), nullable=False),
        sa.Column("city", sa.String(100)),
        sa.Column("stadium_name", sa.String(150)),
        sa.Column("stadium_lat", sa.Numeric(9, 6)),
        sa.Column("stadium_lon", sa.Numeric(9, 6)),
        sa.Column("park_factor", sa.Numeric(5, 3), server_default="1.000"),
        sa.Column(
            "surface",
            sa.String(20),
            server_default="grass",
            nullable=False,
        ),
        sa.Column(
            "roof_type",
            sa.String(20),
            server_default="open",
            nullable=False,
        ),
        sa.Column("capacity", sa.Integer),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.CheckConstraint("league IN ('KBO', 'MLB', 'NPB')", name="chk_teams_league"),
        sa.CheckConstraint(
            "surface IN ('grass', 'turf', 'hybrid')", name="chk_teams_surface"
        ),
        sa.CheckConstraint(
            "roof_type IN ('open', 'retractable', 'dome')", name="chk_teams_roof"
        ),
    )
    op.create_unique_constraint("uq_teams_league_short", "teams", ["league", "short_name"])

    # PLAYERS
    op.create_table(
        "players",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("team_id", sa.Integer, sa.ForeignKey("teams.id", ondelete="SET NULL")),
        sa.Column("league", sa.String(10), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("position", sa.String(10), nullable=False),
        sa.Column("bats", sa.CHAR(1)),
        sa.Column("throws", sa.CHAR(1)),
        sa.Column("birth_date", sa.Date),
        sa.Column("external_id", sa.String(50)),
        sa.Column("is_active", sa.Boolean, server_default="true", nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.CheckConstraint("bats IN ('L','R','S')", name="chk_players_bats"),
        sa.CheckConstraint("throws IN ('L','R')", name="chk_players_throws"),
    )
    op.create_index("idx_players_team", "players", ["team_id"])
    op.create_index("idx_players_external", "players", ["external_id"])

    # GAMES
    op.create_table(
        "games",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("league", sa.String(10), nullable=False),
        sa.Column("game_date", sa.Date, nullable=False),
        sa.Column("game_time", sa.Time(timezone=True)),
        sa.Column("home_team_id", sa.Integer, sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("away_team_id", sa.Integer, sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("home_starter_id", sa.Integer, sa.ForeignKey("players.id")),
        sa.Column("away_starter_id", sa.Integer, sa.ForeignKey("players.id")),
        sa.Column("venue", sa.String(150)),
        sa.Column("status", sa.String(20), server_default="scheduled", nullable=False),
        sa.Column("home_score", sa.SmallInteger),
        sa.Column("away_score", sa.SmallInteger),
        sa.Column("winner_team_id", sa.Integer, sa.ForeignKey("teams.id")),
        sa.Column("innings_played", sa.SmallInteger),
        sa.Column("external_game_id", sa.String(50)),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('scheduled','in_progress','final','postponed','cancelled')",
            name="chk_games_status",
        ),
    )
    op.create_index("idx_games_date", "games", ["game_date"])
    op.create_index("idx_games_home", "games", ["home_team_id"])
    op.create_index("idx_games_away", "games", ["away_team_id"])
    op.execute(
        """
        CREATE UNIQUE INDEX uq_games_external
        ON games(league, external_game_id)
        WHERE external_game_id IS NOT NULL
        """
    )

    # PREDICTIONS
    op.create_table(
        "predictions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "game_id",
            sa.Integer,
            sa.ForeignKey("games.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("model_version", sa.String(50), nullable=False),
        sa.Column(
            "predicted_winner_id",
            sa.Integer,
            sa.ForeignKey("teams.id"),
            nullable=False,
        ),
        sa.Column("home_win_prob", sa.Numeric(5, 4), nullable=False),
        sa.Column("confidence_tier", sa.String(10), server_default="medium", nullable=False),
        sa.Column(
            "feature_snapshot",
            postgresql.JSONB,
            server_default="{}",
            nullable=False,
        ),
        sa.Column("llm_explanation", sa.Text),
        sa.Column("llm_model", sa.String(50)),
        sa.Column("llm_generated_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("was_correct", sa.Boolean),
        sa.Column(
            "predicted_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "home_win_prob BETWEEN 0 AND 1", name="chk_predictions_prob"
        ),
        sa.CheckConstraint(
            "confidence_tier IN ('low','medium','high')", name="chk_predictions_tier"
        ),
    )
    op.create_index("idx_predictions_game", "predictions", ["game_id"])
    op.create_index("idx_predictions_model", "predictions", ["model_version"])
    op.create_index(
        "idx_predictions_date",
        "predictions",
        [sa.text("predicted_at DESC")],
    )
    op.create_unique_constraint(
        "uq_predictions_game_model", "predictions", ["game_id", "model_version"]
    )

    # WEATHER LOGS
    op.create_table(
        "weather_logs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "game_id",
            sa.Integer,
            sa.ForeignKey("games.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "fetched_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column("is_forecast", sa.Boolean, server_default="true", nullable=False),
        sa.Column("temperature_c", sa.Numeric(5, 2)),
        sa.Column("feels_like_c", sa.Numeric(5, 2)),
        sa.Column("humidity_pct", sa.SmallInteger),
        sa.Column("wind_speed_ms", sa.Numeric(5, 2)),
        sa.Column("wind_deg", sa.SmallInteger),
        sa.Column("wind_direction", sa.String(5)),
        sa.Column("precipitation_mm", sa.Numeric(6, 2), server_default="0"),
        sa.Column("cloud_cover_pct", sa.SmallInteger),
        sa.Column("visibility_m", sa.Integer),
        sa.Column("weather_main", sa.String(50)),
        sa.Column("weather_desc", sa.String(100)),
        sa.Column("uv_index", sa.Numeric(4, 1)),
        sa.Column("raw_response", postgresql.JSONB),
        sa.CheckConstraint(
            "humidity_pct BETWEEN 0 AND 100", name="chk_weather_humidity"
        ),
        sa.CheckConstraint("wind_deg BETWEEN 0 AND 360", name="chk_weather_wind_deg"),
        sa.CheckConstraint(
            "cloud_cover_pct BETWEEN 0 AND 100", name="chk_weather_cloud"
        ),
    )
    op.create_index("idx_weather_game", "weather_logs", ["game_id"])
    op.create_index(
        "idx_weather_fetched",
        "weather_logs",
        [sa.text("fetched_at DESC")],
    )

    # updated_at auto-update triggers
    op.execute(
        """
        CREATE OR REPLACE FUNCTION set_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    for table in ("teams", "players", "games"):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_updated_at
            BEFORE UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
            """
        )


def downgrade() -> None:
    for table in ("teams", "players", "games"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_updated_at ON {table}")
    op.execute("DROP FUNCTION IF EXISTS set_updated_at()")

    op.drop_table("weather_logs")
    op.drop_table("predictions")
    op.drop_table("games")
    op.drop_table("players")
    op.drop_table("teams")
