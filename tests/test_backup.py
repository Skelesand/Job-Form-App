import sqlite3

import backup


def test_backup_and_restore_preserve_data(tmp_path):
    source = tmp_path / "source.db"
    backup_path = tmp_path / "backups" / "scan_jobs-test.db"
    restored = tmp_path / "restored.db"

    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE projects (id INTEGER PRIMARY KEY, project_name TEXT)")
        connection.execute("INSERT INTO projects (project_name) VALUES ('Example')")
        connection.commit()

    backup.backup_database(f"sqlite:///{source}", backup_path)
    backup.restore_database(backup_path, f"sqlite:///{restored}")

    with sqlite3.connect(restored) as connection:
        row = connection.execute("SELECT project_name FROM projects").fetchone()
    assert row == ("Example",)
