import argparse
import datetime as dt
from collections import Counter

import pandas as pd
from sqlalchemy import select

import db


REQUIRED_COLUMNS = [
    "Project Name", "Project Type", "Sector", "Sqft", "Levels",
    "Partition Density", "Site Condition", "Interior", "Exterior",
    "Roof", "Coverage", "Total Scans",
]


def normalize_name(value):
    return str(value).strip().casefold()


def parse_row(row, row_number):
    project_name = str(row["Project Name"]).strip()
    if not project_name or project_name.lower() == "nan":
        raise ValueError(f"row {row_number}: Project Name is required")

    values = {
        "project_name": project_name,
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
    if values["sqft"] <= 0 or values["levels"] <= 0:
        raise ValueError(f"row {row_number}: square footage and levels must be positive")
    if values["partition_density"] < 0:
        raise ValueError(f"row {row_number}: partition density cannot be negative")
    if values["site_condition"] not in {1, 2, 3}:
        raise ValueError(f"row {row_number}: site condition must be 1, 2, or 3")
    if not 0 <= values["coverage"] <= 1:
        raise ValueError(f"row {row_number}: coverage must be between 0 and 1")
    if values["scan_count"] <= 0:
        raise ValueError(f"row {row_number}: total scans must be positive")
    return values


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
