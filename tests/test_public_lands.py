"""
Tests for public_lands package.
Run with:  pytest tests/ -v
"""

import json
import tempfile
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box, Polygon

from parknsrec.database import Database
from parknsrec.visualizer import Visualizer, CATEGORY_COLORS, _darken


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_POLYGON = Polygon([(-120, 38), (-119, 38), (-119, 39), (-120, 39), (-120, 38)])
SAMPLE_POLYGON_2 = Polygon([(-110, 35), (-109, 35), (-109, 36), (-110, 36), (-110, 35)])


def make_sample_gdf():
    return gpd.GeoDataFrame(
        {
            "id": [1, 2, 3],
            "name": ["Yosemite National Park", "Sierra National Forest", "BLM CA"],
            "category": ["national_park", "national_forest", "blm"],
            "state": ["CA", "CA", "CA"],
            "agency": ["NPS", "USFS", "BLM"],
            "area_acres": [748_000.0, 1_300_000.0, 500_000.0],
            "source_url": ["https://nps.gov", "https://fs.usda.gov", "https://blm.gov"],
            "geometry": [SAMPLE_POLYGON, SAMPLE_POLYGON_2, SAMPLE_POLYGON],
        },
        crs="EPSG:4326",
    )


@pytest.fixture
def tmp_db(tmp_path):
    db_file = tmp_path / "test_lands.gpkg"
    db = Database(path=db_file)
    return db


@pytest.fixture
def populated_db(tmp_db):
    gdf = make_sample_gdf()
    tmp_db.upsert(gdf, source_label="test")
    return tmp_db


# ---------------------------------------------------------------------------
# Database tests
# ---------------------------------------------------------------------------


class TestDatabase:
    def test_creates_empty_db(self, tmp_db):
        assert tmp_db.path.exists()

    def test_upsert_inserts_records(self, tmp_db):
        gdf = make_sample_gdf()
        n = tmp_db.upsert(gdf, source_label="test")
        assert n == 3

    def test_upsert_deduplicates(self, populated_db):
        gdf = make_sample_gdf()
        n = populated_db.upsert(gdf, source_label="test_dup")
        assert n == 0  # All already present

    def test_query_all(self, populated_db):
        gdf = populated_db.query()
        assert len(gdf) == 3

    def test_query_by_category(self, populated_db):
        gdf = populated_db.query(categories=["national_park"])
        assert len(gdf) == 1
        assert gdf.iloc[0]["name"] == "Yosemite National Park"

    def test_query_by_state(self, populated_db):
        gdf = populated_db.query(states=["CA"])
        assert len(gdf) == 3

    def test_query_by_name(self, populated_db):
        gdf = populated_db.query(name_contains="sierra")
        assert len(gdf) == 1
        assert "Sierra" in gdf.iloc[0]["name"]

    def test_query_by_bbox(self, populated_db):
        # Only first polygon intersects this bbox
        gdf = populated_db.query(bbox=(-121, 37, -118, 40))
        assert len(gdf) >= 1

    def test_stats(self, populated_db):
        s = populated_db.stats()
        assert s["total"] == 3
        assert "national_park" in s["by_category"]
        assert s["by_category"]["national_park"] == 1

    def test_export_geojson(self, populated_db, tmp_path):
        out = str(tmp_path / "out.geojson")
        populated_db.export(out, fmt="geojson")
        assert Path(out).exists()
        with open(out) as f:
            data = json.load(f)
        assert len(data["features"]) == 3

    def test_export_csv(self, populated_db, tmp_path):
        out = str(tmp_path / "out.csv")
        populated_db.export(out, fmt="csv")
        assert Path(out).exists()
        df = pd.read_csv(out)
        assert len(df) == 3

    def test_empty_db_stats(self, tmp_db):
        s = tmp_db.stats()
        assert s["total"] == 0

    def test_query_empty_db(self, tmp_db):
        gdf = tmp_db.query()
        assert gdf.empty


# ---------------------------------------------------------------------------
# Visualizer tests
# ---------------------------------------------------------------------------


class TestVisualizer:
    def test_interactive_map_creates_file(self, populated_db, tmp_path):
        viz = Visualizer(db=populated_db)
        out = str(tmp_path / "map.html")
        result = viz.interactive_map(output_path=out)
        assert Path(result).exists()
        content = Path(result).read_text()
        assert "leaflet" in content.lower()

    def test_static_map_creates_file(self, populated_db, tmp_path):
        viz = Visualizer(db=populated_db)
        out = str(tmp_path / "map.png")
        result = viz.static_map(output_path=out)
        assert Path(result).exists()
        assert Path(result).stat().st_size > 1000

    def test_summary_chart_creates_file(self, populated_db, tmp_path):
        viz = Visualizer(db=populated_db)
        out = str(tmp_path / "chart.png")
        result = viz.summary_chart(output_path=out)
        assert Path(result).exists()

    def test_interactive_map_empty_db(self, tmp_db, tmp_path):
        viz = Visualizer(db=tmp_db)
        out = str(tmp_path / "empty_map.html")
        result = viz.interactive_map(output_path=out)
        assert Path(result).exists()

    def test_interactive_map_category_filter(self, populated_db, tmp_path):
        viz = Visualizer(db=populated_db)
        out = str(tmp_path / "filtered_map.html")
        result = viz.interactive_map(output_path=out, categories=["national_park"])
        assert Path(result).exists()

    def test_color_palette_complete(self):
        from parknsrec.database import CATEGORIES

        for cat in CATEGORIES:
            assert cat in CATEGORY_COLORS, f"Missing color for category: {cat}"

    def test_darken_function(self):
        darkened = _darken("#2d6a2d", 0.5)
        assert darkened.startswith("#")
        assert darkened != "#2d6a2d"

    def test_darken_invalid_color(self):
        # Should not raise
        result = _darken("notacolor", 0.5)
        assert result == "notacolor"


# ---------------------------------------------------------------------------
# Ingestor tests (offline / mock)
# ---------------------------------------------------------------------------


class TestIngestorFieldMap:
    """Test field mapping logic without network calls."""

    def test_apply_field_map_renames_columns(self):
        from parknsrec.ingestor import DataIngestor
        import geopandas as gpd
        from shapely.geometry import Point

        ingestor = DataIngestor.__new__(DataIngestor)

        gdf = gpd.GeoDataFrame(
            {
                "UNIT_NAME": ["Test Park"],
                "STATE": ["CA"],
                "GIS_Acres": [10000.0],
                "UNIT_CODE": ["TEST"],
                "geometry": [Point(-120, 38)],
            },
            crs="EPSG:4326",
        )
        cfg = {
            "category": "national_park",
            "field_map": {
                "UNIT_NAME": "name",
                "STATE": "state",
                "GIS_Acres": "area_acres",
                "UNIT_CODE": "id",
            },
            "agency": "NPS",
            "source_url": "https://nps.gov",
        }
        result = ingestor._apply_field_map(gdf, cfg)
        assert "name" in result.columns
        assert "state" in result.columns
        assert result.iloc[0]["name"] == "Test Park"
        assert result.iloc[0]["category"] == "national_park"

    def test_apply_field_map_with_category_map(self):
        from parknsrec.ingestor import DataIngestor
        import geopandas as gpd
        from shapely.geometry import Point

        ingestor = DataIngestor.__new__(DataIngestor)

        gdf = gpd.GeoDataFrame(
            {
                "UNIT_NAME": ["Statue of Liberty"],
                "DESIG": ["National Monument"],
                "STATE": ["NY"],
                "GIS_Acres": [58.0],
                "UNIT_CODE": ["STLI"],
                "geometry": [Point(-74, 40.7)],
            },
            crs="EPSG:4326",
        )
        cfg = {
            "category": "national_park",
            "field_map": {
                "UNIT_NAME": "name",
                "STATE": "state",
                "GIS_Acres": "area_acres",
                "UNIT_CODE": "id",
            },
            "category_field": "DESIG",
            "category_map": {"National Monument": "national_monument"},
            "agency": "NPS",
            "source_url": "https://nps.gov",
        }
        result = ingestor._apply_field_map(gdf, cfg)
        assert result.iloc[0]["category"] == "national_monument"
