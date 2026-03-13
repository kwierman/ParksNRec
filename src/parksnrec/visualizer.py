"""
Visualizer: creates interactive (Folium/Leaflet) and static (Matplotlib)
maps of public land boundaries.

Usage:
    from public_lands import Database, Visualizer
    db = Database()
    viz = Visualizer(db)
    viz.interactive_map(output_path="map.html")
    viz.static_map(output_path="map.png")
"""

import logging
from pathlib import Path
from typing import Optional, List, Tuple

import geopandas as gpd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.colors as mcolors
import folium
from folium.plugins import MarkerCluster, MiniMap, Fullscreen

from .database import Database

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Color palette per category
# ---------------------------------------------------------------------------

CATEGORY_COLORS = {
    "national_park":            "#2d6a2d",   # Forest green
    "national_monument":        "#4a7c59",   # Sage
    "national_recreation_area": "#5a9e6f",   # Light green
    "national_forest":          "#1a5c1a",   # Dark green
    "national_grassland":       "#8db87a",   # Pale green
    "blm":                      "#c8a55e",   # Tan / BLM gold
    "state_park":               "#4a90d9",   # Blue
    "wilderness":               "#7b4fa6",   # Purple
    "wildlife_refuge":          "#c06020",   # Burnt orange
    "other":                    "#888888",   # Grey
}

CATEGORY_LABELS = {
    "national_park":            "National Park / Seashore / Lakeshore",
    "national_monument":        "National Monument / Memorial / Historic Site",
    "national_recreation_area": "National Recreation Area",
    "national_forest":          "National Forest",
    "national_grassland":       "National Grassland",
    "blm":                      "BLM Land",
    "state_park":               "State Park",
    "wilderness":               "Wilderness Area",
    "wildlife_refuge":          "National Wildlife Refuge",
    "other":                    "Other Public Land",
}


class Visualizer:
    """Map renderer for public land data."""

    def __init__(self, db: Optional[Database] = None):
        self.db = db or Database()

    # ------------------------------------------------------------------
    # Interactive HTML map (Folium / Leaflet.js)
    # ------------------------------------------------------------------

    def interactive_map(
        self,
        output_path: str = "public_lands_map.html",
        categories: Optional[List[str]] = None,
        states: Optional[List[str]] = None,
        bbox: Optional[Tuple[float, float, float, float]] = None,
        name_contains: Optional[str] = None,
        max_features: int = 5000,
        simplify_tolerance: float = 0.01,
    ) -> str:
        """
        Build an interactive Folium map.

        Args:
            output_path:        Where to save the HTML file.
            categories:         Filter by category list.
            states:             Filter by state codes.
            bbox:               (minx, miny, maxx, maxy) bounding box.
            name_contains:      Name substring filter.
            max_features:       Cap on number of features (for performance).
            simplify_tolerance: Geometry simplification tolerance (degrees).

        Returns:
            Path to the saved HTML file.
        """
        gdf = self.db.query(
            categories=categories,
            states=states,
            bbox=bbox,
            name_contains=name_contains,
        )

        if gdf.empty:
            logger.warning("No features found for the given filters.")
            gdf = gpd.GeoDataFrame(
                columns=["name", "category", "state", "area_acres", "geometry"],
                geometry="geometry",
                crs="EPSG:4326",
            )

        if len(gdf) > max_features:
            logger.warning("Limiting to %d features (found %d).", max_features, len(gdf))
            gdf = gdf.head(max_features)

        # Simplify geometries for faster rendering
        if simplify_tolerance and not gdf.empty:
            gdf = gdf.copy()
            gdf["geometry"] = gdf["geometry"].simplify(simplify_tolerance, preserve_topology=True)

        # Center map on data extent or CONUS
        if not gdf.empty:
            total_bounds = gdf.total_bounds  # (minx, miny, maxx, maxy)
            center_lat = (total_bounds[1] + total_bounds[3]) / 2
            center_lon = (total_bounds[0] + total_bounds[2]) / 2
        else:
            center_lat, center_lon = 39.5, -98.35   # CONUS center

        m = folium.Map(
            location=[center_lat, center_lon],
            zoom_start=5,
            tiles=None,
        )

        # Base tile layers
        folium.TileLayer("CartoDB positron", name="Light", control=True).add_to(m)
        folium.TileLayer(
            "https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}",
            attr="Esri",
            name="Esri Topo",
            overlay=False,
            control=True,
        ).add_to(m)
        folium.TileLayer("OpenStreetMap", name="OpenStreetMap", control=True).add_to(m)

        # Add plugin controls
        MiniMap(toggle_display=True).add_to(m)
        Fullscreen(position="topleft").add_to(m)

        # Create a FeatureGroup per category
        if not gdf.empty:
            for category in sorted(gdf["category"].unique()):
                cat_gdf = gdf[gdf["category"] == category]
                color = CATEGORY_COLORS.get(category, "#888888")
                label = CATEGORY_LABELS.get(category, category.replace("_", " ").title())
                fg = folium.FeatureGroup(name=label, show=True)

                for _, row in cat_gdf.iterrows():
                    if row.geometry is None or row.geometry.is_empty:
                        continue
                    popup_html = self._build_popup(row)
                    folium.GeoJson(
                        row.geometry.__geo_interface__,
                        style_function=lambda _, c=color: {
                            "fillColor": c,
                            "color": _darken(c, 0.6),
                            "weight": 0.8,
                            "fillOpacity": 0.45,
                        },
                        highlight_function=lambda _: {
                            "weight": 2.5,
                            "fillOpacity": 0.7,
                        },
                        popup=folium.Popup(popup_html, max_width=320),
                        tooltip=row.get("name", ""),
                    ).add_to(fg)

                fg.add_to(m)

        # Legend
        legend_html = self._build_legend_html(
            gdf["category"].unique() if not gdf.empty else []
        )
        m.get_root().html.add_child(folium.Element(legend_html))

        # Layer control
        folium.LayerControl(collapsed=False).add_to(m)

        output_path = str(output_path)
        m.save(output_path)
        logger.info("Interactive map saved to %s", output_path)
        return output_path

    # ------------------------------------------------------------------
    # Static map (Matplotlib)
    # ------------------------------------------------------------------

    def static_map(
        self,
        output_path: str = "public_lands_map.png",
        categories: Optional[List[str]] = None,
        states: Optional[List[str]] = None,
        bbox: Optional[Tuple[float, float, float, float]] = None,
        name_contains: Optional[str] = None,
        figsize: Tuple[int, int] = (20, 12),
        dpi: int = 150,
        show_basemap: bool = True,
        title: str = "US Public Lands",
    ) -> str:
        """
        Build a static Matplotlib choropleth map.

        Returns:
            Path to the saved image file.
        """
        gdf = self.db.query(
            categories=categories,
            states=states,
            bbox=bbox,
            name_contains=name_contains,
        )

        fig, ax = plt.subplots(1, 1, figsize=figsize)
        ax.set_facecolor("#d4e8f7")   # Ocean/background blue
        fig.patch.set_facecolor("#1a1a2e")

        if gdf.empty:
            ax.text(
                0.5, 0.5,
                "No data found.\nRun 'public_lands ingest' to populate the database.",
                transform=ax.transAxes,
                ha="center", va="center",
                fontsize=14, color="white",
            )
        else:
            # Plot each category as a separate layer
            legend_patches = []
            for category in sorted(gdf["category"].unique()):
                cat_gdf = gdf[gdf["category"] == category]
                color = CATEGORY_COLORS.get(category, "#888888")
                cat_gdf.plot(
                    ax=ax,
                    color=color,
                    edgecolor=_darken(color, 0.7),
                    linewidth=0.3,
                    alpha=0.7,
                )
                label = CATEGORY_LABELS.get(category, category.replace("_", " ").title())
                legend_patches.append(
                    mpatches.Patch(facecolor=color, edgecolor=_darken(color, 0.7),
                                   label=f"{label} ({len(cat_gdf):,})")
                )

            # Legend
            ax.legend(
                handles=legend_patches,
                loc="lower left",
                framealpha=0.85,
                fontsize=8,
                title="Land Type",
                title_fontsize=9,
            )

        ax.set_title(title, fontsize=18, color="white", pad=14, fontweight="bold")
        ax.set_xlabel("Longitude", color="#aaaaaa", fontsize=9)
        ax.set_ylabel("Latitude",  color="#aaaaaa", fontsize=9)
        ax.tick_params(colors="#aaaaaa")
        for spine in ax.spines.values():
            spine.set_edgecolor("#555555")

        plt.tight_layout()
        fig.savefig(output_path, dpi=dpi, bbox_inches="tight", facecolor=fig.get_facecolor())
        plt.close(fig)
        logger.info("Static map saved to %s", output_path)
        return output_path

    # ------------------------------------------------------------------
    # Category summary chart
    # ------------------------------------------------------------------

    def summary_chart(
        self,
        output_path: str = "public_lands_summary.png",
        figsize: Tuple[int, int] = (12, 6),
    ) -> str:
        """Bar chart of feature counts and total acreage by category."""
        gdf = self.db.query()

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=figsize)
        fig.patch.set_facecolor("#1a1a2e")

        if gdf.empty:
            for ax in (ax1, ax2):
                ax.set_facecolor("#1a1a2e")
                ax.text(0.5, 0.5, "No data", transform=ax.transAxes,
                        ha="center", va="center", color="white")
        else:
            counts = gdf["category"].value_counts()
            colors = [CATEGORY_COLORS.get(c, "#888888") for c in counts.index]

            ax1.set_facecolor("#252540")
            bars = ax1.barh(
                [CATEGORY_LABELS.get(c, c) for c in counts.index],
                counts.values,
                color=colors,
                edgecolor="none",
            )
            ax1.set_title("Feature Count by Type", color="white", fontsize=12)
            ax1.tick_params(colors="#cccccc", labelsize=8)
            ax1.set_facecolor("#252540")
            for spine in ax1.spines.values():
                spine.set_visible(False)
            ax1.xaxis.label.set_color("#aaaaaa")

            # Acreage chart
            if "area_acres" in gdf.columns:
                acres = (
                    gdf.dropna(subset=["area_acres"])
                    .groupby("category")["area_acres"].sum()
                    .sort_values(ascending=False)
                )
                a_colors = [CATEGORY_COLORS.get(c, "#888888") for c in acres.index]
                ax2.set_facecolor("#252540")
                ax2.barh(
                    [CATEGORY_LABELS.get(c, c) for c in acres.index],
                    acres.values / 1_000_000,
                    color=a_colors,
                    edgecolor="none",
                )
                ax2.set_title("Total Acreage by Type (millions)", color="white", fontsize=12)
                ax2.tick_params(colors="#cccccc", labelsize=8)
                for spine in ax2.spines.values():
                    spine.set_visible(False)

        plt.tight_layout()
        fig.savefig(output_path, dpi=120, bbox_inches="tight", facecolor=fig.get_facecolor())
        plt.close(fig)
        logger.info("Summary chart saved to %s", output_path)
        return output_path

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_popup(self, row) -> str:
        cat = row.get("category", "")
        label = CATEGORY_LABELS.get(cat, cat.replace("_", " ").title())
        color = CATEGORY_COLORS.get(cat, "#888888")
        acres = row.get("area_acres")
        acres_str = f"{acres:,.0f}" if acres and str(acres) != "nan" else "N/A"
        state = row.get("state", "")
        agency = row.get("agency", "")
        source = row.get("source_url", "")

        html = f"""
        <div style="font-family:Arial,sans-serif;min-width:220px">
          <div style="background:{color};color:white;padding:8px 10px;border-radius:4px 4px 0 0">
            <b>{row.get('name', 'Unknown')}</b>
          </div>
          <div style="padding:8px 10px;border:1px solid #ddd;border-top:none;border-radius:0 0 4px 4px">
            <table style="width:100%;font-size:12px">
              <tr><td><b>Type</b></td><td>{label}</td></tr>
              <tr><td><b>State</b></td><td>{state}</td></tr>
              <tr><td><b>Agency</b></td><td>{agency}</td></tr>
              <tr><td><b>Acres</b></td><td>{acres_str}</td></tr>
            </table>
            {"<a href='" + source + "' target='_blank' style='font-size:11px'>More info ↗</a>" if source else ""}
          </div>
        </div>
        """
        return html

    def _build_legend_html(self, categories) -> str:
        items = ""
        for cat in sorted(categories):
            color = CATEGORY_COLORS.get(cat, "#888888")
            label = CATEGORY_LABELS.get(cat, cat.replace("_", " ").title())
            items += f"""
              <div style="display:flex;align-items:center;margin:3px 0">
                <div style="width:14px;height:14px;background:{color};
                            border:1px solid {_darken(color,0.6)};
                            border-radius:2px;margin-right:7px;flex-shrink:0"></div>
                <span style="font-size:12px">{label}</span>
              </div>"""

        return f"""
        <div style="
            position:fixed;bottom:30px;right:10px;z-index:9999;
            background:rgba(255,255,255,0.93);padding:12px 16px;
            border-radius:8px;border:1px solid #ccc;
            box-shadow:0 2px 8px rgba(0,0,0,0.2);max-width:280px">
          <b style="font-size:13px;display:block;margin-bottom:6px">Public Land Types</b>
          {items}
        </div>"""


# ---------------------------------------------------------------------------
# Color utility
# ---------------------------------------------------------------------------

def _darken(hex_color: str, factor: float = 0.7) -> str:
    """Return a darker version of a hex color."""
    try:
        r, g, b = mcolors.to_rgb(hex_color)
        return mcolors.to_hex((r * factor, g * factor, b * factor))
    except Exception:
        return hex_color
