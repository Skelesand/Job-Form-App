import datetime
import csv
import io
import os
import time
from flask import Flask, jsonify, render_template, request, redirect, send_file, url_for
import openpyxl
import model
import db

app = Flask(__name__)

EXCEL_PATH = os.getenv(
    "EXCEL_PATH",
    r"data\Scan_Log_Dataset.xlsx"
)

DATABASE_URL = os.getenv("DATABASE_URL", db.DEFAULT_DATABASE_URL)
db.init_db(DATABASE_URL)

_prediction_cache = {
    "database_url": None,
    "engines": {},
}


def get_prediction_engine(project_type):
    """Load and cache a prediction engine from the database."""
    if _prediction_cache["database_url"] != DATABASE_URL:
        _prediction_cache.update({
            "database_url": DATABASE_URL,
            "engines": {},
        })

    normalized_type = model.clean_text_values(model.pd.Series([project_type])).iloc[0]
    if normalized_type not in _prediction_cache["engines"]:
        records = db.get_training_rows(normalized_type, DATABASE_URL)
        historical_df = model.load_and_prepare_records(records, normalized_type)
        engine = None
        if len(historical_df) >= 4:
            engine = model.build_similarity_engine(historical_df)
        _prediction_cache["engines"][normalized_type] = (historical_df, engine)

    return _prediction_cache["engines"][normalized_type]


def get_existing_projects(filepath):
    """Reads the Excel sheet and returns a unique list of project names from Column A."""
    projects = []
    try:
        if os.path.exists(filepath):
            wb = openpyxl.load_workbook(filepath, data_only=True)
            sheet = wb.active
            for row in sheet.iter_rows(min_row=2, max_col=1):
                if row[0].value:
                    val = str(row[0].value).strip()
                    if val and val not in projects:
                        projects.append(val)
            wb.close()
    except Exception as e:
        print(f"[Warning] Could not read project list: {e}")
    return sorted(projects)


def get_all_projects(filepath):
    """Reads the entire Excel sheet and returns a list of dictionaries for all logged jobs."""
    projects = []
    try:
        if os.path.exists(filepath):
            wb = openpyxl.load_workbook(filepath, data_only=True)
            sheet = wb.active
            for row in sheet.iter_rows(min_row=2):
                if row[0].value:
                    projects.append({
                        "project_name": str(row[0].value).strip(),
                        "project_type": row[1].value if len(row) > 1 and row[1].value else "",
                        "sector": row[2].value if len(row) > 2 and row[2].value else "",
                        "sqft": row[3].value if len(row) > 3 and row[3].value else "",
                        "levels": row[4].value if len(row) > 4 and row[4].value else "",
                        "partition_density": row[5].value if len(row) > 5 and row[5].value else "",
                        "site_condition": row[6].value if len(row) > 6 and row[6].value else "",
                        "interior": row[7].value if len(row) > 7 and row[7].value else "",
                        "exterior": row[8].value if len(row) > 8 and row[8].value else "",
                        "roof": row[9].value if len(row) > 9 and row[9].value else "",
                        "coverage": row[10].value if len(row) > 10 and row[10].value else "",
                        "scan_count": row[11].value if len(row) > 11 and row[11].value else "",
                        "timestamp": row[12].value if len(row) > 12 and row[12].value else ""
                    })
            wb.close()
    except Exception as e:
        print(f"[Error] Could not read all projects: {e}")
    return projects


def get_project_details(filepath, project_name):
    """Searches for a project by name and returns its row values as a dictionary."""
    try:
        if os.path.exists(filepath):
            wb = openpyxl.load_workbook(filepath, data_only=True)
            sheet = wb.active

            for row in sheet.iter_rows(min_row=2):
                if row[0].value and str(row[0].value).strip() == project_name.strip():
                    data = {
                        "project_type": row[1].value if row[1].value else "",
                        "sector": row[2].value if row[2].value else "",
                        "sqft": row[3].value if row[3].value else "",
                        "levels": row[4].value if row[4].value else "",
                        "partition_density": row[5].value if row[5].value else "",
                        "site_condition": row[6].value if row[6].value else "",
                        "interior": row[7].value if row[7].value else "",
                        "exterior": row[8].value if row[8].value else "",
                        "roof": row[9].value if row[9].value else "",
                        "coverage": row[10].value if row[10].value else "",
                        "scan_count": row[11].value if row[11].value else "",
                    }
                    wb.close()
                    return data
            wb.close()
    except Exception as e:
        print(f"[Error] Failed to fetch project details: {e}")
    return None


def update_or_append_to_excel(filepath, data_row):
    max_retries = 3
    retry_delay = 2

    for attempt in range(max_retries):
        try:
            wb = openpyxl.load_workbook(filepath)
            sheet = wb.active

            project_name = data_row[0]
            row_updated = False

            for row in sheet.iter_rows(min_row=1, max_col=1):
                if row[0].value == project_name:
                    current_row_idx = row[0].row
                    for col_idx, value in enumerate(data_row, start=1):
                        sheet.cell(row=current_row_idx, column=col_idx, value=value)
                    row_updated = True
                    print(f"[Info] Updated existing row for project: {project_name}")
                    break

            if not row_updated:
                sheet.append(data_row)
                print(f"[Info] Appended new row for project: {project_name}")

            wb.save(filepath)
            wb.close()
            return True

        except PermissionError:
            print(f"[Warning] File locked. Retrying in {retry_delay} seconds... (Attempt {attempt + 1}/{max_retries})")
            time.sleep(retry_delay)

    print("[Error] Could not write to Excel. File locked.")
    return False


@app.route("/")
def home():
    """Dashboard view showing all logged jobs."""
    all_jobs = db.list_projects(DATABASE_URL)
    return render_template("index.html", jobs=all_jobs)


@app.route("/form")
def form():
    """Data entry view for logging/editing a project."""
    project_list = db.project_names(DATABASE_URL)
    return render_template("form.html", projects=project_list)


@app.route("/get_project_data")
def get_project_data():
    project_name = request.args.get("name")
    if not project_name:
        return jsonify({"success": False, "error": "No project name provided"})

    data = db.get_project(project_name, DATABASE_URL)
    if data:
        return jsonify({"success": True, "data": data})
    return jsonify({"success": False, "error": "Project not found"})


@app.route("/export", methods=["POST"])
def export_projects():
    """Create a CSV or Excel download from the dashboard's visible projects."""
    data = request.get_json(silent=True) or {}
    projects = data.get("projects")
    export_format = data.get("format", "xlsx").lower()

    if not isinstance(projects, list):
        return jsonify({"success": False, "error": "No projects were provided for export."}), 400
    if export_format not in {"csv", "xlsx"}:
        return jsonify({"success": False, "error": "Unsupported export format."}), 400

    columns = [
        "Project Name", "Project Type", "Sector", "Square Footage", "Levels",
        "Partition Density", "Site Condition", "Interior Scanned", "Exterior Scanned",
        "Roof Scanned", "Coverage", "Total Scans", "Updated",
    ]
    rows = [[project.get(key, "") for key in [
        "project_name", "project_type", "sector", "sqft", "levels",
        "partition_density", "site_condition", "interior", "exterior",
        "roof", "coverage", "scan_count", "timestamp",
    ]] for project in projects if isinstance(project, dict)]
    if not rows:
        return jsonify({"success": False, "error": "There are no visible projects to export."}), 400

    if export_format == "csv":
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(columns)
        writer.writerows(rows)
        return send_file(
            io.BytesIO(output.getvalue().encode("utf-8-sig")),
            mimetype="text/csv",
            as_attachment=True,
            download_name="scan-projects-filtered.csv",
        )

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Filtered Projects"
    sheet.append(columns)
    for row in rows:
        sheet.append(row)
    output = io.BytesIO()
    workbook.save(output)
    output.seek(0)
    return send_file(
        output,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name="scan-projects-filtered.xlsx",
    )


@app.route("/predict", methods=["GET", "POST"])
def predict():
    """Estimate scans for the current form values without saving the job."""
    if request.method == "GET":
        return render_template("predict.html")

    try:
        data = request.get_json(silent=True) or {}
        required_fields = [
            "project_type", "sector", "sqft", "levels",
            "partition_density", "site_condition", "interior",
            "exterior", "roof", "coverage"
        ]
        missing_fields = [field for field in required_fields if data.get(field) in (None, "")]
        if missing_fields:
            return jsonify({
                "success": False,
                "error": "Complete all project details before requesting an estimate."
            }), 400

        try:
            input_data = {
                "Project Type": data["project_type"],
                "Sector": data["sector"],
                "Sqft": float(data["sqft"]),
                "Levels": float(data["levels"]),
                "Partition Density": float(data["partition_density"]),
                "Site Condition": float(data["site_condition"]),
                "Interior": data["interior"],
                "Exterior": data["exterior"],
                "Roof": data["roof"],
                "Coverage": float(data["coverage"]),
            }
        except (TypeError, ValueError):
            return jsonify({"success": False, "error": "Numeric fields must contain valid numbers."}), 400

        if input_data["Sqft"] <= 0 or input_data["Levels"] <= 0 or input_data["Coverage"] < 0 or input_data["Coverage"] > 1:
            return jsonify({"success": False, "error": "Square footage and levels must be positive, and coverage must be between 0 and 1."}), 400

        historical_df, engine = get_prediction_engine(input_data["Project Type"])
        if engine is None:
            project_type = input_data["Project Type"].strip().title()
            return jsonify({
                "success": False,
                "error": f"At least four {project_type} records are needed before estimates can be generated. This type has {len(historical_df)} usable record(s)."
            }), 400

        if len(historical_df) < 10:
            project_type = input_data["Project Type"].strip().title()
            return jsonify({
                "success": False,
                "error": f"Not enough historical {project_type} records for a reliable estimate. At least 10 valid job records are required. Current total: {len(historical_df)}."
            }), 400

        input_df = model.pd.DataFrame([input_data])
        matches, prediction, confidence = model.find_lookalike_jobs(
            input_df,
            historical_df,
            *engine,
        )
        warning_message = None
        if confidence < 60:
            warning_message = f"Warning: model confidence is low ({confidence:.1f}%). Add more comparable historical jobs or review the input values."
        closest_match_scan_count = float(matches.iloc[0]["Total Scans"])
        observed_range = [
            int(round(min(prediction, closest_match_scan_count))),
            int(round(max(prediction, closest_match_scan_count)))
        ]
        match_data = []
        for _, match in matches.iterrows():
            match_data.append({
                "project_name": str(match.get("Project Name", "Historical project")),
                "scan_count": int(round(float(match["Total Scans"]))),
                "influence": round(float(match["Influence_Weight"]) * 100, 1),
            })

        return jsonify({
            "success": True,
            "prediction": round(prediction),
            "range": observed_range,
            "confidence": round(confidence, 1),
            "warning": warning_message,
            "matches": match_data,
        })
    except Exception as exc:
        print(f"[Error] Prediction failed: {exc}")
        return jsonify({"success": False, "error": "The estimate could not be generated from the current data."}), 500


def remove_project_from_excel(filepath, project_name):
    """Remove a project row from Excel by project name."""
    max_retries = 3
    retry_delay = 2

    for attempt in range(max_retries):
        try:
            wb = openpyxl.load_workbook(filepath)
            sheet = wb.active
            
            # Find and delete the row with matching project name
            for row in sheet.iter_rows(min_row=2):
                if row[0].value and str(row[0].value).strip() == project_name.strip():
                    sheet.delete_rows(row[0].row)
                    wb.save(filepath)
                    wb.close()
                    print(f"[Info] Deleted row for project: {project_name}")
                    return True
            
            wb.close()
            # If we get here, project wasn't found
            return False

        except PermissionError:
            print(f"[Warning] File locked. Retrying in {retry_delay} seconds... (Attempt {attempt + 1}/{max_retries})")
            time.sleep(retry_delay)
    
    print("[Error] Could not write to Excel. File locked.")
    return False


@app.route("/delete", methods=["POST"])
def delete_project():
    try:
        data = request.get_json()
        project_name = data.get("project_name")
        
        if not project_name:
            return jsonify({"success": False, "error": "No project name provided"})
        
        # Remove the project from Excel
        success = db.delete_project(project_name, DATABASE_URL)
        
        if success:
            return jsonify({"success": True, "message": "Project deleted successfully"})
        else:
            return jsonify({"success": False, "error": "Failed to delete project"})
    except Exception as e:
        print(f"[Error] Error deleting project: {e}")
        return jsonify({"success": False, "error": str(e)})


@app.route("/submit", methods=["POST"])
def submit():
    try:
        project_name = request.form.get("project_name")
        project_type = request.form.get("project_type")
        sector = request.form.get("sector")
        sqft = request.form.get("sqft")
        levels = request.form.get("levels")
        partition_density = request.form.get("partition_density")
        site_condition = request.form.get("site_condition")
        interior = request.form.get("interior")
        exterior = request.form.get("exterior")
        roof = request.form.get("roof")
        coverage = request.form.get("coverage")
        scan_count = request.form.get("scan_count")
        # Validate required fields
        if not project_name or not project_name.strip():
            return "<h3>Error: Project name is required.</h3><a href='/form'>Go Back</a>"

        # Validate and convert numeric fields with error handling
        try:
            sqft = int(sqft)
            levels = int(levels)
            partition_density = int(partition_density)
            site_condition = int(site_condition)
            coverage = float(coverage)
            scan_count = int(scan_count)
        except (ValueError, TypeError) as e:
            return f"<h3>Error: Invalid numeric input. {str(e)}</h3><a href='/form'>Go Back</a>"

        if sqft <= 0 or levels <= 0 or partition_density < 0 or site_condition not in {1, 2, 3}:
            return "<h3>Error: Numeric values are outside the allowed ranges.</h3><a href='/form'>Go Back</a>"
        if coverage < 0 or coverage > 1 or scan_count <= 0:
            return "<h3>Error: Coverage must be between 0 and 1 and scans must be positive.</h3><a href='/form'>Go Back</a>"

        db.upsert_project({
            "project_name": project_name.strip(),
            "project_type": project_type.strip(),
            "sector": sector.strip(),
            "sqft": sqft,
            "levels": levels,
            "partition_density": partition_density,
            "site_condition": site_condition,
            "interior": interior,
            "exterior": exterior,
            "roof": roof,
            "coverage": coverage,
            "scan_count": scan_count,
        }, DATABASE_URL)
        _prediction_cache["engines"] = {}
        return "<h3>Job logged/updated successfully!</h3><a href='/'>Go to Home Dashboard</a>"
    except Exception as e:
        print(f"[Error] Unexpected error in /submit: {e}")
        return f"<h3>Error: An unexpected error occurred. Please try again.</h3><a href='/form'>Go Back</a>"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)