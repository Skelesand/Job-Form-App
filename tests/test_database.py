import db


PROJECT = {
    "project_name": "Database Test Project",
    "project_type": "Building",
    "sector": "Office",
    "sqft": 1000,
    "levels": 2,
    "partition_density": 4,
    "site_condition": 2,
    "interior": "y",
    "exterior": "n",
    "roof": "n",
    "coverage": 0.9,
    "scan_count": 12,
}


def test_project_repository_crud(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'projects.db'}"
    db.init_db(database_url)

    created = db.upsert_project(PROJECT, database_url)
    assert created["project_name"] == PROJECT["project_name"]
    assert created["interior"] == "y"
    assert db.project_names(database_url) == [PROJECT["project_name"]]
    assert db.get_project(PROJECT["project_name"], database_url)["scan_count"] == 12

    updated = {**PROJECT, "scan_count": 18}
    db.upsert_project(updated, database_url)
    assert db.get_project(PROJECT["project_name"], database_url)["scan_count"] == 18

    assert db.delete_project(PROJECT["project_name"], database_url) is True
    assert db.get_project(PROJECT["project_name"], database_url) is None
    assert db.delete_project(PROJECT["project_name"], database_url) is False


def test_database_constraints_reject_invalid_project(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'constraints.db'}"
    db.init_db(database_url)
    invalid_project = {**PROJECT, "sqft": 0}

    try:
        db.upsert_project(invalid_project, database_url)
        assert False, "Expected the database check constraint to reject zero square footage"
    except Exception as exc:
        assert "sqft" in str(exc).lower() or "check constraint" in str(exc).lower()
