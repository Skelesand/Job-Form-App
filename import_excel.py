import argparse
import datetime as dt
from collections import Counter

import pandas as pd
from sqlalchemy import select

import db
import validation


REQUIRED_COLUMNS = [
    "Project Name", "Project Type", "Sector", "Sqft", "Levels",
    "Partition Density", "Site Condition", "Interior", "Exterior",
    "Roof", "Coverage", "Total Scans",
]


def normalize_name(value):
    return validation.project_identity(value)


def parse_row(row, row_number):
    values = {
        "project_name": row["Project Name"],
        "project_type": str(row["Project Type"]).strip(),
        "sector": str(row["Sector"]).strip(),
        "sqft": int(float(row["Sqft"])),
        "levels": int(float(row["Levels"])),
        "partition_density": int(float(row["Partition Density"])),
        "site_condition": int(float(row["Site Condition"])),
        "interior": row["Interior"],
        "exterior": row["Exterior"],
        "roof": row["Roof"],
        "coverage": float(row["Coverage"]),
        "scan_count": int(float(row["Total Scans"])),
    }
    try:
        return validation.validate_project(values)
    except validation.ValidationError as exc:
        raise ValueError(f"row {row_number}: {exc}") from exc


def inspect_workbook(excel_path):
    dataframe = pd.read_excel(excel_path)
    missing_columns = [column for column in REQUIRED_COLUMNS if column not in dataframe.columns]
    if missing_columns:
        raise ValueError(f"Missing required workbook columns: {', '.join(missing_columns)}")

    rows = []
    errors = []
    for index, (_, row) in enumerate(dataframe.iterrows(), start=2):
        try:
            rows.append(parse_row(row, index))
        except (TypeError, ValueError, OverflowError) as exc:
            errors.append(str(exc))

    names = [normalize_name(row["project_name"]) for row in rows]
    duplicate_names = sorted(name for name, count in Counter(names).items() if count > 1)
    return rows, errors, duplicate_names


def import_workbook(excel_path, database_url=None, dry_run=False):
    rows, errors, duplicate_names = inspect_workbook(excel_path)
    report = {
        "rows": len(rows),
        "errors": errors,
        "duplicates": duplicate_names,
        "imported": 0,
        "added": 0,
        "updated": 0,
        "skipped": 0,
        "rejected": len(errors),
    }
    if errors or duplicate_names or dry_run:
        return report

    db.init_db(database_url)
    session_factory = db.get_session_factory(database_url)
    with session_factory() as session:
        existing_names = {
            normalize_name(name)
            for name in session.scalars(select(db.Project.project_name)).all()
        }
        collisions = sorted(existing_names.intersection(normalize_name(row["project_name"]) for row in rows))
        if collisions:
            report["duplicates"] = collisions
            report["skipped"] = len(collisions)
            return report

        for values in rows:
            project_values = values.copy()
            project_values["interior"] = db.normalize_bool(values["interior"])
            project_values["exterior"] = db.normalize_bool(values["exterior"])
            project_values["roof"] = db.normalize_bool(values["roof"])
            project = db.Project(
                **project_values,
                created_at=dt.datetime.now(dt.UTC),
                updated_at=dt.datetime.now(dt.UTC),
            )
            session.add(project)
        session.commit()
        report["imported"] = len(rows)
        report["added"] = len(rows)
    return report


def main():
    parser = argparse.ArgumentParser(description="Import scan jobs from the legacy Excel workbook.")
    parser.add_argument("--excel", default="data/Scan_Log_Dataset.xlsx")
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    report = import_workbook(args.excel, args.database_url, args.dry_run)
    print(f"Valid rows: {report['rows']}")
    print(f"Imported rows: {report['imported']}")
    if report["errors"]:
        print("Validation errors:")
        for error in report["errors"]:
            print(f"- {error}")
    if report["duplicates"]:
        print("Duplicate project names requiring review:")
        for name in report["duplicates"]:
            print(f"- {name}")
    if report["errors"] or report["duplicates"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
