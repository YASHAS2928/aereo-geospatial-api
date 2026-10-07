from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel


class FileInfo(BaseModel):
    id: str
    filename: str
    feature_count: int
    crs: str
    status: Literal["COMPLETED", "COMPLETED_WITH_WARNINGS"]
    measured_count: int
    skipped_count: int
    checksum_sha256: str
    size_bytes: int
    created_at: datetime


class FeatureMeasurement(BaseModel):
    index: int
    source_id: str | None
    geometry_type: str | None
    geometry: dict[str, Any] | None
    source_geometry_xml: str | None = None
    properties: dict[str, Any]
    source_crs: str
    measurement_status: str
    measurement_type: Literal["area", "length"] | None
    value: float | None
    unit: Literal["m", "m2"] | None
    measurement_crs: str | None
    warning_code: str | None


class MeasurementPage(BaseModel):
    file_id: str
    count: int
    next_offset: int | None
    features: list[FeatureMeasurement]
