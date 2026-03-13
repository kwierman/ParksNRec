"""
Database layer using GeoPackage (via GeoPandas/Fiona) for portable
geospatial storage. Falls back to a flat GeoJSON cache if needed.

Schema:
  - lands table: id, name, category, state, agency, area_acres, source_url, geometry
"""

import logging
import os
from pathlib import Path
from typing import Optional, List

import geopandas as gpd
import pandas as pd
from shapely.geometry import box

logger = logging.getLogger(__name__)

CATEGORIES = [
    "national_park",
    "national_monument",
    "national_recreation_area",
    "national_forest",
    "national_grassland",
    "blm",
    "state_park",
    "wilderness",
    "wildlife_refuge",
    "other",
]

DEFAULT_DB_PATH = Path.home() / ".public_lands" / "lands.gpkg"


class Database:
    """Geospatial database backed by a GeoPackage file."""

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else DEFAULT_DB_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    # ------------------------------------------------------------------
    # Schema helpers
    # ------------------------------------------------------------------

    def _ensure_schema(self):
        """Create an empty GeoPackage with the correct schema if it doesn't exist."""
        if self.path.exists():
            return
        empty = gpd.GeoDataFrame(
            columns=[
                "id", "name", "category", "state", "agency",
                "area_acres", "source_url", "geometry",
            ],
            geometry="geometry",
            crs="EPSG:4326",
        )
        empty.to_file(self.path, driver="GPKG", layer="lands")
        logger.info("Created new database at %s", self.path)

    # ------------------------------------------------------------------
    # Write helpers
    # ------------------------------------------------------------------

    def upsert(self, gdf: gpd.GeoDataFrame, source_label: str = "") -> int:
        """
        Upsert records into the lands layer.
        Matches on (name, category, state) to avoid duplicates.
        Returns number of new records inserted.
        """
        if gdf is None or gdf.empty:
            return 0

        gdf = gdf.copy()
        gdf = self._normalize_columns(gdf)
        gdf = gdf.to_crs("EPSG:4326")

        existing = self._load()

        if existing.empty:
            combined = gdf
        else:
            key_cols = ["name", "category", "state"]
            existing_keys = set(
                existing[key_cols].apply(tuple, axis=1)
            )
            new_mask = ~gdf[key_cols].apply(tuple, axis=1).isin(existing_keys)
            new_rows = gdf[new_mask]
            if new_rows.empty:
                logger.info("[%s] No new records to add.", source_label)
                return 0
            combined = pd.concat([existing, new_rows], ignore_index=True)
            combined = gpd.GeoDataFrame(combined, geometry="geometry", crs="EPSG:4326")

        combined.to_file(self.path, driver="GPKG", layer="lands")
        n_new = len(combined) - len(existing)
        logger.info("[%s] Inserted %d new records (total=%d).", source_label, n_new, len(combined))
        return n_new

    # ------------------------------------------------------------------
    # Read helpers
    # ------------------------------------------------------------------

    def _load(self) -> gpd.GeoDataFrame:
        try:
            return gpd.read_file(self.path, layer="lands")
        except Exception:
            return gpd.GeoDataFrame(
                columns=["id", "name", "category", "state", "agency",
                         "area_acres", "source_url", "geometry"],
                geometry="geometry",
                crs="EPSG:4326",
            )

    def query(
        self,
        categories: Optional[List[str]] = None,
        states: Optional[List[str]] = None,
        bbox: Optional[tuple] = None,
        name_contains: Optional[str] = None,
    ) -> gpd.GeoDataFrame:
        """
        Query the database with optional filters.

        Args:
            categories: List of category strings (e.g. ["national_park", "blm"])
            states: List of 2-letter state codes (e.g. ["CA", "OR"])
            bbox: (minx, miny, maxx, maxy) in WGS84
            name_contains: Substring to match against name (case-insensitive)
        """
        gdf = self._load()
        if gdf.empty:
            return gdf

        if categories:
            gdf = gdf[gdf["category"].isin(categories)]
        if states:
            states_upper = [s.upper() for s in states]
            gdf = gdf[gdf["state"].str.upper().isin(states_upper)]
        if bbox:
            bbox_geom = box(*bbox)
            gdf = gdf[gdf.geometry.intersects(bbox_geom)]
        if name_contains:
            gdf = gdf[gdf["name"].str.contains(name_contains, case=False, na=False)]

        return gdf.reset_index(drop=True)

    def stats(self) -> dict:
        """Return summary statistics about the database contents."""
        gdf = self._load()
        if gdf.empty:
            return {"total": 0, "by_category": {}, "by_state": {}}

        return {
            "total": len(gdf),
            "by_category": gdf["category"].value_counts().to_dict(),
            "by_state": gdf["state"].value_counts().head(20).to_dict(),
            "db_path": str(self.path),
            "db_size_mb": round(self.path.stat().st_size / 1024 / 1024, 2),
        }

    def export(self, output_path: str, fmt: str = "geojson") -> str:
        """Export the full database to GeoJSON, Shapefile, or CSV."""
        gdf = self._load()
        fmt = fmt.lower()
        if fmt == "geojson":
            gdf.to_file(output_path, driver="GeoJSON")
        elif fmt in ("shp", "shapefile"):
            gdf.to_file(output_path, driver="ESRI Shapefile")
        elif fmt == "csv":
            df = pd.DataFrame(gdf.drop(columns="geometry"))
            df.to_csv(output_path, index=False)
        else:
            raise ValueError(f"Unsupported export format: {fmt}")
        return output_path

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _normalize_columns(self, gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """Ensure the GDF has all required columns with sensible defaults."""
        required = {
            "id": None,
            "name": "Unknown",
            "category": "other",
            "state": "",
            "agency": "",
            "area_acres": None,
            "source_url": "",
        }
        for col, default in required.items():
            if col not in gdf.columns:
                gdf[col] = default
        return gdf[list(required.keys()) + ["geometry"]]
