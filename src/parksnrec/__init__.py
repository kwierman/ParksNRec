"""
public_lands - A Python package for ingesting and visualizing US public land boundaries.

Data sources:
  - National Parks: NPS IRMA Portal (ArcGIS REST)
  - National Forests: USFS FSGeodata Clearinghouse
  - BLM Lands: BLM GeoCommunicator ArcGIS REST
  - State Parks: PADUS (Protected Areas Database of the US) via OpenData
"""

__version__ = "1.0.0"
__author__ = "public_lands contributors"

from .database import Database
from .ingestor import DataIngestor
from .visualizer import Visualizer

__all__ = ["Database", "DataIngestor", "Visualizer"]
