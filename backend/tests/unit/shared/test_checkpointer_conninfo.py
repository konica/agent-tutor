from smart_tutor.shared.adapters.postgres.checkpointer import psycopg_conninfo


def test_psycopg_conninfo_drops_the_driver_and_keeps_the_encoded_password() -> None:
    assert psycopg_conninfo("postgresql+psycopg://u:p%40x@h:1/db") == "postgresql://u:p%40x@h:1/db"
