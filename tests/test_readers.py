import zipfile
from dataclasses import replace

import fiona
import pytest
from shapely.geometry import Polygon, mapping

from app.config import Settings
from app.errors import InputError
from app.geo.readers import read_kml, read_shapefile
from app.processing import process_file


def make_shapefile(tmp_path, crs="EPSG:4326"):
    folder = tmp_path / "source"
    folder.mkdir()
    with fiona.open(
        folder / "plot.shp",
        "w",
        driver="ESRI Shapefile",
        crs=crs,
        schema={"geometry": "Polygon", "properties": {"name": "str"}},
    ) as dst:
        dst.write(
            {
                "geometry": mapping(
                    Polygon([(77, 12), (77.001, 12), (77.001, 12.001), (77, 12.001), (77, 12)])
                ),
                "properties": {"name": "test"},
            }
        )
    path = tmp_path / "survey.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for child in folder.iterdir():
            archive.write(child, "nested/" + child.name)
    return path


def test_real_shapefile_roundtrip(tmp_path):
    path = make_shapefile(tmp_path)
    crs, features = process_file(str(path), ".zip", None, Settings())
    assert crs == "EPSG:4326"
    assert features[0]["properties"]["name"] == "test"
    assert features[0]["measurement_status"] == "MEASURED"


@pytest.mark.parametrize(
    "name", ["../escape.shp", "/absolute.shp", "C:/evil.shp", "nested\\evil.shp"]
)
def test_zip_traversal(tmp_path, name):
    path = tmp_path / "bad.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(name, b"bad")
    with pytest.raises(InputError, match="Unsafe"):
        read_shapefile(path, tmp_path / "extract", None, Settings())


def test_zip_expansion_limit(tmp_path):
    path = tmp_path / "bad.zip"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("a.shp", b"x" * 1000)
    with pytest.raises(InputError) as exc:
        read_shapefile(path, tmp_path / "extract", None, replace(Settings(), expanded_bytes=100))
    assert exc.value.status == 413


def test_missing_crs_requires_override(tmp_path):
    path = make_shapefile(tmp_path, crs=None)
    with pytest.raises(InputError) as exc:
        process_file(str(path), ".zip", None, Settings())
    assert exc.value.code == "MISSING_CRS"
    assert process_file(str(path), ".zip", "EPSG:4326", Settings())[0] == "EPSG:4326"


def test_xml_entities_blocked(tmp_path):
    path = tmp_path / "evil.kml"
    path.write_text(
        '<!DOCTYPE kml [<!ENTITY x "secret">]><kml><Placemark><name>&x;</name></Placemark></kml>'
    )
    with pytest.raises(InputError) as exc:
        read_kml(path, None, Settings())
    assert exc.value.code == "INVALID_KML"


def test_kml_nested_and_bad_feature_isolation(tmp_path):
    path = tmp_path / "survey.kml"
    path.write_text(
        '<kml><Document><Folder><Placemark id="good"><Point><coordinates>77,12,50</coordinates></Point></Placemark><Placemark id="bad"><LineString><coordinates>bad</coordinates></LineString></Placemark></Folder></Document></kml>'
    )
    _, features = process_file(str(path), ".kml", None, Settings())
    assert len(features) == 2
    assert features[0]["geometry"]["coordinates"] == [77, 12, 50]
    assert features[1]["measurement_status"] == "INVALID_OR_UNSUPPORTED_GEOMETRY"


def test_zip_symlink(tmp_path):
    import stat

    path = tmp_path / "symlink.zip"
    info = zipfile.ZipInfo("link.shp")
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(info, "/etc/passwd")
    with pytest.raises(InputError) as exc:
        process_file(str(path), ".zip", None, Settings())
    assert exc.value.code == "UNSAFE_ZIP"


def test_multiple_datasets_rejected(tmp_path):
    path = tmp_path / "multiple.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("a.shp", b"x")
        archive.writestr("b.shp", b"x")
    with pytest.raises(InputError) as exc:
        process_file(str(path), ".zip", None, Settings())
    assert exc.value.code == "AMBIGUOUS_DATASET"


def test_kml_feature_limit(tmp_path):
    path = tmp_path / "many.kml"
    path.write_text("<kml>" + "<Placemark/>" * 3 + "</kml>")
    with pytest.raises(InputError) as exc:
        process_file(str(path), ".kml", None, replace(Settings(), features=2))
    assert exc.value.code == "FEATURE_LIMIT"


def test_unsupported_track_preserves_source(tmp_path):
    path = tmp_path / "track.kml"
    path.write_text(
        '<kml xmlns:gx="http://www.google.com/kml/ext/2.2"><Placemark><gx:Track><gx:coord>77 12 0</gx:coord></gx:Track></Placemark></kml>'
    )
    _, features = process_file(str(path), ".kml", None, Settings())
    assert features[0]["geometry_type"] == "Track"
    assert "Track" in features[0]["source_geometry_xml"]


def test_network_link_is_not_silently_fetched(tmp_path):
    path = tmp_path / "remote.kml"
    path.write_text(
        "<kml><NetworkLink><Link><href>https://example.com/secret</href></Link></NetworkLink></kml>"
    )
    with pytest.raises(InputError) as exc:
        process_file(str(path), ".kml", None, Settings())
    assert exc.value.code == "UNSUPPORTED_KML_REFERENCE"
