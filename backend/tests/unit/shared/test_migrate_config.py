from alembic.config import Config

from smart_tutor.shared.adapters.postgres.migrate import escape_percent


def test_a_url_with_percent_survives_the_alembic_config() -> None:
    url = "postgresql+psycopg://user:p%40ss@localhost/db"
    config = Config()
    config.set_main_option("sqlalchemy.url", escape_percent(url))
    assert config.get_main_option("sqlalchemy.url") == url
