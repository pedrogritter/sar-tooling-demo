"""Pixel and geographic coordinates for an ICEYE affine.

The six numbers in ``proj:transform`` follow GDAL order. Column and row
are full-resolution raster coordinates. Measurements taken on a coarser
grid pass ``scale`` so that one coarse pixel spans ``scale`` full pixels.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Grid:
    """Affine from full-resolution pixels to longitude and latitude."""

    origin_lon: float
    col_lon: float
    row_lon: float
    origin_lat: float
    col_lat: float
    row_lat: float

    @classmethod
    def from_transform(cls, values: list[float] | tuple[float, ...]) -> Grid:
        if len(values) < 6:
            raise ValueError("proj:transform needs six numbers")
        return cls(*[float(value) for value in values[:6]])

    def to_lonlat(
        self, col: float, row: float, scale: float = 1.0
    ) -> tuple[float, float]:
        full_col = col * scale
        full_row = row * scale
        lon = self.origin_lon + self.col_lon * full_col + self.row_lon * full_row
        lat = self.origin_lat + self.col_lat * full_col + self.row_lat * full_row
        return lon, lat

    def to_colrow(
        self, lon: float, lat: float, scale: float = 1.0
    ) -> tuple[float, float]:
        det = self.col_lon * self.row_lat - self.row_lon * self.col_lat
        if det == 0:
            raise ValueError("proj:transform is singular")
        dlon = lon - self.origin_lon
        dlat = lat - self.origin_lat
        full_col = (self.row_lat * dlon - self.row_lon * dlat) / det
        full_row = (-self.col_lat * dlon + self.col_lon * dlat) / det
        return full_col / scale, full_row / scale


def metres(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Distance between two WGS84 points, accurate at the scale of this scene."""

    mean_lat = math.radians((lat1 + lat2) / 2)
    east = (lon2 - lon1) * 111_320 * math.cos(mean_lat)
    north = (lat2 - lat1) * 110_540
    return math.hypot(east, north)
