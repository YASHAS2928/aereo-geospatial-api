import math
import stat
import zipfile
from pathlib import PurePosixPath

import fiona
from defusedxml import ElementTree as ET
from pyproj import CRS
from shapely.geometry import shape

from app.errors import InputError


def plain(value):
    if hasattr(value, "items"):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def read_shapefile(path, directory, override, settings):
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if len(members) > settings.zip_members:
                raise InputError("ZIP_LIMIT", "Too many archive members", 413)
            seen, total = set(), 0
            for member in members:
                p = PurePosixPath(member.filename)
                mode = member.external_attr >> 16
                key = str(p).casefold()
                if (
                    p.is_absolute()
                    or ".." in p.parts
                    or "\\" in member.filename
                    or ":" in member.filename
                    or stat.S_ISLNK(mode)
                    or member.flag_bits & 1
                    or key in seen
                ):
                    raise InputError("UNSAFE_ZIP", "Unsafe or duplicate archive entry")
                seen.add(key)
                total += member.file_size
                if total > settings.expanded_bytes:
                    raise InputError("ZIP_LIMIT", "Archive expands beyond limit", 413)
            actual = 0
            for member in members:
                destination = directory / member.filename
                if member.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as src, destination.open("wb") as dst:
                    while chunk := src.read(64 * 1024):
                        actual += len(chunk)
                        if actual > settings.expanded_bytes:
                            raise InputError("ZIP_LIMIT", "Archive expands beyond limit", 413)
                        dst.write(chunk)
        datasets = [p for p in directory.rglob("*") if p.suffix.lower() == ".shp"]
        if len(datasets) != 1:
            raise InputError("AMBIGUOUS_DATASET", "ZIP must contain exactly one Shapefile dataset")
        shp = datasets[0]
        siblings = {p.name.casefold(): p for p in shp.parent.iterdir()}
        for suffix in (".shx", ".dbf"):
            if shp.with_suffix(suffix).name.casefold() not in siblings:
                raise InputError("MISSING_COMPONENT", f"Shapefile requires {suffix}")
        with fiona.open(shp, enabled_drivers=["ESRI Shapefile"]) as collection:
            detected = collection.crs_wkt
            if detected and override:
                raise InputError("CRS_CONFLICT", "Override cannot replace an existing CRS")
            if not detected and not override:
                raise InputError("MISSING_CRS", "Missing CRS; provide source_crs explicitly")
            crs = CRS.from_user_input(detected or override)
            label = crs.to_string()
            records = []
            for feature in collection:
                records.append(
                    {
                        "source_id": feature.id,
                        "geometry": plain(feature.geometry),
                        "properties": plain(feature.properties),
                    }
                )
                if len(records) > settings.features:
                    raise InputError("FEATURE_LIMIT", "Too many features", 413)
            return label, records
    except InputError:
        raise
    except Exception as exc:
        raise InputError("INVALID_SHAPEFILE", "Cannot read Shapefile or CRS") from exc


def local(tag):
    return tag.rsplit("}", 1)[-1]


def coordinates(node):
    element = next((x for x in node.iter() if local(x.tag) == "coordinates"), None)
    if element is None or not element.text:
        raise ValueError("Missing coordinates")
    result = []
    for token in element.text.split():
        values = [float(v) for v in token.split(",")]
        if len(values) not in (2, 3) or not all(math.isfinite(v) for v in values):
            raise ValueError("Invalid coordinates")
        if not (-180 <= values[0] <= 180 and -90 <= values[1] <= 90):
            raise ValueError("KML coordinates outside WGS84 range")
        result.append(values)
    return result


def kml_geometry(node):
    kind = local(node.tag)
    if kind == "Point":
        values = coordinates(node)
        if len(values) != 1:
            raise ValueError("Point must contain one coordinate")
        return {"type": "Point", "coordinates": values[0]}
    if kind == "LineString":
        return {"type": kind, "coordinates": coordinates(node)}
    if kind == "Polygon":
        outer, inner = [], []
        for child in node:
            if local(child.tag) == "outerBoundaryIs":
                outer.append(coordinates(child))
            elif local(child.tag) == "innerBoundaryIs":
                inner.append(coordinates(child))
        if len(outer) != 1:
            raise ValueError("Polygon requires one outer ring")
        for ring in outer + inner:
            if len(ring) < 4 or ring[0] != ring[-1]:
                raise ValueError("KML ring must be closed with at least four coordinates")
        return {"type": kind, "coordinates": outer + inner}
    if kind == "MultiGeometry":
        geometries = [kml_geometry(child) for child in node]
        types = {g["type"] for g in geometries}
        multi = {"Point": "MultiPoint", "LineString": "MultiLineString", "Polygon": "MultiPolygon"}
        if len(types) == 1:
            kind = next(iter(types))
            if kind in multi:
                return {
                    "type": multi[kind],
                    "coordinates": [g["coordinates"] for g in geometries],
                }
        return {"type": "GeometryCollection", "geometries": geometries}
    raise ValueError("Unsupported KML geometry")


def read_kml(path, override, settings):
    if override:
        raise InputError("CRS_CONFLICT", "KML CRS is WGS84; overrides are not accepted")
    try:
        root = ET.parse(path, forbid_dtd=True).getroot()
        if local(root.tag) != "kml":
            raise ValueError("Not KML")
        if any(local(node.tag) == "NetworkLink" for node in root.iter()):
            raise InputError("UNSUPPORTED_KML_REFERENCE", "NetworkLink references are not fetched")
        records = []
        for node in root.iter():
            if local(node.tag) != "Placemark":
                continue
            props, geometries = {}, []
            for child in node:
                kind = local(child.tag)
                if kind in ("name", "description"):
                    props[kind] = child.text or ""
                elif kind == "ExtendedData":
                    for item in child.iter():
                        if local(item.tag) in ("Data", "SimpleData") and item.get("name"):
                            props[item.get("name")] = "".join(item.itertext()).strip()
                elif kind in (
                    "Point",
                    "LineString",
                    "Polygon",
                    "MultiGeometry",
                    "Track",
                    "MultiTrack",
                    "Model",
                ):
                    geometries.append(child)
            record = {"source_id": node.get("id"), "properties": props, "geometry": None}
            try:
                if len(geometries) == 1:
                    record["geometry"] = kml_geometry(geometries[0])
                    shape(record["geometry"])
                elif len(geometries) > 1:
                    raise ValueError("Multiple geometry elements")
            except ValueError:
                record["reader_warning"] = "INVALID_OR_UNSUPPORTED_KML_GEOMETRY"
                record["source_geometry_type"] = local(geometries[0].tag) if geometries else None
                record["source_geometry_xml"] = "".join(
                    ET.tostring(g, encoding="unicode") for g in geometries
                )
            records.append(record)
            if len(records) > settings.features:
                raise InputError("FEATURE_LIMIT", "Too many features", 413)
        return "EPSG:4326", records
    except InputError:
        raise
    except Exception as exc:
        raise InputError("INVALID_KML", "Cannot parse safe KML XML") from exc
