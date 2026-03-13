"""
Data source definitions and field-mapping configurations.

Each source is a dict with:
  url          - base URL or template
  source_type  - "arcgis_rest" | "wfs" | "geojson_url" | "shapefile_url"
  category     - land category label
  field_map    - mapping from source field names → our schema field names
  params       - extra query parameters (for ArcGIS REST sources)
"""

# ---------------------------------------------------------------------------
# ArcGIS REST helper  (returns GeoJSON FeatureCollection pages)
# ---------------------------------------------------------------------------

ARCGIS_REST_PARAMS = {
    "where": "1=1",
    "outFields": "*",
    "f": "geojson",
    "resultOffset": 0,
    "resultRecordCount": 1000,
    "geometryType": "esriGeometryPolygon",
    "outSR": "4326",
}

# ---------------------------------------------------------------------------
# Source registry
# ---------------------------------------------------------------------------

SOURCES = {
    # ------------------------------------------------------------------
    # National Parks Service – NPS Unit Boundaries
    # ArcGIS REST: https://mapservices.nps.gov/arcgis/rest/services/
    # ------------------------------------------------------------------
    "nps_boundaries": {
        "source_type": "arcgis_rest",
        "url": (
            "https://services1.arcgis.com/fBc8EJBxQRMcHlei/arcgis/rest/services/"
            "NPS_Land_Resources_Division_Boundary_and_Tract_Data_Service/FeatureServer/2/query"
        ),
        "category": "national_park",   # refined per-record below
        "field_map": {
            "UNIT_NAME": "name",
            "STATE": "state",
            "DESIG": "designation",   # used to refine category
            "GIS_Acres": "area_acres",
            "UNIT_CODE": "id",
        },
        "category_field": "DESIG",
        "category_map": {
            "National Park": "national_park",
            "National Monument": "national_monument",
            "National Recreation Area": "national_recreation_area",
            "National Seashore": "national_park",
            "National Lakeshore": "national_park",
            "National Parkway": "national_park",
            "National Memorial": "national_monument",
            "National Historic Site": "national_monument",
            "National Historical Park": "national_monument",
            "National Preserve": "national_park",
            "National Reserve": "national_park",
            "National Battlefield": "national_monument",
            "National Battlefield Park": "national_monument",
            "National Military Park": "national_monument",
            "National Scenic Trail": "other",
        },
        "source_url": "https://www.nps.gov/",
        "agency": "National Park Service",
    },

    # ------------------------------------------------------------------
    # USFS National Forests & Grasslands
    # ------------------------------------------------------------------
    "usfs_boundaries": {
        "source_type": "arcgis_rest",
        "url": (
            "https://apps.fs.usda.gov/arcx/rest/services/EDW/"
            "EDW_ForestSystemBoundaries_01/MapServer/0/query"
        ),
        "category": "national_forest",
        "field_map": {
            "FORESTNAME": "name",
            "REGION": "state",       # USFS region; state filled from geometry
            "GIS_ACRES": "area_acres",
            "OBJECTID": "id",
        },
        "source_url": "https://www.fs.usda.gov/",
        "agency": "US Forest Service",
    },

    # ------------------------------------------------------------------
    # BLM Land Boundaries
    # ------------------------------------------------------------------
    "blm_national": {
        "source_type": "arcgis_rest",
        "url": (
            "https://gis.blm.gov/arcgis/rest/services/lands/BLM_Natl_SMA_LimitOf/"
            "MapServer/1/query"
        ),
        "category": "blm",
        "field_map": {
            "ADMU_NAME": "name",
            "ADMIN_ST": "state",
            "GIS_ACRES": "area_acres",
            "OBJECTID": "id",
        },
        "source_url": "https://www.blm.gov/",
        "agency": "Bureau of Land Management",
    },

    # ------------------------------------------------------------------
    # Protected Areas Database (PADUS) – State Parks layer
    # This is a large ESRI FeatureService hosted by USGS
    # ------------------------------------------------------------------
    "padus_state_parks": {
        "source_type": "arcgis_rest",
        "url": (
            "https://services.arcgis.com/v01gqwM5QqNysAAi/arcgis/rest/services/"
            "PADUS3_0_StateLand_Arc/FeatureServer/0/query"
        ),
        "category": "state_park",
        "field_map": {
            "Unit_Nm": "name",
            "State_Nm": "state",
            "GIS_Acres": "area_acres",
            "OBJECTID": "id",
            "Mang_Name": "agency",
        },
        "source_url": "https://www.usgs.gov/programs/gap-analysis-project/science/pad-us-data-overview",
        "agency": "State Agency",
    },

    # ------------------------------------------------------------------
    # PADUS – Federal Wilderness Areas
    # ------------------------------------------------------------------
    "padus_wilderness": {
        "source_type": "arcgis_rest",
        "url": (
            "https://services.arcgis.com/v01gqwM5QqNysAAi/arcgis/rest/services/"
            "PADUS3_0_Wilderness_Arc/FeatureServer/0/query"
        ),
        "category": "wilderness",
        "field_map": {
            "Unit_Nm": "name",
            "State_Nm": "state",
            "GIS_Acres": "area_acres",
            "OBJECTID": "id",
            "Mang_Name": "agency",
        },
        "source_url": "https://www.usgs.gov/programs/gap-analysis-project/science/pad-us-data-overview",
        "agency": "Various",
    },

    # ------------------------------------------------------------------
    # National Wildlife Refuges (USFWS)
    # ------------------------------------------------------------------
    "usfws_refuges": {
        "source_type": "arcgis_rest",
        "url": (
            "https://services.arcgis.com/QVENGdaPbd4LUkLV/arcgis/rest/services/"
            "FWSInterest_public/FeatureServer/1/query"
        ),
        "category": "wildlife_refuge",
        "field_map": {
            "ORGNAME": "name",
            "STATECD": "state",
            "AREAC": "area_acres",
            "OBJECTID": "id",
        },
        "source_url": "https://www.fws.gov/",
        "agency": "US Fish & Wildlife Service",
    },
}
