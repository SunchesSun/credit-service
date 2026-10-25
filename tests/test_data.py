import pandas as pd
import pandera.pandas as pa
import pytest

from credit_service.data import ROW_SCHEMA, clean_data, validate_data


@pytest.fixture()
def sample():
    return pd.DataFrame([
        {
            "Unnamed: 0": index,
            "Age": 35,
            "Sex": "female",
            "Job": 2,
            "Housing": "own",
            "Saving accounts": None,
            "Checking account": "little",
            "Credit amount": 1500,
            "Duration": 12,
            "Purpose": "car",
            "Risk": "bad" if index < 3 else "good",
        }
        for index in range(10)
    ])


def test_good_rows_pass(sample):
    result = ROW_SCHEMA.validate(clean_data(sample), lazy=True)
    assert len(result) == 10


@pytest.mark.parametrize("column,value", [
    ("Age", 0),
    ("Age", 120),
    ("Age", 35.5),
    ("Credit amount", -1),
    ("Duration", 0),
    ("Sex", "unknown"),
    ("Risk", "unknown"),
])
def test_corrupt_value_is_rejected(sample, column, value):
    # Для дробного возраста явно меняем тип, чтобы pandas 3 принял испорченное значение.
    if isinstance(value, float):
        sample[column] = sample[column].astype(float)
    sample.loc[0, column] = value
    with pytest.raises(pa.errors.SchemaErrors):
        ROW_SCHEMA.validate(clean_data(sample), lazy=True)


def test_duplicate_record_id_is_rejected(sample):
    sample.loc[1, "Unnamed: 0"] = sample.loc[0, "Unnamed: 0"]
    with pytest.raises(pa.errors.SchemaErrors) as error:
        ROW_SCHEMA.validate(clean_data(sample), lazy=True)
    assert "field_uniqueness" in error.value.failure_cases["check"].tolist()


def test_small_batch_is_rejected(sample):
    with pytest.raises(pa.errors.SchemaErrors) as error:
        validate_data(clean_data(sample))
    assert "minimum_rows" in error.value.failure_cases["check"].tolist()


def full_batch(sample):
    frame = pd.concat([sample] * 80, ignore_index=True)
    frame["Unnamed: 0"] = range(len(frame))
    return clean_data(frame)


def test_full_batch_passes(sample):
    assert len(validate_data(full_batch(sample))) == 800


def test_values_outside_observed_csv_ranges_pass(sample):
    frame = full_batch(sample)
    frame.loc[0, ["age", "credit_amount", "duration"]] = [76, 20_000, 73]
    assert len(validate_data(frame)) == 800


def test_single_class_batch_is_rejected(sample):
    frame = full_batch(sample)
    frame["risk"] = "good"
    with pytest.raises(pa.errors.SchemaErrors) as error:
        validate_data(frame)
    assert "bad_share" in error.value.failure_cases["check"].tolist()
