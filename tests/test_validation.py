import pandas as pd

import model


def test_decide_validation_strategy_requires_minimum_data():
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
    df = pd.DataFrame({'Project Type': ['building']})

    try:
        model.validate_training_data(df)
        assert False, 'Expected ValueError when required fields are missing'
    except ValueError:
        pass
