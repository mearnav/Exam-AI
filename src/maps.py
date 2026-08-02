import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import geopandas as gpd
from src import config

import json
from groq import Groq

_client = Groq(api_key=config.GROQ_API_KEY)

WORLD_URL = ("https://raw.githubusercontent.com/datasets/geo-countries/"
             "master/data/countries.geojson")

# Load once at import (cached in memory for reuse)
_world = None


def _get_world():
    """Load the world map once and reuse it."""
    global _world
    if _world is None:
        _world = gpd.read_file(WORLD_URL)
    return _world


def draw_country_outline(country: str, output_path: str) -> str | None:
    """Render a clean outline map of the given country as a PNG.
    Returns the path, or None if the country isn't found."""
    world = _get_world()
    shape = world[world["name"] == country]
    if len(shape) == 0:
        return None

    fig, ax = plt.subplots(figsize=(6, 6))
    shape.boundary.plot(ax=ax, linewidth=1.2, edgecolor="#2c3e50")
    shape.plot(ax=ax, color="#eef4fa")     # light fill
    ax.axis("off")
    ax.set_title(f"Map of {country}", fontsize=12, pad=10)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return output_path

def draw_labeling_map(country: str, markers: list[dict], output_path: str) -> str | None:
    """Render an accurate country map with numbered markers at given points.
    'markers' = [{'label': 'Delhi', 'lat': 28.6, 'lon': 77.2}, ...].
    The numbers appear on the map; the answer key holds what each number is."""
    world = _get_world()
    shape = world[world["name"] == country]
    if len(shape) == 0:
        return None

    fig, ax = plt.subplots(figsize=(6, 7))
    shape.plot(ax=ax, color="#eef4fa", edgecolor="#2c3e50", linewidth=1.2)
    ax.axis("off")
    ax.set_title(f"Map of {country} — identify the marked locations",
                 fontsize=11, pad=10)

    for i, m in enumerate(markers, start=1):
        lon, lat = m["lon"], m["lat"]
        # a dot at the real coordinate
        ax.plot(lon, lat, "o", markersize=6, color="#b32020", zorder=3)
        # the number label next to it (NOT the name — that's the answer)
        ax.annotate(str(i), xy=(lon, lat), xytext=(lon + 0.6, lat + 0.4),
                    fontsize=11, fontweight="bold", color="#b32020", zorder=4)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return output_path


def plan_map(question_text: str) -> dict:
    """Decide the map + markers for a map-labeling question. The LLM supplies
    well-known locations and coordinates; our code plots them accurately.
    Returns {'country': str, 'markers': [{'label','lat','lon'}, ...]}."""
    system = (
        "You set up a geography map-labeling question. Given the question, "
        "return ONLY JSON:\n"
        '{"country": "India", "markers": [{"label": "Delhi", "lat": 28.61, '
        '"lon": 77.21}, ...]}\n'
        "Rules:\n"
        "- Use 3-6 locations that are single POINTS: major cities or specific "
        "landmarks with one clear location (e.g. Delhi, Mumbai, Taj Mahal).\n"
        "- DO NOT use rivers, mountain ranges, forests, regions, or anything "
        "that spans a large area — those cannot be shown as a single point.\n"
        "- Use only well-known locations so coordinates are accurate.\n"
        "- 'lat' and 'lon' are decimal degrees. No text outside JSON."
    )
    resp = _client.chat.completions.create(
        model=config.TEXT_MODEL,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": question_text}],
        response_format={"type": "json_object"},
        temperature=0,
    )
    data = json.loads(resp.choices[0].message.content)
    return {
        "country": data.get("country", ""),
        "markers": _validate_markers(data.get("markers", [])),
    }


def _validate_markers(markers: list) -> list:
    """Keep only markers with sane coordinates — guards against bad LLM data."""
    clean = []
    for m in markers:
        try:
            lat, lon = float(m["lat"]), float(m["lon"])
        except (KeyError, ValueError, TypeError):
            continue
        # valid earth coordinates only
        if -90 <= lat <= 90 and -180 <= lon <= 180 and m.get("label"):
            clean.append({"label": str(m["label"]), "lat": lat, "lon": lon})
    return clean


if __name__ == "__main__":
    # Real coordinates of major Indian cities
    markers = [
        {"label": "Delhi", "lat": 28.61, "lon": 77.21},
        {"label": "Mumbai", "lat": 19.08, "lon": 72.88},
        {"label": "Kolkata", "lat": 22.57, "lon": 88.36},
        {"label": "Chennai", "lat": 13.08, "lon": 80.27},
    ]
    path = draw_labeling_map(
        "India", markers, os.path.join(config.OUTPUT_DIR, "test_india_labeled.png"))
    print("Labeling map saved to:", path)
    print("Answer key:", {i + 1: m["label"] for i, m in enumerate(markers)})

