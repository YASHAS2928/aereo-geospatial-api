import os
from pathlib import Path
from tempfile import TemporaryDirectory

from pyproj import network

from app.config import Settings
from app.errors import InputError
from app.geo.measurement import measure
from app.geo.readers import read_kml, read_shapefile


def vertex_count(value):
    if not value:
        return 0
    if isinstance(value, dict):
        return sum(vertex_count(v) for k, v in value.items() if k in ("coordinates", "geometries"))
    if isinstance(value, (list, tuple)):
        if isinstance(value[0], (int, float)):
            return 1
        return sum(vertex_count(v) for v in value)
    return 0


def process_file(path: str, extension: str, source_crs: str | None, settings: Settings):
    os.environ["PROJ_NETWORK"] = "OFF"
    network.set_network_enabled(False)
    with TemporaryDirectory(prefix="aereo-extract-") as folder:
        if extension == ".zip":
            crs, records = read_shapefile(path, Path(folder), source_crs, settings)
        else:
            crs, records = read_kml(path, source_crs, settings)
        count = 0
        for index, record in enumerate(records):
            geom = record["geometry"]
            count += vertex_count(geom)
            if count > settings.vertices:
                raise InputError("VERTEX_LIMIT", "Too many coordinate vertices", 413)
            record.update(
                index=index,
                source_crs=crs,
                geometry_type=geom.get("type")
                if geom
                else record.pop("source_geometry_type", None),
            )
            record.update(measure(geom, crs))
            if record.get("reader_warning"):
                record.update(
                    measurement_status="INVALID_OR_UNSUPPORTED_GEOMETRY",
                    warning_code=record.pop("reader_warning"),
                )
        return crs, records
