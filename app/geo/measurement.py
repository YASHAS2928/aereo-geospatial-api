import math

import numpy as np
from pyproj import CRS, Transformer
from pyproj.exceptions import ProjError
from shapely import get_coordinates, transform
from shapely.errors import ShapelyError
from shapely.geometry import shape
from shapely.validation import explain_validity


def measure(geometry, source_crs):
    result = dict(
        measurement_status="NOT_APPLICABLE",
        measurement_type=None,
        value=None,
        unit=None,
        measurement_crs=None,
        warning_code=None,
    )
    if not geometry:
        return {**result, "measurement_status": "EMPTY_GEOMETRY"}
    try:
        geom = shape(geometry)
        if geom.is_empty:
            return {**result, "measurement_status": "EMPTY_GEOMETRY"}
        if not geom.is_valid:
            return {
                **result,
                "measurement_status": "INVALID_GEOMETRY",
                "warning_code": explain_validity(geom),
            }
        if geom.geom_type in ("Point", "MultiPoint"):
            return result
        if geom.geom_type not in ("Polygon", "MultiPolygon", "LineString", "MultiLineString"):
            return {**result, "measurement_status": "UNSUPPORTED_GEOMETRY"}
        to_wgs = Transformer.from_crs(source_crs, 4326, always_xy=True, allow_ballpark=False)
        wgs = transform(geom, lambda x, y: to_wgs.transform(x, y, errcheck=True), interleaved=False)
        west, south, east, north = wgs.bounds
        if not all(math.isfinite(v) for v in wgs.bounds):
            raise ValueError("Non-finite coordinates")
        if west < -180 or east > 180 or south < -90 or north > 90:
            raise ValueError("Coordinates outside longitude/latitude range")
        # Limit distortion without rejecting local features across UTM zones or the equator.
        if east - west > 6 or north - south > 6:
            return {
                **result,
                "measurement_status": "UNSUPPORTED_CRS_EXTENT",
                "warning_code": "EXTENT_EXCEEDS_6_DEGREES_OR_CROSSES_ANTIMERIDIAN",
            }
        lon, lat = (west + east) / 2, (south + north) / 2
        polygon = geom.geom_type in ("Polygon", "MultiPolygon")
        method = "laea" if polygon else "aeqd"
        target = CRS.from_proj4(f"+proj={method} +lat_0={lat} +lon_0={lon} +datum=WGS84 +units=m")
        projector = Transformer.from_crs(4326, target, always_xy=True, allow_ballpark=False)
        # Subdivide long edges before projection to reduce chord approximation error.
        coordinates = get_coordinates(wgs)
        estimated_vertices = len(coordinates)
        if len(coordinates) > 1:
            estimated_vertices += int(
                np.ceil(np.linalg.norm(np.diff(coordinates, axis=0), axis=1) / 0.01).sum()
            )
        if estimated_vertices > 1_000_000:
            return {
                **result,
                "measurement_status": "UNSUPPORTED_CRS_EXTENT",
                "warning_code": "DENSIFIED_VERTEX_LIMIT",
            }
        wgs = wgs.segmentize(0.01)
        projected = transform(
            wgs, lambda x, y: projector.transform(x, y, errcheck=True), interleaved=False
        )
        value = projected.area if polygon else projected.length
        if not math.isfinite(value):
            raise ValueError("Non-finite measurement")
        return dict(
            measurement_status="MEASURED",
            measurement_type="area" if polygon else "length",
            value=value,
            unit="m2" if polygon else "m",
            measurement_crs=target.to_wkt(),
            warning_code=None,
        )
    except (ValueError, TypeError, ShapelyError, ProjError) as exc:
        return {
            **result,
            "measurement_status": "TRANSFORMATION_FAILED",
            "warning_code": type(exc).__name__,
        }
