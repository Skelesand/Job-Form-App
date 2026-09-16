import pandas as pd
import numpy as np
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.neighbors import NearestNeighbors
from sklearn.metrics import mean_absolute_error, mean_absolute_percentage_error
from sklearn.ensemble import RandomForestRegressor

'''
Global config & settings
These settings tell the system what data to look at and how much importance (weight)
to give to different features when matching projects

The higher the weight the more distance it will put between itself
and any neighbors that do not have the same value of that feature
'''


FEATURE_WEIGHTS = {
    'Project Type': 22.41,
    'Sector': 10.99,
    'Sqft_Log': 13.11,
    'Levels': 9.51,
    'Partition Density': 12.31,
    'Site Condition': 8.91,
    'Interior': 12.02,
    'Exterior': 11.64,
    'Roof': 1.90
}

CATEGORICAL_COLS = ['Project Type', 'Sector', 'Interior', 'Exterior', 'Roof']
NUMERIC_COLS = ['Sqft_Log', 'Levels', 'Partition Density', 'Site Condition']
REQUIRED_INPUT_COLUMNS = CATEGORICAL_COLS + ['Sqft', 'Levels', 'Partition Density', 'Site Condition']

file_path = 'data\\Scan_Log_Dataset.xlsx'


# Data Standardization Tool
def clean_text_values(series):
    """Standardize text values and common yes-or-no spellings in a data series."""
    return series.astype(str).str.strip().str.lower().replace({
        'yes': 'y', 'true': 'y', '1': 'y', '1.0': 'y',
        'no': 'n', 'false': 'n', '0': 'n', '0.0': 'n',
        'nan': 'missing', 'none': 'missing'
    })


def validate_required_columns(df, required_columns):
    """Raise an error when a data frame is missing any required columns."""
    missing = [col for col in required_columns if col not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns for model input: {missing}")


def prepare_model_features(df):
    """Normalize raw feature columns so the model can validate and train on the same schema."""
    df = df.copy()
    if 'Sqft' in df.columns:
        df['Sqft'] = pd.to_numeric(df['Sqft'], errors='coerce').fillna(1.0)
        df.loc[df['Sqft'] <= 0, 'Sqft'] = 1.0
        df['Sqft_Log'] = np.log1p(df['Sqft'])

    for col in CATEGORICAL_COLS:
        if col in df.columns:
            df[col] = clean_text_values(df[col])

    for col in NUMERIC_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    return df


def validate_training_data(df):
    """Validate that the training data has the fields and minimum quality needed for prediction."""
    required = [
        'Project Type', 'Sector', 'Sqft', 'Levels', 'Partition Density',
        'Site Condition', 'Interior', 'Exterior', 'Roof', 'Coverage', 'Total Scans'
    ]
    validate_required_columns(df, required)

    if df.empty:
        raise ValueError('Training data is empty.')

    if df['Total Scans'].dropna().empty:
        raise ValueError('No valid Total Scans values are available.')

    numeric_fields = ['Sqft', 'Levels', 'Partition Density', 'Site Condition', 'Coverage', 'Total Scans']
    for field in numeric_fields:
        if field in df.columns:
            converted = pd.to_numeric(df[field], errors='coerce')
            if converted.isna().all():
                raise ValueError(f'Column {field} does not contain usable numeric data.')

    if 'Project Type' in df.columns:
        types = df['Project Type'].dropna().astype(str).str.strip().str.lower()
        if types.empty:
            raise ValueError('Project Type column is empty.')

    return True


def decide_validation_strategy(df, min_records_for_prediction=10, min_records_for_split=20):
    """Choose a validation strategy based on data availability and project-type sample size."""
    validate_training_data(df)
    total_records = len(df)

    if total_records < min_records_for_prediction:
        return {
            'eligible': False,
            'strategy': 'insufficient_data',
            'message': f'At least {min_records_for_prediction} valid records are required before predictions can be trusted.',
            'record_count': total_records,
        }

    if total_records < min_records_for_split:
        return {
            'eligible': True,
            'strategy': 'leave_one_out',
            'message': 'Dataset is small; leave-one-out validation is the safest available option.',
            'record_count': total_records,
        }

    return {
        'eligible': True,
        'strategy': 'k_fold',
        'message': 'Dataset is large enough for grouped cross-validation.',
        'record_count': total_records,
    }


def calculate_adaptive_gamma(train_weighted_features, n_neighbors=3):
    """Calculate a confidence scale from the distances between nearby training records."""
    nn = NearestNeighbors(n_neighbors=n_neighbors + 1, metric='cosine')
    nn.fit(train_weighted_features)
    distances, _ = nn.kneighbors(train_weighted_features)
    mean_neighbor_dist = np.mean(distances[:, 1:])
    return 1.0 / (mean_neighbor_dist + 1e-5) if mean_neighbor_dist > 0 else 2.5


def calculate_confidence(avg_distance, gamma):
    """Convert an average match distance into a confidence percentage from 0 to 100."""
    confidence = np.exp(-gamma * avg_distance) * 100
    return np.clip(confidence, 0, 100)


# Opens tracking sheets, filters empty rows, and isolates coverage from raw square footage
def load_and_prepare_data(project_type=None, filepath=None):
    """Load historical scan data, clean its fields, and optionally filter by project type."""
    data_path = filepath or file_path
    try:
        df = pd.read_excel(data_path)
    except FileNotFoundError:
        try:
            df = pd.read_csv(data_path)
        except FileNotFoundError as exc:
            raise FileNotFoundError(f"Data file not found at: {data_path}") from exc
    except ValueError:
        try:
            df = pd.read_csv(data_path)
        except Exception as exc:
            raise ValueError(f"Could not read data file at: {data_path}") from exc

    # Validate and clean Total Scans
    df['Total Scans'] = pd.to_numeric(df['Total Scans'], errors='coerce')
    df = df.dropna(subset=['Total Scans'])
    df = df[df['Total Scans'] > 0].copy()

    # Isolate scan coverage mechanics from asset matching metrics
    df['Coverage'] = pd.to_numeric(df.get('Coverage', 1.0), errors='coerce').fillna(1.0)
    df.loc[df['Coverage'] <= 0, 'Coverage'] = 1.0

    # Ground truth actual scans remain pristine
    df['Raw_Scans_Actual'] = df['Total Scans']

    # Handle asset physical scale without letting coverage deform it
    df['Sqft'] = pd.to_numeric(df['Sqft'], errors='coerce').fillna(1.0)
    df.loc[df['Sqft'] <= 0, 'Sqft'] = 1.0

    # Log footprint maps to the true total physical asset scale for proper neighbor comparison
    df['Sqft_Log'] = np.log1p(df['Sqft'])

    # Track the operational area that was physically captured to calculate accurate rates
    df['Scanned_Sqft'] = df['Sqft'] * df['Coverage']

    # Standardize text data tables
    for col in CATEGORICAL_COLS:
        if col in df.columns:
            df[col] = clean_text_values(df[col])

    for col in NUMERIC_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    # Keep comparisons within the requested project type.
    if 'Project Type' in df.columns and project_type is not None:
        normalized_type = clean_text_values(pd.Series([project_type])).iloc[0]
        df = df[df['Project Type'] == normalized_type]

    return df.reset_index(drop=True)


def load_and_prepare_records(records, project_type=None):
    """Prepare database records using the same transformations as Excel data."""
    df = pd.DataFrame(records)
    if df.empty:
        return df

    df['Total Scans'] = pd.to_numeric(df['Total Scans'], errors='coerce')
    df = df.dropna(subset=['Total Scans'])
    df = df[df['Total Scans'] > 0].copy()
    df['Coverage'] = pd.to_numeric(df.get('Coverage', 1.0), errors='coerce').fillna(1.0)
    df.loc[df['Coverage'] <= 0, 'Coverage'] = 1.0
    df['Raw_Scans_Actual'] = df['Total Scans']
    df['Sqft'] = pd.to_numeric(df['Sqft'], errors='coerce').fillna(1.0)
    df.loc[df['Sqft'] <= 0, 'Sqft'] = 1.0
    df['Sqft_Log'] = np.log1p(df['Sqft'])
    df['Scanned_Sqft'] = df['Sqft'] * df['Coverage']

    for col in CATEGORICAL_COLS:
        if col in df.columns:
            df[col] = clean_text_values(df[col])
    for col in NUMERIC_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    if 'Project Type' in df.columns and project_type is not None:
        normalized_type = clean_text_values(pd.Series([project_type])).iloc[0]
        df = df[df['Project Type'] == normalized_type]
    return df.reset_index(drop=True)


def _detect_feature_family(feature_name):
    """Map transformed feature names back to their conceptual family."""
    normalized = feature_name.lower()
    if 'project type' in normalized:
        return 'Project Type'
    if 'sector' in normalized:
        return 'Sector'
    if 'interior' in normalized:
        return 'Interior'
    if 'exterior' in normalized:
        return 'Exterior'
    if 'roof' in normalized:
        return 'Roof'
    if 'sqft' in normalized:
        return 'Sqft_Log'
    if 'levels' in normalized:
        return 'Levels'
    if 'partition density' in normalized:
        return 'Partition Density'
    if 'site condition' in normalized:
        return 'Site Condition'
    return None


def learn_feature_weights(feature_names, X_processed, target_values):
    """Learn a weight vector from historical scan counts and fall back to the legacy static weights if needed."""
    if len(target_values) < 5 or X_processed.shape[1] == 0:
        return np.ones(len(feature_names), dtype=float)

    try:
        model = RandomForestRegressor(
            n_estimators=200,
            random_state=42,
            min_samples_leaf=max(1, min(3, len(target_values) // 20))
        )
        model.fit(X_processed, np.log1p(np.asarray(target_values, dtype=float)))
        importances = model.feature_importances_
        if not np.all(np.isfinite(importances)) or np.sum(importances) <= 0:
            raise ValueError('Importance values are invalid.')

        family_importances = {}
        for name, importance in zip(feature_names, importances):
            family = _detect_feature_family(name)
            if family is None:
                continue
            family_importances.setdefault(family, []).append(float(importance))

        if not family_importances:
            raise ValueError('No feature families were recognized for weighting.')

        weights = np.ones(len(feature_names), dtype=float)
        for i, name in enumerate(feature_names):
            family = _detect_feature_family(name)
            if family is None:
                continue
            weights[i] = float(np.mean(family_importances[family]))

        weights = np.clip(weights, 0.25, 5.0)
        weights = weights / np.mean(weights)
        return weights
    except Exception:
        legacy_weights = np.ones(len(feature_names), dtype=float)
        for i, name in enumerate(feature_names):
            for feature, weight in FEATURE_WEIGHTS.items():
                if feature in name:
                    if name.startswith('cat__'):
                        prefix = name.split('__')[1].split('_')[0]
                        cat_family_size = sum(1 for f in feature_names if f.startswith(f'cat__{prefix}'))
                        legacy_weights[i] = weight / np.sqrt(max(cat_family_size, 1))
                    else:
                        legacy_weights[i] = weight
                    break
        return legacy_weights


# Similarity Engine Builder
def build_similarity_engine(df):
    """Build the preprocessing and nearest-neighbor objects used to compare projects."""
    df = prepare_model_features(df)
    validate_required_columns(df, CATEGORICAL_COLS + NUMERIC_COLS)
    X = df[CATEGORICAL_COLS + NUMERIC_COLS].copy()

    numeric_transformer = Pipeline(steps=[
        ('imputer', SimpleImputer(strategy='median')),
        ('scaler', StandardScaler())
    ])

    categorical_transformer = Pipeline(steps=[
        ('imputer', SimpleImputer(strategy='constant', fill_value='missing')),
        ('onehot', OneHotEncoder(handle_unknown='ignore', sparse_output=False))
    ])

    preprocessor = ColumnTransformer(
        transformers=[
            ('cat', categorical_transformer, CATEGORICAL_COLS),
            ('num', numeric_transformer, NUMERIC_COLS)
        ])

    X_processed = preprocessor.fit_transform(X)
    feature_names = preprocessor.get_feature_names_out()
    weight_vector = learn_feature_weights(feature_names, X_processed, df['Total Scans'].values)

    X_weighted = X_processed * weight_vector

    # Using Cosine distance
    nn_model = NearestNeighbors(n_neighbors=3, metric='cosine')
    nn_model.fit(X_weighted)

    # Set up our dynamic, adaptive confidence reference scale
    gamma = calculate_adaptive_gamma(X_weighted, n_neighbors=3)

    return nn_model, preprocessor, weight_vector, gamma


# Look-Alike Predictor
def find_lookalike_jobs(new_job_df, historical_df, nn_model, preprocessor, weight_vector, gamma, n_neighbors=3):
    """Looks up matching jobs and projects scan demands via proximity scaling logic."""
    nn_model.set_params(n_neighbors=n_neighbors)

    temp_df = new_job_df.copy()
    validate_required_columns(temp_df, REQUIRED_INPUT_COLUMNS)

    # Apply raw square footage preprocessing to input
    temp_df['Sqft'] = pd.to_numeric(temp_df['Sqft'], errors='coerce').fillna(1.0)
    temp_df['Sqft_Log'] = np.log1p(temp_df['Sqft'])

    for col in CATEGORICAL_COLS:
        if col in temp_df.columns:
            temp_df[col] = clean_text_values(temp_df[col])

    new_job_processed = preprocessor.transform(temp_df[CATEGORICAL_COLS + NUMERIC_COLS])
    new_job_weighted = new_job_processed * weight_vector

    distances, indices = nn_model.kneighbors(new_job_weighted)
    matched_jobs = historical_df.iloc[indices[0]].copy()

    # INVERSE DISTANCE WEIGHTING (IDW) w/ coupling safe floor
    safe_distances = np.where(distances[0] == 0, 0.02, distances[0])
    raw_weights = 1.0 / safe_distances
    normalized_weights = raw_weights / np.sum(raw_weights)

    # Calculate historical scan density profiles based strictly on the area actually scanned
    matched_jobs['Scan_Rate'] = matched_jobs['Total Scans'] / np.where(matched_jobs['Scanned_Sqft'] > 0, matched_jobs['Scanned_Sqft'], 1)

    # INSULATION GUARDRAIL: scan rate outlier dampening
    rate_mean = matched_jobs['Scan_Rate'].mean()
    rate_std = matched_jobs['Scan_Rate'].std()
    if pd.notna(rate_std) and rate_std > 0:
        matched_jobs['Scan_Rate'] = matched_jobs['Scan_Rate'].clip(
            lower=max(0, rate_mean - (1.5 * rate_std)),
            upper=rate_mean + (1.5 * rate_std)
        )

    # Use weighted historical scan counts directly, then blend with a sqft-normalized estimate.
    weighted_total_scans = np.dot(matched_jobs['Total Scans'].values, normalized_weights)
    weighted_scan_rate = np.dot(matched_jobs['Scan_Rate'].values, normalized_weights)

    target_sqft = temp_df['Sqft'].values[0]
    requested_coverage = temp_df['Coverage'].values[0] if 'Coverage' in temp_df.columns else 1.0

    # Coverage is applied only as a final mild adjustment.
    area_adjusted_estimate = target_sqft * weighted_scan_rate
    blended_prediction = 0.6 * weighted_total_scans + 0.4 * area_adjusted_estimate

    # Apply small coverage influence without exploding the estimate.
    final_prediction = blended_prediction * (0.9 + 0.2 * requested_coverage)

    # Prevent pathological low or high predictions from extreme outliers.
    if np.isfinite(final_prediction):
        lower_bound = max(0.0, np.min(matched_jobs['Total Scans'].values) * 0.5)
        upper_bound = max(np.max(matched_jobs['Total Scans'].values) * 1.8, lower_bound + 1.0)
        final_prediction = float(np.clip(final_prediction, lower_bound, upper_bound))

    # Derive Confidence Score using our adaptive gamma metric
    avg_dist = np.mean(distances[0])
    confidence_score = calculate_confidence(avg_dist, gamma)

    matched_jobs['Match_Distance'] = distances[0]
    matched_jobs['Influence_Weight'] = normalized_weights

    return matched_jobs, final_prediction, confidence_score


# Leave-One-Out Validation Engine
def evaluate_via_cross_validation(df, n_neighbors=3):
    """Evaluate prediction accuracy by repeatedly comparing each record with the others."""
    strategy = decide_validation_strategy(df)
    if not strategy['eligible']:
        raise ValueError(strategy['message'])

    validation_strategy = strategy['strategy']
    print(f"Starting {validation_strategy} validation across {len(df)} records...")

    actual_scans, predicted_scans, job_names, confidences = [], [], [], []

    for i in range(len(df)):
        test_job = df.iloc[[i]].copy()
        train_df = df.drop(df.index[i]).reset_index(drop=True)

        try:
            engine, preprocessor, weight_vector, gamma = build_similarity_engine(train_df)
            matches, final_est, conf = find_lookalike_jobs(
                test_job, train_df, engine, preprocessor, weight_vector, gamma, n_neighbors=n_neighbors
            )

            actual_scans.append(test_job['Raw_Scans_Actual'].values[0])
            predicted_scans.append(final_est)
            job_names.append(test_job['Project Name'].values[0])
            confidences.append(conf)
        except Exception as exc:
            print(f"[Warning] Skipping validation row {i} ({test_job['Project Name'].values[0] if 'Project Name' in test_job.columns else i}): {exc}")
            continue

    actual = np.array(actual_scans)
    pred = np.array(predicted_scans)
    conf = np.array(confidences)

    # Calculate overall validation metrics
    mae = mean_absolute_error(actual, pred)
    mape = mean_absolute_percentage_error(actual, pred)

    # Filter arrays for Strength/Confidence >= 70%
    strong_mask = conf >= 70.0
    actual_strong = actual[strong_mask]
    pred_strong = pred[strong_mask]

    print("\n==================================================")
    print("              OVERALL VALIDATION METRICS          ")
    print("==================================================")
    print(f"Validation Strategy: {validation_strategy}")
    print(f"Mean Absolute Error: {mae:.1f} Scans")
    print(f"Mean Absolute Percentage Error: {mape * 100:.2f}%")
    print(f"Total Evaluated Records: {len(actual)}")

    print("\n==================================================")
    print("       HIGH CONFIDENCE METRICS (STRENGTH >= 70%)   ")
    print("==================================================")
    if len(actual_strong) > 0:
        mae_strong = mean_absolute_error(actual_strong, pred_strong)
        mape_strong = mean_absolute_percentage_error(actual_strong, pred_strong)
        print(f"MAE (Strong Matches): {mae_strong:.1f} Scans")
        print(f"MAPE (Strong Matches): {mape_strong * 100:.2f}%")
        print(f"High-Confidence Records: {len(actual_strong)} out of {len(actual)}")
    else:
        print("No scans reached a prediction strength of 70% or higher.")

    print("\n==================================================")
    print("       SAMPLE PERFORMANCE MATRIX OUTCOMES         ")
    print("==================================================")

    breakdown_df = pd.DataFrame({
        'Project Name': job_names,
        'Actual': np.round(actual, 1),
        'Predicted': np.round(pred, 1),
        '+/-': np.where(pred < actual, '-', '+'),
        'Error': np.round(np.abs(pred - actual), 1),
        'Raw_Confidence': confidences
    })

    breakdown_df = breakdown_df.sort_values(by='Raw_Confidence', ascending=False)
    breakdown_df['Strength'] = breakdown_df['Raw_Confidence'].apply(lambda c: f"{c:.1f}%")
    breakdown_df = breakdown_df.drop(columns=['Raw_Confidence'])

    print(breakdown_df.head(80).to_string(index=False))
    return {
        'strategy': validation_strategy,
        'record_count': len(actual),
        'mae': float(mae),
        'mape': float(mape),
        'eligible': True,
    }


# Execution Entry Point
if __name__ == "__main__":
    historical_database = load_and_prepare_data()

    if len(historical_database) < 5:
        print("Error: Critical lack of historical base parameters.")
    else:
        # Run validation check iteration
        evaluate_via_cross_validation(df=historical_database, n_neighbors=3)

        # Build core engine models using all available database elements
        engine, pipeline_transformer, final_weights, training_gamma = build_similarity_engine(historical_database)

        # Verify execution integrity using a sample lookup target profile
        incoming_rfq = pd.DataFrame([{
            'Project Type': 'building',
            'Sector': 'residential',
            'Sqft': 2500,
            'Levels': 3,
            'Partition Density': 9,
            'Site Condition': 2,
            'Interior': 'y',
            'Exterior': 'y',
            'Roof': 'n',
            'Coverage': 1.0
        }])

        matches, prediction, final_conf = find_lookalike_jobs(
            incoming_rfq, historical_database, engine, pipeline_transformer, final_weights, training_gamma, n_neighbors=3
        )

        print("\n==================================================")
        print(f" LIVE FINAL ESTIMATE  : {prediction:.1f} Scans")
        print(f" PREDICTION STRENGTH  : {final_conf:.1f}%")
        print("==================================================")
        display_cols = ['Project Name', 'Sqft', 'Coverage', 'Total Scans', 'Match_Distance', 'Influence_Weight']
        print(matches[[c for c in display_cols if c in matches.columns]].to_string(index=False))