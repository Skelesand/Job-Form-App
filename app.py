import csv
import io
import logging
import os
from flask import Flask, jsonify, redirect, render_template, request, send_file, url_for
from flask_wtf.csrf import CSRFProtect
import openpyxl
import model
import db
import validation

app = Flask(__name__)
APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")
if APP_ENV not in {"development", "test"} and SECRET_KEY == "dev-only-change-me":
    raise RuntimeError("SECRET_KEY must be configured outside development.")
app.config.update(
    SECRET_KEY=SECRET_KEY,
    WTF_CSRF_TIME_LIMIT=None,
)
csrf = CSRFProtect(app)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", db.DEFAULT_DATABASE_URL)
db.init_db(DATABASE_URL)

_prediction_cache = {
    "database_url": None,
    "engines": {},
}


@app.after_request
def add_security_headers(response):
    """Add browser security headers to every response."""
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    return response


@app.errorhandler(400)
def handle_bad_request(error):
    """Return a JSON or HTML response for a malformed request."""
    if request.is_json:
        return jsonify({"success": False, "error": "The request could not be processed."}), 400
    return render_template("error.html", status_code=400, message="The request could not be processed."), 400


@app.errorhandler(404)
def handle_not_found(error):
    """Return a JSON or HTML response when a requested page is missing."""
    if request.is_json:
        return jsonify({"success": False, "error": "The requested resource was not found."}), 404
    return render_template("error.html", status_code=404, message="The requested page was not found."), 404


@app.errorhandler(500)
def handle_server_error(error):
    """Log an unexpected error and return a JSON or HTML error response."""
    logger.exception("Unhandled application error")
    if request.is_json:
        return jsonify({"success": False, "error": "An unexpected server error occurred."}), 500
    return render_template("error.html", status_code=500, message="An unexpected server error occurred."), 500


def spreadsheet_safe(value):
    """Prevent exported text from being interpreted as a spreadsheet formula."""
    if isinstance(value, (list, tuple)):
        value = ", ".join(str(item) for item in value)
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


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
    """Return the saved details for the project named in the request."""
    project_name = request.args.get("name")
    if not project_name:
        return jsonify({"success": False, "error": "No project name provided"})

    data = db.get_project(project_name, DATABASE_URL)
    if data:
        return jsonify({"success": True, "data": data})
    return jsonify({"success": False, "error": "Project not found"})


@app.route("/export", methods=["POST"])
def export_projects():
    """Create a CSV or Excel download from authoritative database records."""
    data = request.get_json(silent=True) or {}
    project_ids = data.get("project_ids")
    export_format = data.get("format", "xlsx").lower()

    if not isinstance(project_ids, list) or not project_ids:
        return jsonify({"success": False, "error": "No projects were provided for export."}), 400
    if export_format not in {"csv", "xlsx"}:
        return jsonify({"success": False, "error": "Unsupported export format."}), 400

    try:
        project_ids = [int(project_id) for project_id in project_ids]
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "Project identifiers must be numeric."}), 400

    projects = db.get_projects_by_ids(project_ids, DATABASE_URL)

    columns = [
        "Project Name", "Project Type", "Sector", "Square Footage", "Levels",
        "Partition Density", "Site Condition", "Interior Scanned", "Exterior Scanned",
        "Roof Scanned", "Coverage", "Total Scans", "Updated",
        "Tags",
    ]
    rows = [[spreadsheet_safe(project.get(key, "")) for key in [
        "project_name", "project_type", "sector", "sqft", "levels",
        "partition_density", "site_condition", "interior", "exterior",
        "roof", "coverage", "scan_count", "timestamp",
        "tags",
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
        try:
            normalized = validation.validate_prediction(data)
            input_data = {
                "Project Type": normalized["project_type"],
                "Sector": normalized["sector"],
                "Sqft": normalized["sqft"],
                "Levels": normalized["levels"],
                "Partition Density": normalized["partition_density"],
                "Site Condition": normalized["site_condition"],
                "Interior": normalized["interior"],
                "Exterior": normalized["exterior"],
                "Roof": normalized["roof"],
                "Coverage": normalized["coverage"],
            }
        except validation.ValidationError:
            return jsonify({"success": False, "error": "Complete the fields with valid values before requesting an estimate."}), 400

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
        logger.exception("Prediction failed")
        return jsonify({"success": False, "error": "The estimate could not be generated from the current data."}), 500


@app.route("/delete", methods=["POST"])
def delete_project():
    """Delete a project by identifier and clear cached predictions."""
    try:
        data = request.get_json(silent=True) or {}
        project_id = data.get("id")
        if project_id is None and data.get("project_name"):
            legacy_project = db.get_project(data["project_name"], DATABASE_URL)
            project_id = legacy_project["id"] if legacy_project else None
        project_id = int(project_id)
        
        if project_id <= 0:
            raise ValueError
        
        success = db.delete_project_by_id(project_id, DATABASE_URL)
        
        if success:
            _prediction_cache["engines"] = {}
            return jsonify({"success": True, "message": "Project deleted successfully"})
        return jsonify({"success": False, "error": "Project not found."}), 404
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "A valid project identifier is required."}), 400
    except Exception as exc:
        logger.exception("Error deleting project")
        return jsonify({"success": False, "error": "The project could not be deleted."}), 500


@app.route("/delete/<int:project_id>", methods=["POST"])
def delete_project_form(project_id):
    """Delete a project from the form route and redirect to the dashboard."""
    try:
        if not db.delete_project_by_id(project_id, DATABASE_URL):
            return redirect(url_for("home"))
        _prediction_cache["engines"] = {}
        return redirect(url_for("home"))
    except Exception:
        logger.exception("Form delete failed")
        return render_template("error.html", status_code=500, message="The project could not be deleted."), 500


@app.route("/submit", methods=["POST"])
def submit():
    """Validate and save a submitted project, or return its errors to the form."""
    try:
        values = validation.validate_project(request.form.to_dict())
        db.upsert_project(values, DATABASE_URL)
        _prediction_cache["engines"] = {}
        return redirect(url_for("home"))
    except validation.ValidationError as exc:
        return render_template(
            "form.html",
            projects=db.project_names(DATABASE_URL),
            errors=exc.errors,
            form_values=request.form.to_dict(),
        ), 400
    except Exception as exc:
        logger.exception("Unexpected error in /submit")
        return render_template("error.html", status_code=500, message="The job could not be saved."), 500


if __name__ == "__main__":
    host = os.getenv("APP_HOST", "127.0.0.1")
    port = int(os.getenv("APP_PORT", "5000"))
    debug = os.getenv("FLASK_DEBUG", "0").strip().lower() in {"1", "true", "yes"}
    app.run(host=host, port=port, debug=debug)