import datetime as dt
import os
from pathlib import Path

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, Integer, String, create_engine, event, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
import validation


DEFAULT_DATABASE_URL = "sqlite:///data/scan_jobs.db"
DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint("sqft > 0", name="ck_projects_sqft_positive"),
        CheckConstraint("levels > 0", name="ck_projects_levels_positive"),
        CheckConstraint("partition_density >= 0", name="ck_projects_partition_density_nonnegative"),
        CheckConstraint("site_condition BETWEEN 1 AND 3", name="ck_projects_site_condition_range"),
        CheckConstraint("coverage BETWEEN 0 AND 1", name="ck_projects_coverage_range"),
        CheckConstraint("scan_count > 0", name="ck_projects_scan_count_positive"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    project_type: Mapped[str] = mapped_column(String(100))
    sector: Mapped[str] = mapped_column(String(100))
    sqft: Mapped[int] = mapped_column(Integer)
    levels: Mapped[int] = mapped_column(Integer)
    partition_density: Mapped[int] = mapped_column(Integer)
    site_condition: Mapped[int] = mapped_column(Integer)
    interior: Mapped[bool] = mapped_column(Boolean)
    exterior: Mapped[bool] = mapped_column(Boolean)
    roof: Mapped[bool] = mapped_column(Boolean)
    coverage: Mapped[float] = mapped_column(Float)
    scan_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=lambda: dt.datetime.now(dt.UTC))
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=lambda: dt.datetime.now(dt.UTC), onupdate=lambda: dt.datetime.now(dt.UTC))


_engine = None
_Session = None


def get_engine(database_url=None):
    global _engine
    url = database_url or DATABASE_URL
    if _engine is None or str(_engine.url) != url:
        if url.startswith("sqlite:///"):
            database_path = Path(url.removeprefix("sqlite:///"))
            if not database_path.is_absolute():
                database_path.parent.mkdir(parents=True, exist_ok=True)
        connect_args = {"timeout": 10} if url.startswith("sqlite") else {}
        _engine = create_engine(url, future=True, connect_args=connect_args)
        if url.startswith("sqlite"):
            @event.listens_for(_engine, "connect")
            def configure_sqlite(dbapi_connection, connection_record):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA busy_timeout=10000")
                cursor.close()
    return _engine


def get_session_factory(database_url=None):
    global _Session
    engine = get_engine(database_url)
    if _Session is None or _Session.kw.get("bind") is not engine:
        _Session = sessionmaker(bind=engine, expire_on_commit=False)
    return _Session


def init_db(database_url=None):
    Base.metadata.create_all(get_engine(database_url))


def normalize_bool(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"y", "yes", "true", "1", "1.0"}


def project_to_dict(project):
    return {
        "id": project.id,
        "project_name": project.project_name,
        "project_type": project.project_type,
        "sector": project.sector,
        "sqft": project.sqft,
        "levels": project.levels,
        "partition_density": project.partition_density,
        "site_condition": project.site_condition,
        "interior": "y" if project.interior else "n",
        "exterior": "y" if project.exterior else "n",
        "roof": "y" if project.roof else "n",
        "coverage": project.coverage,
        "scan_count": project.scan_count,
        "timestamp": project.updated_at.strftime("%Y-%m-%d %H:%M:%S") if project.updated_at else "",
    }


def project_to_model_row(project):
    return {
        "Project Name": project.project_name,
        "Project Type": project.project_type,
        "Sector": project.sector,
        "Sqft": project.sqft,
        "Levels": project.levels,
        "Partition Density": project.partition_density,
        "Site Condition": project.site_condition,
        "Interior": "y" if project.interior else "n",
        "Exterior": "y" if project.exterior else "n",
        "Roof": "y" if project.roof else "n",
        "Coverage": project.coverage,
        "Total Scans": project.scan_count,
    }


def list_projects(database_url=None):
    init_db(database_url)
    with get_session_factory(database_url)() as session:
        projects = session.scalars(select(Project).order_by(Project.id)).all()
        return [project_to_dict(project) for project in projects]


def project_names(database_url=None):
    return sorted(project["project_name"] for project in list_projects(database_url))


def get_project(project_name, database_url=None):
    init_db(database_url)
    with get_session_factory(database_url)() as session:
        identity = validation.project_identity(project_name)
        project = session.scalar(select(Project).where(func.lower(Project.project_name) == identity))
        return project_to_dict(project) if project else None


def get_projects_by_ids(project_ids, database_url=None):
    init_db(database_url)
    with get_session_factory(database_url)() as session:
        projects = session.scalars(select(Project).where(Project.id.in_(project_ids))).all()
        projects_by_id = {project.id: project for project in projects}
        return [project_to_dict(projects_by_id[project_id]) for project_id in project_ids if project_id in projects_by_id]


def get_training_rows(project_type=None, database_url=None):
    init_db(database_url)
    with get_session_factory(database_url)() as session:
        statement = select(Project).order_by(Project.id)
        projects = session.scalars(statement).all()
        rows = [project_to_model_row(project) for project in projects]
    if project_type is None:
        return rows
    normalized_type = str(project_type).strip().lower()
    return [row for row in rows if str(row["Project Type"]).strip().lower() == normalized_type]


def upsert_project(values, database_url=None):
    values = validation.validate_project(values)
    init_db(database_url)
    with get_session_factory(database_url)() as session:
        identity = validation.project_identity(values["project_name"])
        project = session.scalar(select(Project).where(func.lower(Project.project_name) == identity))
        if project is None:
            project = Project(project_name=values["project_name"])
            session.add(project)
        for field in ("project_type", "sector", "sqft", "levels", "partition_density", "site_condition", "coverage", "scan_count"):
            setattr(project, field, values[field])
        project.interior = normalize_bool(values["interior"])
        project.exterior = normalize_bool(values["exterior"])
        project.roof = normalize_bool(values["roof"])
        project.updated_at = dt.datetime.now(dt.UTC)
        session.commit()
        return project_to_dict(project)


def delete_project(project_name, database_url=None):
    init_db(database_url)
    with get_session_factory(database_url)() as session:
        project = session.scalar(select(Project).where(Project.project_name == project_name.strip()))
        if project is None:
            return False
        session.delete(project)
        session.commit()
        return True


def delete_project_by_id(project_id, database_url=None):
    init_db(database_url)
    with get_session_factory(database_url)() as session:
        project = session.get(Project, project_id)
        if project is None:
            return False
        session.delete(project)
        session.commit()
        return True
