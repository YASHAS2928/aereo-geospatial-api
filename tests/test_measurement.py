import pytest
from pyproj import Geod, Transformer
from shapely import transform
from shapely.geometry import LineString, Polygon, mapping

from app.geo.measurement import measure


@pytest.mark.parametrize("lon,lat", [(77.59, 12.97), (18, -33), (5.999, 0.001), (179.9, 20)])
def test_area_against_independent_ellipsoid(lon, lat):
    coords = [
        (lon, lat),
        (lon + 0.001, lat),
        (lon + 0.001, lat + 0.001),
        (lon, lat + 0.001),
        (lon, lat),
    ]
    expected = abs(Geod(ellps="WGS84").polygon_area_perimeter(*zip(*coords))[0])
    result = measure(mapping(Polygon(coords)), "EPSG:4326")
    assert result["measurement_status"] == "MEASURED"
    assert result["unit"] == "m2"
    assert result["value"] == pytest.approx(expected, rel=1e-6)


@pytest.mark.parametrize("lon,lat", [(77.59, 12.97), (18, -33), (5.999, -0.001)])
def test_line_against_geodesic(lon, lat):
    expected = Geod(ellps="WGS84").inv(lon, lat, lon + 0.002, lat + 0.002)[2]
    result = measure(mapping(LineString([(lon, lat), (lon + 0.002, lat + 0.002)])), 4326)
    assert result["value"] == pytest.approx(expected, rel=1e-6)


def test_projected_feet_input():
    polygon = Polygon([(-74, 40.7), (-73.999, 40.7), (-73.999, 40.701), (-74, 40.701), (-74, 40.7)])
    projector = Transformer.from_crs(4326, 2263, always_xy=True)
    feet = transform(polygon, projector.transform, interleaved=False)
    a = measure(mapping(polygon), 4326)
    b = measure(mapping(feet), 2263)
    assert b["value"] == pytest.approx(a["value"], rel=1e-7)


def test_holes_and_multipolygon():
    exterior = [(77, 12), (77.002, 12), (77.002, 12.002), (77, 12.002), (77, 12)]
    hole = [
        (77.0005, 12.0005),
        (77.0015, 12.0005),
        (77.0015, 12.0015),
        (77.0005, 12.0015),
        (77.0005, 12.0005),
    ]
    full = measure(mapping(Polygon(exterior)), 4326)["value"]
    part = measure(mapping(Polygon(hole)), 4326)["value"]
    actual = measure(mapping(Polygon(exterior, [hole])), 4326)["value"]
    assert actual == pytest.approx(full - part, rel=1e-6)


@pytest.mark.parametrize(
    "geometry,status",
    [
        (None, "EMPTY_GEOMETRY"),
        ({"type": "Point", "coordinates": [77, 12]}, "NOT_APPLICABLE"),
        (
            {
                "type": "GeometryCollection",
                "geometries": [{"type": "Point", "coordinates": [77, 12]}],
            },
            "UNSUPPORTED_GEOMETRY",
        ),
        (mapping(Polygon([(0, 0), (1, 1), (0, 1), (1, 0), (0, 0)])), "INVALID_GEOMETRY"),
        (mapping(LineString([(179, 0), (-179, 0)])), "UNSUPPORTED_CRS_EXTENT"),
    ],
)
def test_explicit_feature_statuses(geometry, status):
    result = measure(geometry, 4326)
    assert result["measurement_status"] == status
    assert result["value"] is None


def test_zone_and_equator_crossing_supported():
    line = {"type": "LineString", "coordinates": [[5.999, -0.001], [6.001, 0.001]]}
    actual = measure(line, 4326)
    expected = Geod(ellps="WGS84").inv(5.999, -0.001, 6.001, 0.001)[2]
    assert actual["measurement_status"] == "MEASURED"
    assert actual["value"] == pytest.approx(expected, rel=1e-6)


def test_multiline_sums_parts():
    first = [[77, 12], [77.001, 12]]
    second = [[77, 12.001], [77.001, 12.001]]
    actual = measure({"type": "MultiLineString", "coordinates": [first, second]}, 4326)
    expected = sum(Geod(ellps="WGS84").inv(*a, *b)[2] for a, b in [first, second])
    assert actual["value"] == pytest.approx(expected, rel=1e-6)


def test_known_equal_area_square():
    from pyproj import CRS

    crs = CRS.from_proj4("+proj=laea +lat_0=12 +lon_0=77 +datum=WGS84 +units=m")
    square = mapping(Polygon([(-50, -50), (50, -50), (50, 50), (-50, 50), (-50, -50)]))
    assert measure(square, crs)["value"] == pytest.approx(10000, rel=1e-6)


def test_known_three_four_five_line():
    from pyproj import CRS

    crs = CRS.from_proj4("+proj=aeqd +lat_0=12 +lon_0=77 +datum=WGS84 +units=m")
    line = {"type": "LineString", "coordinates": [[0, 0], [3, 4]]}
    assert measure(line, crs)["value"] == pytest.approx(5, rel=1e-7)
