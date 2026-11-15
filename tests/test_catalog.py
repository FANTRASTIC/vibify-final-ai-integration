import pytest

from src.catalog import CatalogError, catalog_stats, load_catalog

HEADER = "id,title,artist,genre,mood,energy,tempo_bpm,valence,danceability,acousticness\n"
GOOD = "1,A,X,pop,happy,0.5,100,0.5,0.5,0.5\n"


def write(tmp_path, body, header=HEADER):
    p = tmp_path / "c.csv"
    p.write_text(header + body, encoding="utf-8")
    return str(p)


def test_real_catalog_meets_requirements():
    songs = load_catalog("data/songs.csv")
    stats = catalog_stats(songs)
    assert len(songs) >= 48
    assert len(stats["genres"]) == 16 and min(stats["genres"].values()) >= 3
    assert max(stats["artists"].values()) <= 2


def test_original_rows_untouched():
    old = open("data/songs_v1.csv", "rb").read()
    new = open("data/songs.csv", "rb").read()
    assert new.startswith(old)


def test_valid_file(tmp_path):
    songs = load_catalog(write(tmp_path, GOOD))
    assert songs[0]["id"] == 1 and songs[0]["energy"] == 0.5


def test_missing_file():
    with pytest.raises(CatalogError, match="not found"):
        load_catalog("nope.csv")


def test_missing_column(tmp_path):
    with pytest.raises(CatalogError, match="missing required column"):
        load_catalog(write(tmp_path, "1,A\n", header="id,title\n"))


def test_duplicate_id_and_title(tmp_path):
    with pytest.raises(CatalogError, match="row 2, field 'id'"):
        load_catalog(write(tmp_path, GOOD + "1,B,Y,pop,happy,0.5,100,0.5,0.5,0.5\n"))
    with pytest.raises(CatalogError, match="row 2, field 'title'"):
        load_catalog(write(tmp_path, GOOD + "2,a,Y,pop,happy,0.5,100,0.5,0.5,0.5\n"))


@pytest.mark.parametrize("bad,field", [
    ("1,A,X,pop,happy,1.5,100,0.5,0.5,0.5\n", "energy"),
    ("1,A,X,pop,happy,0.5,100,-0.1,0.5,0.5\n", "valence"),
    ("1,A,X,pop,happy,0.5,100,0.5,2,0.5\n", "danceability"),
    ("1,A,X,pop,happy,0.5,100,0.5,0.5,9\n", "acousticness"),
    ("1,A,X,pop,happy,0.5,10,0.5,0.5,0.5\n", "tempo_bpm"),
    ("1,A,X,pop,happy,abc,100,0.5,0.5,0.5\n", "energy"),
    ("x,A,X,pop,happy,0.5,100,0.5,0.5,0.5\n", "id"),
    ("1,,X,pop,happy,0.5,100,0.5,0.5,0.5\n", "title"),
    ("1,A,X, ,happy,0.5,100,0.5,0.5,0.5\n", "genre"),
    ("1,A,X,pop,,0.5,100,0.5,0.5,0.5\n", "mood"),
    ("1,A,,pop,happy,0.5,100,0.5,0.5,0.5\n", "artist"),
])
def test_invalid_rows(tmp_path, bad, field):
    with pytest.raises(CatalogError, match=f"row 1, field '{field}'"):
        load_catalog(write(tmp_path, bad))


def test_stats(tmp_path):
    songs = load_catalog(write(tmp_path, GOOD + "2,B,X,pop,sad,0.5,100,0.5,0.5,0.5\n"))
    s = catalog_stats(songs)
    assert s["genres"] == {"pop": 2} and s["artists"] == {"X": 2} and s["moods"] == {"happy": 1, "sad": 1}
