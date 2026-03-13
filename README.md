# 🏕 public_lands

A Python package for ingesting, storing, and visualizing US public land boundaries — National Parks, National Forests, BLM lands, State Parks, Wildlife Refuges, Wilderness Areas, and more.

---

## Features

- **Multi-source ingestion**: Pulls from NPS, USFS, BLM, USFWS, and PADUS (Protected Areas Database of the US) via live ArcGIS REST APIs
- **Geospatial database**: Stores all boundaries in a portable GeoPackage (`.gpkg`) file using GeoPandas/Fiona
- **Interactive maps**: Folium/Leaflet HTML maps with popups, layer toggles, and a mini-map
- **Static maps**: Matplotlib choropleth maps suitable for reports and publications
- **Summary charts**: Bar charts of land counts and total acreage by type
- **Export**: GeoJSON, Shapefile, or CSV
- **Rich CLI**: Full command-line interface with progress bars and formatted tables

---

## Data Sources

| Source Key         | Agency                          | Land Types                                     |
|--------------------|---------------------------------|------------------------------------------------|
| `nps_boundaries`   | National Park Service           | Parks, Monuments, Seashores, Historic Sites… |
| `usfs_boundaries`  | US Forest Service               | National Forests & Grasslands                 |
| `blm_national`     | Bureau of Land Management       | BLM surface management areas                  |
| `padus_state_parks`| State agencies (via USGS PADUS) | State Parks                                    |
| `padus_wilderness` | Various federal agencies        | Wilderness Areas                               |
| `usfws_refuges`    | US Fish & Wildlife Service      | National Wildlife Refuges                      |

---

## Installation

```bash
pip install public_lands
# or from source:
git clone https://github.com/yourname/public_lands
cd public_lands
pip install -e .
```

---

## Quick Start

### CLI

```bash
# See all data sources
public_lands sources

# Ingest everything (may take 5–20 min depending on connection)
public_lands ingest

# Ingest only National Parks and National Forests
public_lands ingest -s nps_boundaries -s usfs_boundaries

# Check what's in the database
public_lands stats

# Query – all California state parks
public_lands query --category state_park --state CA

# Query – everything with "Yosemite" in the name
public_lands query --name Yosemite

# Generate interactive HTML map (all data)
public_lands map --output my_map.html

# Generate interactive map – just National Parks in the Pacific Northwest
public_lands map -o pnw_parks.html --category national_park --state WA --state OR --state ID

# Generate static PNG map
public_lands map --format static --output conus_map.png

# Summary chart
public_lands chart --output summary.png

# Export to GeoJSON
public_lands export all_lands.geojson --format geojson

# Export state parks only to Shapefile
public_lands export state_parks.shp --format shp --category state_park
```

### Python API

```python
from public_lands import Database, DataIngestor, Visualizer

# 1. Set up database (defaults to ~/.public_lands/lands.gpkg)
db = Database()

# 2. Ingest data
ingestor = DataIngestor(db=db)
results = ingestor.ingest_all()
print(results)

# Ingest a single source
results = ingestor.ingest_source("nps_boundaries")

# 3. Query
gdf = db.query(categories=["national_park", "national_monument"], states=["CA"])
print(f"Found {len(gdf)} features in California")
print(gdf[["name", "category", "area_acres"]].head(10))

# Bounding box query (Los Angeles area)
gdf = db.query(bbox=(-119, 33, -116, 35))

# 4. Visualize
viz = Visualizer(db=db)

# Interactive HTML map
viz.interactive_map(
    output_path="national_parks.html",
    categories=["national_park"],
    states=["WA", "OR", "CA"],
)

# Static map
viz.static_map(
    output_path="all_lands.png",
    title="US Public Lands",
)

# Summary chart
viz.summary_chart(output_path="summary.png")

# 5. Export
db.export("all_lands.geojson", fmt="geojson")
db.export("blm_only.csv", fmt="csv")

# 6. Stats
print(db.stats())
```

---

## Database Schema

All land records are stored in a GeoPackage (`lands.gpkg`) in the `lands` layer:

| Column       | Type    | Description                                 |
|--------------|---------|---------------------------------------------|
| `id`         | str/int | Source-system identifier                    |
| `name`       | str     | Official unit name                          |
| `category`   | str     | Land type (see categories below)            |
| `state`      | str     | 2-letter state code(s)                      |
| `agency`     | str     | Managing agency                             |
| `area_acres` | float   | Area in acres                               |
| `source_url` | str     | URL of the original data source             |
| `geometry`   | Polygon | Boundary polygon(s) in WGS84 (EPSG:4326)    |

### Categories

```
national_park          National Park, Seashore, Lakeshore, Parkway, Preserve
national_monument      Monument, Memorial, Historic Site, Battlefield
national_recreation_area
national_forest
national_grassland
blm                    Bureau of Land Management
state_park
wilderness
wildlife_refuge
other
```

---

## CLI Reference

```
Usage: public_lands [OPTIONS] COMMAND [ARGS]...

Options:
  --db TEXT          Path to GeoPackage DB (or set PUBLIC_LANDS_DB env var)
  --verbose/--quiet
  --help

Commands:
  ingest    Download and store data from online sources
  query     Query the database
  map       Generate interactive HTML or static PNG map
  chart     Generate summary bar chart
  stats     Print database statistics
  export    Export to GeoJSON / Shapefile / CSV
  sources   List all configured data sources
```

---

## Performance Notes

- Full ingest of all sources downloads ~50,000–150,000 polygon features and takes 5–30 minutes depending on your connection and API responsiveness.
- The GeoPackage file will typically be 200–800 MB for the full dataset.
- Interactive maps are limited to 5,000 features by default (configurable) for browser performance. Use `--state` or `--category` filters for large datasets.
- Geometries are simplified (tolerance = 0.01°) for the interactive map; this can be adjusted via the Python API.

---

## License

MIT
