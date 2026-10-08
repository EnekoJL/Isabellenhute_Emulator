"""CsvProfileAdapter (plan section 3.4) using tmp_path files."""

from __future__ import annotations

import pytest

csv_reader = pytest.importorskip("isascale.infrastructure.adapters.csv_reader")
CsvProfileAdapter = csv_reader.CsvProfileAdapter

from isascale.domain.models import CurrentProfile  # noqa: E402
from isascale.ports.profile_port import ProfileFormatError, ProfileReaderPort  # noqa: E402


@pytest.fixture
def reader() -> CsvProfileAdapter:
    return CsvProfileAdapter()


@pytest.fixture
def write(tmp_path):
    def _write(content: str, name: str = "profile.csv"):
        path = tmp_path / name
        path.write_text(content, encoding="utf-8")
        return path

    return _write


def test_is_profile_reader_port(reader):
    assert isinstance(reader, ProfileReaderPort)


def test_current_in_amps_is_converted_to_ma(reader, write):
    profile = reader.load_profile(write("time,current\n0,0\n1,10.5\n2,-20\n", name="wot_lap.csv"))
    assert isinstance(profile, CurrentProfile)
    assert profile.name == "wot_lap"
    assert profile.points == ((0.0, 0.0), (1.0, 10_500.0), (2.0, -20_000.0))


def test_current_in_ma(reader, write):
    profile = reader.load_profile(write("time,current_ma\n0,100\n0.5,-35000\n"))
    assert profile.points == ((0.0, 100.0), (0.5, -35_000.0))


def test_accepts_str_path(reader, write):
    assert reader.load_profile(str(write("time,current\n0,1\n1,2\n"))).duration_s == 1.0


def test_comments_are_ignored(reader, write):
    content = "# exported from logger\ntime,current\n# start\n0,1\n1,2 # trailing\n2,3\n"
    assert [i for _, i in reader.load_profile(write(content)).points] == [1000.0, 2000.0, 3000.0]


@pytest.mark.parametrize("header", [" time , current ", "TIME,Current", "Time , CURRENT"])
def test_headers_are_trimmed_and_case_insensitive(reader, write, header):
    profile = reader.load_profile(write(f"{header}\n0,1\n1,2\n"))
    assert profile.points == ((0.0, 1000.0), (1.0, 2000.0))


def test_extra_columns_ignored(reader, write):
    profile = reader.load_profile(write("time,voltage,current\n0,400,1\n1,399,2\n"))
    assert profile.points == ((0.0, 1000.0), (1.0, 2000.0))


def test_profile_interpolates(reader, write):
    profile = reader.load_profile(write("time,current\n0,0\n2,100\n"))
    assert profile.current_at(1.0) == pytest.approx(50_000.0)


@pytest.mark.parametrize(
    "content",
    [
        pytest.param("t,current\n0,1\n1,2\n", id="no-time-column"),
        pytest.param("time,amps\n0,1\n1,2\n", id="no-current-column"),
        pytest.param("time\n0\n1\n", id="only-time"),
        pytest.param("time,current\n0,abc\n1,2\n", id="non-numeric-current"),
        pytest.param("time,current\nzero,1\n1,2\n", id="non-numeric-time"),
        pytest.param("time,current\n0,\n1,2\n", id="nan-current"),
        pytest.param("time,current\n,1\n1,2\n", id="nan-time"),
        pytest.param("time,current\n0,1\n", id="one-row"),
        pytest.param("time,current\n", id="no-rows"),
        pytest.param("", id="empty-file"),
        pytest.param("time,current\n0,1\n1,2\n1,3\n", id="time-repeated"),
        pytest.param("time,current\n0,1\n2,2\n1,3\n", id="time-decreasing"),
        pytest.param("time,current\n-1,1\n1,2\n", id="negative-time"),
    ],
)
def test_invalid_files_raise_profile_format_error(reader, write, content):
    with pytest.raises(ProfileFormatError):
        reader.load_profile(write(content))


def test_missing_file_raises_profile_format_error(reader, tmp_path):
    with pytest.raises(ProfileFormatError):
        reader.load_profile(tmp_path / "does_not_exist.csv")


def test_directory_raises_profile_format_error(reader, tmp_path):
    with pytest.raises(ProfileFormatError):
        reader.load_profile(tmp_path)


def test_current_ma_wins_when_both_columns_present(reader, write):
    profile = reader.load_profile(write("time,current,current_ma\n0,1,5\n1,2,6\n"))
    assert [i for _, i in profile.points] == [5.0, 6.0]


@pytest.mark.parametrize("value", ["inf", "-inf"])
def test_infinite_values_rejected(reader, write, value):
    with pytest.raises(ProfileFormatError):
        reader.load_profile(write(f"time,current\n0,{value}\n1,2\n"))
