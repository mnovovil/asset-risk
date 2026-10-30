import pytest

from engine.ingest import PortfolioError, read_portfolio


def write(tmp_path, content: str | bytes):
    path = tmp_path / "portfolio.csv"
    path.write_bytes(content if isinstance(content, bytes) else content.encode())
    return path


def test_reads_rows_in_input_order(tmp_path):
    path = write(tmp_path, "id,lat,lon\nb,1.5,2.5\na,3.5,4.5\n")
    assert read_portfolio(path, 10) == [("b", "1.5", "2.5"), ("a", "3.5", "4.5")]


@pytest.mark.parametrize(
    "content",
    [
        "ID,Lat,LON\na,1,2\n",
        " id , lat , lon \na,1,2\n",
        "lon,id,lat\n2,a,1\n",
        "id,lat,lon,note\na,1,2,extra\n",
        b"\xef\xbb\xbfid,lat,lon\na,1,2\n",
        "id,lat,lon\r\na,1,2\r\n",
    ],
)
def test_accepts_header_variations(tmp_path, content):
    assert read_portfolio(write(tmp_path, content), 10) == [("a", "1", "2")]


def test_missing_columns_are_named(tmp_path):
    with pytest.raises(PortfolioError, match="lon"):
        read_portfolio(write(tmp_path, "id,lat\na,1\n"), 10)


def test_missing_file(tmp_path):
    with pytest.raises(PortfolioError, match="not found"):
        read_portfolio(tmp_path / "nope.csv", 10)


@pytest.mark.parametrize("content", ["", "id,lat,lon\n"])
def test_no_rows(tmp_path, content):
    with pytest.raises(PortfolioError):
        read_portfolio(write(tmp_path, content), 10)


def test_binary_file_is_rejected(tmp_path):
    with pytest.raises(PortfolioError):
        read_portfolio(write(tmp_path, b"\x89PNG\r\n\x1a\n\x00\xff\xfe\x00"), 10)


def test_duplicates_are_named(tmp_path):
    with pytest.raises(PortfolioError, match="Duplicate ids.*a"):
        read_portfolio(write(tmp_path, "id,lat,lon\na,1,2\nb,1,2\na,3,4\n"), 10)


def test_duplicates_ignore_surrounding_space(tmp_path):
    with pytest.raises(PortfolioError, match="Duplicate"):
        read_portfolio(write(tmp_path, 'id,lat,lon\na,1,2\n" a ",3,4\n'), 10)


def test_long_duplicate_lists_are_shortened(tmp_path):
    rows = "".join(f"d{i},1,2\nd{i},1,2\n" for i in range(8))
    with pytest.raises(PortfolioError, match="and 3 more"):
        read_portfolio(write(tmp_path, f"id,lat,lon\n{rows}"), 100)


def test_blank_ids_are_not_duplicates(tmp_path):
    points = read_portfolio(write(tmp_path, "id,lat,lon\n,1,2\n,3,4\n"), 10)
    assert len(points) == 2


def test_bad_rows_do_not_stop_the_run(tmp_path):
    points = read_portfolio(write(tmp_path, "id,lat,lon\na,95,2\nb,abc,2\nc,1,\n"), 10)
    assert [p[0] for p in points] == ["a", "b", "c"]


def test_row_limit(tmp_path):
    path = write(tmp_path, "id,lat,lon\na,1,2\nb,1,2\nc,1,2\n")
    assert len(read_portfolio(path, 3)) == 3
    with pytest.raises(PortfolioError, match="3 rows; the limit is 2"):
        read_portfolio(path, 2)
