"""
DataIngestor: fetches geospatial data from online sources and writes to Database.

Supports:
  - ArcGIS REST FeatureServer / MapServer queries (paginated)
  - Direct GeoJSON URL downloads
  - Shapefile ZIP downloads
"""

import io
import logging
import time
import zipfile
from pathlib import Path
from typing import Optional, List, Callable
from urllib.parse import urlencode

import geopandas as gpd
import pandas as pd
import requests
from shapely.geometry import shape

from .database import Database
from .sources import SOURCES, ARCGIS_REST_PARAMS

logger = logging.getLogger(__name__)

# How many retries on transient errors
MAX_RETRIES = 3
RETRY_BACKOFF = 2.0   # seconds
REQUEST_TIMEOUT = 60  # seconds per call
PAGE_SIZE = 500       # features per ArcGIS page


class DataIngestor:
    """Downloads and stores public land boundaries from configured sources."""

    def __init__(self, db: Optional[Database] = None, verbose: bool = True):
        self.db = db or Database()
        self.verbose = verbose
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "public_lands/1.0 (+https://github.com/)"})

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ingest_all(
        self,
        source_keys: Optional[List[str]] = None,
        progress_cb: Optional[Callable] = None,
    ) -> dict:
        """
        Ingest from all (or specified) sources.

        Args:
            source_keys: list of keys from SOURCES dict; None = all
            progress_cb: callable(source_key, n_fetched, n_total) for progress updates

        Returns:
            dict mapping source_key → {"inserted": int, "fetched": int, "error": str|None}
        """
        keys = source_keys or list(SOURCES.keys())
        results = {}
        for key in keys:
            if key not in SOURCES:
                logger.warning("Unknown source key: %s – skipping.", key)
                results[key] = {"inserted": 0, "fetched": 0, "error": f"Unknown source: {key}"}
                continue
            results[key] = self._ingest_source(key, progress_cb)
        return results

    def ingest_source(self, source_key: str) -> dict:
        """Ingest a single named source."""
        return self._ingest_source(source_key)

    # ------------------------------------------------------------------
    # Internal dispatch
    # ------------------------------------------------------------------

    def _ingest_source(self, key: str, progress_cb=None) -> dict:
        cfg = SOURCES[key]
        stype = cfg["source_type"]
        result = {"inserted": 0, "fetched": 0, "error": None}

        try:
            if stype == "arcgis_rest":
                gdf = self._fetch_arcgis_rest(key, cfg, progress_cb)
            elif stype == "geojson_url":
                gdf = self._fetch_geojson_url(cfg["url"])
            elif stype == "shapefile_url":
                gdf = self._fetch_shapefile_zip(cfg["url"])
            else:
                raise ValueError(f"Unsupported source type: {stype}")

            if gdf is not None and not gdf.empty:
                gdf = self._apply_field_map(gdf, cfg)
                result["fetched"] = len(gdf)
                result["inserted"] = self.db.upsert(gdf, source_label=key)
            else:
                logger.warning("[%s] No features returned.", key)

        except Exception as exc:
            logger.error("[%s] Ingest failed: %s", key, exc, exc_info=True)
            result["error"] = str(exc)

        return result

    # ------------------------------------------------------------------
    # ArcGIS REST fetcher (paginated)
    # ------------------------------------------------------------------

    def _fetch_arcgis_rest(
        self, key: str, cfg: dict, progress_cb=None
    ) -> Optional[gpd.GeoDataFrame]:
        """
        Paginate through an ArcGIS REST query endpoint.
        Handles both FeatureServer and MapServer services.
        """
        url = cfg["url"]
        all_features = []
        offset = 0

        # First, get the total count
        count_params = {
            "where": "1=1",
            "returnCountOnly": "true",
            "f": "json",
        }
        try:
            resp = self._get(url, count_params)
            total = resp.get("count", 0)
            logger.info("[%s] Total features: %d", key, total)
        except Exception:
            total = None

        while True:
            params = {
                **ARCGIS_REST_PARAMS,
                "resultOffset": offset,
                "resultRecordCount": PAGE_SIZE,
            }
            try:
                data = self._get(url, params)
            except Exception as exc:
                logger.error("[%s] Page fetch failed at offset %d: %s", key, offset, exc)
                break

            features = data.get("features", [])
            if not features:
                break

            all_features.extend(features)
            logger.info("[%s] Fetched %d features (offset=%d).", key, len(all_features), offset)

            if progress_cb:
                progress_cb(key, len(all_features), total)

            # Check if there are more pages
            exceeded = data.get("exceededTransferLimit", False)
            if not exceeded or len(features) < PAGE_SIZE:
                break

            offset += PAGE_SIZE
            time.sleep(0.2)  # be polite to the server

        if not all_features:
            return None

        return self._features_to_gdf(all_features)

    # ------------------------------------------------------------------
    # GeoJSON URL fetcher
    # ------------------------------------------------------------------

    def _fetch_geojson_url(self, url: str) -> Optional[gpd.GeoDataFrame]:
        resp = self._session.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return gpd.read_file(io.BytesIO(resp.content))

    # ------------------------------------------------------------------
    # Shapefile ZIP fetcher
    # ------------------------------------------------------------------

    def _fetch_shapefile_zip(self, url: str) -> Optional[gpd.GeoDataFrame]:
        resp = self._session.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
            shp_names = [n for n in z.namelist() if n.endswith(".shp")]
            if not shp_names:
                raise ValueError("No .shp file found in ZIP.")
            # Extract to temp dir
            import tempfile, os
            with tempfile.TemporaryDirectory() as tmpdir:
                z.extractall(tmpdir)
                return gpd.read_file(os.path.join(tmpdir, shp_names[0]))

    # ------------------------------------------------------------------
    # HTTP helper with retries
    # ------------------------------------------------------------------

    def _get(self, url: str, params: dict) -> dict:
        for attempt in range(MAX_RETRIES):
            try:
                resp = self._session.get(url, params=params, timeout=REQUEST_TIMEOUT)
                resp.raise_for_status()
                data = resp.json()
                if "error" in data:
                    raise ValueError(f"ArcGIS error: {data['error']}")
                return data
            except (requests.RequestException, ValueError) as exc:
                if attempt < MAX_RETRIES - 1:
                    wait = RETRY_BACKOFF * (attempt + 1)
                    logger.warning("Retry %d/%d after %.1fs – %s", attempt + 1, MAX_RETRIES, wait, exc)
                    time.sleep(wait)
                else:
                    raise

    # ------------------------------------------------------------------
    # Conversion helpers
    # ------------------------------------------------------------------

    def _features_to_gdf(self, features: list) -> gpd.GeoDataFrame:
        """Convert a list of GeoJSON feature dicts to a GeoDataFrame."""
        rows = []
        geometries = []
        for f in features:
            props = f.get("properties") or {}
            geom = f.get("geometry")
            if geom:
                try:
                    geometries.append(shape(geom))
                except Exception:
                    geometries.append(None)
            else:
                geometries.append(None)
            rows.append(props)

        df = pd.DataFrame(rows)
        gdf = gpd.GeoDataFrame(df, geometry=geometries, crs="EPSG:4326")
        return gdf[gdf.geometry.notna()].reset_index(drop=True)

    def _apply_field_map(self, gdf: gpd.GeoDataFrame, cfg: dict) -> gpd.GeoDataFrame:
        """Rename fields, set category, and add metadata columns."""
        field_map = cfg.get("field_map", {})

        # Rename mapped columns
        rename = {src: dst for src, dst in field_map.items() if src in gdf.columns}
        gdf = gdf.rename(columns=rename)

        # Determine category (may be refined from a field)
        base_category = cfg.get("category", "other")
        cat_field = cfg.get("category_field")
        cat_map = cfg.get("category_map", {})

        if cat_field and cat_field in gdf.columns:
            gdf["category"] = gdf[cat_field].map(
                lambda v: cat_map.get(v, base_category) if pd.notna(v) else base_category
            )
        elif "category" not in gdf.columns:
            gdf["category"] = base_category

        # Set static metadata
        if "agency" in cfg and "agency" not in gdf.columns:
            gdf["agency"] = cfg["agency"]
        if "source_url" in cfg:
            gdf["source_url"] = cfg["source_url"]

        # Ensure name column exists
        if "name" not in gdf.columns:
            gdf["name"] = "Unknown"

        # Ensure state column exists
        if "state" not in gdf.columns:
            gdf["state"] = ""

        # Ensure id column
        if "id" not in gdf.columns:
            gdf["id"] = range(len(gdf))

        return gdf
