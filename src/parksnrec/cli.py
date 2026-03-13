from rich.console import Console
from rich.logging import RichHandler
import pathlib
import logging
import typer

# Set log_path=False in the Console instance used by the handler
console = Console(log_path=False)
logging.basicConfig(
    level="INFO",
    format="%(message)s",
    handlers=[RichHandler(console=console)]
)


app = typer.Typer(help="Tools for getting public parks information")

@app.command('ingest')
def ingest(db_path:pathlib.Path = pathlib.Path('parksnrec.db')):
    ...





"""
Command-line interface for public_lands.

Commands:
  ingest     – Download and store land boundary data
  query      – Query the database and print results
  map        – Generate an interactive or static map
  chart      – Generate a summary chart
  stats      – Print database statistics
  export     – Export the database to GeoJSON / Shapefile / CSV
"""

import json
import logging
import sys
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
from rich import box as rbox

from .database import Database
from .ingestor import DataIngestor
from .sources import SOURCES
from .visualizer import Visualizer

console = Console()

# ---------------------------------------------------------------------------
# Root group
# ---------------------------------------------------------------------------

@click.group()
@click.option(
    "--db",
    "db_path",
    default=None,
    envvar="PUBLIC_LANDS_DB",
    help="Path to GeoPackage database (default: ~/.public_lands/lands.gpkg)",
    show_default=True,
)
@click.option("--verbose/--quiet", default=True, help="Enable verbose logging.")
@click.pass_context
def cli(ctx, db_path, verbose):
    """
    🏕  public_lands – US Public Land Boundary Toolkit

    Ingest, query, and visualize boundaries for National Parks, Forests,
    BLM lands, State Parks, Wildlife Refuges, and more.
    """
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(levelname)s  %(name)s: %(message)s",
    )
    ctx.ensure_object(dict)
    ctx.obj["db"] = Database(path=db_path) if db_path else Database()
    ctx.obj["verbose"] = verbose


# ---------------------------------------------------------------------------
# ingest
# ---------------------------------------------------------------------------

@cli.command()
@click.option(
    "--source", "-s",
    multiple=True,
    type=click.Choice(list(SOURCES.keys()) + ["all"], case_sensitive=False),
    default=["all"],
    show_default=True,
    help="Data source(s) to ingest. Pass multiple -s flags or use 'all'.",
)
@click.pass_context
def ingest(ctx, source):
    """Download public land boundary data from online sources and store in DB."""
    db = ctx.obj["db"]
    ingestor = DataIngestor(db=db, verbose=ctx.obj["verbose"])

    keys = list(SOURCES.keys()) if "all" in source else list(source)

    console.print(f"\n[bold green]🌎 Ingesting {len(keys)} source(s)…[/bold green]")
    console.print(f"Database: [cyan]{db.path}[/cyan]\n")

    results = {}
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[cyan]{task.fields[fetched]}[/cyan] features"),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    ) as progress:
        for key in keys:
            task = progress.add_task(f"[yellow]{key}[/yellow]", total=None, fetched=0)

            def _cb(k, n_fetched, n_total, _task=task):
                progress.update(_task, completed=n_fetched,
                                total=n_total or n_fetched,
                                fetched=n_fetched)

            res = ingestor.ingest_source(key)
            results[key] = res
            status = "[red]✗ ERROR[/red]" if res["error"] else "[green]✓[/green]"
            progress.update(
                task,
                description=f"{status} [yellow]{key}[/yellow]",
                completed=res["fetched"],
                total=max(res["fetched"], 1),
                fetched=res["fetched"],
            )

    # Summary table
    table = Table(title="Ingest Results", box=rbox.ROUNDED, show_lines=True)
    table.add_column("Source", style="cyan")
    table.add_column("Fetched", justify="right")
    table.add_column("Inserted", justify="right", style="green")
    table.add_column("Status")

    for key, res in results.items():
        status = f"[red]{res['error'][:60]}[/red]" if res["error"] else "[green]OK[/green]"
        table.add_row(key, str(res["fetched"]), str(res["inserted"]), status)

    console.print(table)

    stats = db.stats()
    console.print(f"\n[bold]Total records in DB:[/bold] [cyan]{stats['total']:,}[/cyan]")


# ---------------------------------------------------------------------------
# query
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--category", "-c", multiple=True, help="Filter by category (repeatable).")
@click.option("--state",    "-st", multiple=True, help="Filter by 2-letter state code (repeatable).")
@click.option("--name",     "-n",  default=None,  help="Filter by name substring.")
@click.option("--bbox",     "-b",  default=None,
              help="Bounding box as 'minx,miny,maxx,maxy' (WGS84).")
@click.option("--limit",    "-l",  default=25, show_default=True, help="Max rows to display.")
@click.option("--json-out", "json_out", is_flag=True, help="Output raw JSON instead of table.")
@click.pass_context
def query(ctx, category, state, name, bbox, limit, json_out):
    """Query the database and display matching records."""
    db = ctx.obj["db"]

    bbox_tuple = None
    if bbox:
        try:
            bbox_tuple = tuple(float(x) for x in bbox.split(","))
        except ValueError:
            console.print("[red]Invalid bbox format. Use: minx,miny,maxx,maxy[/red]")
            sys.exit(1)

    gdf = db.query(
        categories=list(category) or None,
        states=list(state) or None,
        bbox=bbox_tuple,
        name_contains=name,
    )

    if gdf.empty:
        console.print("[yellow]No records match the given filters.[/yellow]")
        return

    console.print(f"[green]{len(gdf):,} record(s) found.[/green]  Showing up to {limit}.\n")
    subset = gdf.head(limit)

    if json_out:
        # Drop geometry for clean JSON output
        import pandas as pd
        df = pd.DataFrame(subset.drop(columns="geometry"))
        click.echo(df.to_json(orient="records", indent=2))
        return

    table = Table(box=rbox.SIMPLE_HEAD, show_lines=False)
    for col in ["name", "category", "state", "agency", "area_acres"]:
        table.add_column(col.replace("_", " ").title(), overflow="fold",
                         max_width=40 if col == "name" else 25)

    for _, row in subset.iterrows():
        acres = row.get("area_acres")
        acres_str = f"{float(acres):,.0f}" if acres and str(acres) not in ("nan", "None") else "—"
        table.add_row(
            str(row.get("name", "")),
            str(row.get("category", "")),
            str(row.get("state", "")),
            str(row.get("agency", "")),
            acres_str,
        )

    console.print(table)


# ---------------------------------------------------------------------------
# map
# ---------------------------------------------------------------------------

@cli.command("map")
@click.option("--output", "-o", default="public_lands_map.html",
              show_default=True, help="Output file path.")
@click.option("--format", "-f", "fmt",
              type=click.Choice(["interactive", "static"], case_sensitive=False),
              default="interactive", show_default=True, help="Map format.")
@click.option("--category", "-c", multiple=True, help="Filter by category.")
@click.option("--state",    "-st", multiple=True, help="Filter by state code.")
@click.option("--name",     "-n",  default=None,  help="Filter by name substring.")
@click.option("--bbox",     "-b",  default=None,  help="Bounding box: minx,miny,maxx,maxy.")
@click.option("--title",    "-t",  default="US Public Lands", help="Map title (static only).")
@click.option("--max-features", default=5000, show_default=True,
              help="Max features (interactive map performance limit).")
@click.pass_context
def map_cmd(ctx, output, fmt, category, state, name, bbox, title, max_features):
    """Generate an interactive HTML or static PNG map."""
    db = ctx.obj["db"]
    viz = Visualizer(db=db)

    bbox_tuple = None
    if bbox:
        bbox_tuple = tuple(float(x) for x in bbox.split(","))

    filters = dict(
        categories=list(category) or None,
        states=list(state) or None,
        bbox=bbox_tuple,
        name_contains=name,
    )

    with console.status(f"Generating [cyan]{fmt}[/cyan] map…"):
        if fmt == "interactive":
            out = viz.interactive_map(output_path=output, max_features=max_features, **filters)
        else:
            # Ensure .png extension for static
            if not output.endswith((".png", ".pdf", ".svg")):
                output += ".png"
            out = viz.static_map(output_path=output, title=title, **filters)

    console.print(f"[green]✓ Map saved to:[/green] [cyan]{out}[/cyan]")


# ---------------------------------------------------------------------------
# chart
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--output", "-o", default="public_lands_summary.png",
              show_default=True, help="Output file path.")
@click.pass_context
def chart(ctx, output):
    """Generate a summary bar chart of land types by count and acreage."""
    db = ctx.obj["db"]
    viz = Visualizer(db=db)

    with console.status("Generating summary chart…"):
        out = viz.summary_chart(output_path=output)

    console.print(f"[green]✓ Chart saved to:[/green] [cyan]{out}[/cyan]")


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--json-out", "json_out", is_flag=True, help="Output raw JSON.")
@click.pass_context
def stats(ctx, json_out):
    """Print database statistics."""
    db = ctx.obj["db"]
    s = db.stats()

    if json_out:
        click.echo(json.dumps(s, indent=2))
        return

    console.print(f"\n[bold]Database:[/bold] [cyan]{s.get('db_path', 'N/A')}[/cyan]")
    console.print(f"[bold]Size:[/bold]     [cyan]{s.get('db_size_mb', 0):.2f} MB[/cyan]")
    console.print(f"[bold]Total:[/bold]    [cyan]{s.get('total', 0):,}[/cyan] records\n")

    if s["by_category"]:
        table = Table(title="Records by Category", box=rbox.ROUNDED)
        table.add_column("Category", style="cyan")
        table.add_column("Count", justify="right", style="green")
        for cat, cnt in sorted(s["by_category"].items(), key=lambda x: -x[1]):
            table.add_row(cat, f"{cnt:,}")
        console.print(table)

    if s["by_state"]:
        table2 = Table(title="Top States", box=rbox.ROUNDED)
        table2.add_column("State", style="cyan")
        table2.add_column("Count", justify="right", style="green")
        for st, cnt in sorted(s["by_state"].items(), key=lambda x: -x[1])[:15]:
            table2.add_row(st, f"{cnt:,}")
        console.print(table2)


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("output_path")
@click.option("--format", "-f", "fmt",
              type=click.Choice(["geojson", "shp", "csv"], case_sensitive=False),
              default="geojson", show_default=True, help="Output format.")
@click.option("--category", "-c", multiple=True, help="Filter by category.")
@click.option("--state",    "-st", multiple=True, help="Filter by state code.")
@click.pass_context
def export(ctx, output_path, fmt, category, state):
    """Export the database to GeoJSON, Shapefile, or CSV."""
    db = ctx.obj["db"]

    gdf = db.query(
        categories=list(category) or None,
        states=list(state) or None,
    )

    if gdf.empty:
        console.print("[yellow]No records to export.[/yellow]")
        return

    fmt_lower = fmt.lower()
    with console.status(f"Exporting {len(gdf):,} records as {fmt}…"):
        if fmt_lower == "geojson":
            gdf.to_file(output_path, driver="GeoJSON")
        elif fmt_lower in ("shp", "shapefile"):
            gdf.to_file(output_path, driver="ESRI Shapefile")
        elif fmt_lower == "csv":
            import pandas as pd
            pd.DataFrame(gdf.drop(columns="geometry")).to_csv(output_path, index=False)

    console.print(f"[green]✓ Exported {len(gdf):,} records to:[/green] [cyan]{output_path}[/cyan]")


# ---------------------------------------------------------------------------
# sources  (informational)
# ---------------------------------------------------------------------------

@cli.command()
def sources():
    """List all configured data sources."""
    table = Table(title="Configured Data Sources", box=rbox.ROUNDED, show_lines=True)
    table.add_column("Key", style="cyan")
    table.add_column("Type")
    table.add_column("Category", style="yellow")
    table.add_column("Agency")
    table.add_column("URL", overflow="fold", max_width=55)

    for key, cfg in SOURCES.items():
        table.add_row(
            key,
            cfg.get("source_type", ""),
            cfg.get("category", ""),
            cfg.get("agency", ""),
            cfg.get("url", ""),
        )
    console.print(table)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    cli(obj={})


if __name__ == "__main__":
    main()
