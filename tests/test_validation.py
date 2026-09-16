import pandas as pd

import model
import validation


def test_project_tags_are_normalized_per_project():
    """Verify that duplicate tags are removed without changing their first spelling."""
    assert validation.parse_tags("windmill_blade, exterior, WINDMILL_BLADE") == ["windmill_blade", "exterior"]


def test_project_tags_reject_blank_entries():
    """Verify that an empty tag between commas is rejected."""
    try:
        validation.parse_tags("windmill_blade, , exterior")
        assert False, "Expected blank tag entry to be rejected"
    except ValueError:
        pass


def test_decide_validation_strategy_requires_minimum_data():
    """Verify that too few records make prediction validation ineligible."""
    df = pd.DataFrame([
        {
            'Project Type': 'building',
            'Sector': 'residential',
            'Sqft': 1000,
            'Levels': 2,
            'Partition Density': 5,
            'Site Condition': 2,
            'Interior': 'y',
            'Exterior': 'y',
            'Roof': 'n',
            'Coverage': 0.9,
            'Total Scans': 12,
        }
    ])

    result = model.decide_validation_strategy(df)
    assert result['eligible'] is False
    assert result['strategy'] == 'insufficient_data'


def test_decide_validation_strategy_uses_leave_one_out_for_small_dataset():
    """Verify that a small eligible dataset uses leave-one-out validation."""
    rows = []
    for i in range(6):
        rows.append({
            'Project Type': 'building',
            'Sector': 'residential',
            'Sqft': 1000 + i * 100,
            'Levels': 2,
            'Partition Density': 5,
            'Site Condition': 2,
            'Interior': 'y',
            'Exterior': 'y',
            'Roof': 'n',
            'Coverage': 0.9,
            'Total Scans': 12 + i,
        })

    df = pd.DataFrame(rows)
    result = model.decide_validation_strategy(df)
    assert result['eligible'] is True
    assert result['strategy'] == 'leave_one_out'


def test_validate_training_data_rejects_missing_required_fields():
    """Verify that training data without required fields is rejected."""
    df = pd.DataFrame({'Project Type': ['building']})

    try:
        model.validate_training_data(df)
        assert False, 'Expected ValueError when required fields are missing'
    except ValueError:
        pass
