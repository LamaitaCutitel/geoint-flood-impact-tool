from __future__ import annotations

from html import escape
from typing import Any
import warnings

import folium
from branca.element import MacroElement
from folium.plugins import MarkerCluster
from jinja2 import Template
from shapely.geometry import shape

from src.app_support.county_boundaries import county_display_name


def add_county_outlines(
    folium_map: folium.Map,
    counties_geojson: dict[str, Any] | None,
    selected_county: str,
) -> None:
    if not counties_geojson:
        return

    def style(feature: dict[str, Any]) -> dict[str, Any]:
        selected = county_display_name(feature) == selected_county
        return {
            "color": "#2563eb" if selected else "#64748b",
            "weight": 3 if selected else 1,
            "fillOpacity": 0,
        }

    folium.GeoJson(
        counties_geojson,
        name="Limite județe",
        control=False,
        style_function=style,
        tooltip=folium.GeoJsonTooltip(fields=["NAME_LATN"], aliases=["Județ"]),
        show=True,
    ).add_to(folium_map)


def add_aoi_layer(
    folium_map: folium.Map,
    aoi_geometry: dict[str, Any] | None,
) -> None:
    if not aoi_geometry:
        return
    folium.GeoJson(
        {
            "type": "Feature",
            "properties": {"name": "Zonă focală"},
            "geometry": aoi_geometry,
        },
        name="Zonă focală desenată",
        control=False,
        style_function=lambda _: {
            "color": "#16a34a",
            "weight": 3,
            "fillColor": "#22c55e",
            "fillOpacity": 0.08,
        },
        tooltip="Zonă focală activă",
        show=True,
    ).add_to(folium_map)


def add_tile_layers(folium_map: folium.Map, layers: list[dict[str, Any]]) -> None:
    for layer in layers:
        tile_url = layer.get("tile_url")
        if not tile_url:
            warnings.warn(
                f"Layerul activ '{layer.get('name', layer.get('id', 'necunoscut'))}' "
                "nu are tile_url si nu poate fi afisat.",
                UserWarning,
                stacklevel=2,
            )
            continue
        folium.TileLayer(
            tiles=tile_url,
            attr="Google Earth Engine",
            name=layer["name"],
            overlay=True,
            control=False,
            show=True,
        ).add_to(folium_map)


def add_buffer_layer(folium_map: folium.Map, geometry: dict[str, Any] | None) -> None:
    if not geometry:
        return
    folium.GeoJson(
        {"type": "Feature", "properties": {}, "geometry": geometry},
        name="Buffer de avertizare",
        control=False,
        style_function=lambda _: {
            "color": "#f59e0b",
            "weight": 2,
            "fillColor": "#facc15",
            "fillOpacity": 0.12,
        },
        show=True,
    ).add_to(folium_map)


def add_osm_layers(
    folium_map: folium.Map,
    layers: dict[str, dict[str, Any]],
) -> None:
    for layer_id, collection in layers.items():
        features = collection.get("features", [])
        if not features:
            continue
        group = folium.FeatureGroup(
            name=collection.get("display_name", layer_id),
            overlay=True,
            control=False,
            show=True,
        ).add_to(folium_map)
        vector_features = []
        reference_features = []
        if layer_id != "osm_critical":
            for feature in features:
                rendered = dict(feature)
                if layer_id == "osm_bridges":
                    rendered["geometry"] = (
                        feature.get("clipped_geometry") or feature.get("geometry")
                    )
                if (
                    layer_id == "osm_buildings"
                    and feature.get("properties", {}).get("status") == "Referință"
                ):
                    reference_features.append(rendered)
                else:
                    vector_features.append(rendered)
        if vector_features:
            folium.GeoJson(
                {"type": "FeatureCollection", "features": vector_features},
                control=False,
                style_function=lambda feature, current=layer_id: _osm_style(
                    current,
                    feature.get("properties", {}).get("status", ""),
                ),
                tooltip=_osm_tooltip(vector_features),
            ).add_to(group)
        if reference_features:
            reference_group = folium.FeatureGroup(
                name="Clădiri de referință",
                overlay=True,
                control=False,
                show=True,
            ).add_to(group)
            folium.GeoJson(
                {"type": "FeatureCollection", "features": reference_features},
                control=False,
                style_function=lambda feature: _osm_style(
                    "osm_buildings",
                    feature.get("properties", {}).get("status", ""),
                ),
                tooltip=_osm_tooltip(reference_features),
            ).add_to(reference_group)
            _ZoomVisibility(reference_group.get_name(), 14).add_to(folium_map)

        if layer_id in {"osm_critical", "osm_bridges"}:
            cluster = MarkerCluster(
                name=f"{layer_id}-markers",
                control=False,
                disableClusteringAtZoom=15,
            ).add_to(group)
            for feature in features:
                point = shape(feature.get("geometry") or {}).representative_point()
                properties = feature.get("properties", {})
                name = escape(str(properties.get("name") or _feature_label(layer_id)))
                category = escape(str(_feature_category(properties, layer_id)))
                status = escape(str(properties.get("status") or "Necunoscut"))
                distance = escape(str(properties.get("distance_to_water_m", "indisponibil")))
                address = escape(str(properties.get("address") or "indisponibil"))
                coordinates = escape(str(properties.get("coordinates") or "indisponibil"))
                source = escape(str(properties.get("source") or "OpenStreetMap"))
                folium.Marker(
                    [point.y, point.x],
                    icon=folium.DivIcon(
                        html=_svg_icon(
                            _icon_kind(properties, layer_id),
                            _status_color(properties.get("status", "")),
                        ),
                        icon_size=(30, 30),
                        icon_anchor=(15, 15),
                    ),
                    tooltip=f"{name} · {status}",
                    popup=folium.Popup(
                        f"<strong>{name}</strong><br>Categorie: {category}<br>"
                        f"Adresă: {address}<br>Coordonate: {coordinates}<br>"
                        f"Status: {status}<br>"
                        f"Distanță până la apă: {distance} m<br>"
                        f"Sursă: {source}",
                        max_width=320,
                    ),
                ).add_to(cluster)


def _status_color(status: str) -> str:
    if status == "Intersectat direct":
        return "#dc2626"
    if "buffer" in status.lower():
        return "#f97316"
    return "#64748b"


def _osm_style(layer_id: str, status: str) -> dict[str, Any]:
    color = _status_color(status)
    weights = {
        "osm_buildings": 1.5,
        "osm_roads": 4,
        "osm_railways": 3,
        "osm_bridges": 5,
    }
    return {
        "color": color,
        "weight": weights.get(layer_id, 2),
        "opacity": 0.95,
        "fillColor": color,
        "fillOpacity": 0.3 if layer_id == "osm_buildings" else 0,
    }


def _icon_kind(properties: dict[str, Any], layer_id: str) -> str:
    if layer_id == "osm_bridges":
        return "pod"
    tags = properties.get("tags") if isinstance(properties.get("tags"), dict) else properties
    amenity = tags.get("amenity") or tags.get("healthcare")
    names = {
        "hospital": "H",
        "clinic": "C",
        "doctors": "M",
        "pharmacy": "+",
        "fire_station": "P",
        "police": "Pol",
        "school": "S",
        "kindergarten": "S",
        "fuel": "B",
        "shelter": "A",
        "ambulance_station": "Amb",
        "railway_station": "G",
        "power_substation": "E",
        "power_plant": "E",
        "water_tower": "A",
        "wastewater_plant": "A",
    }
    normalized_category = tags.get("category")
    if normalized_category in names:
        return names[normalized_category]
    if amenity in names:
        return names[amenity]
    if tags.get("power"):
        return "E"
    if tags.get("railway") == "station":
        return "G"
    return "i"


def _svg_icon(label: str, color: str) -> str:
    safe_label = escape(label)
    return (
        '<div class="impact-osm-icon">'
        '<svg xmlns="http://www.w3.org/2000/svg" width="30" height="30" viewBox="0 0 30 30">'
        f'<circle cx="15" cy="15" r="12" fill="white" stroke="{color}" stroke-width="3"/>'
        f'<text x="15" y="19" text-anchor="middle" font-size="10" font-weight="700" fill="{color}">'
        f"{safe_label}</text></svg></div>"
    )


def _feature_label(layer_id: str) -> str:
    return "Pod" if layer_id == "osm_bridges" else "Obiectiv critic"


def _feature_category(properties: dict[str, Any], layer_id: str) -> str:
    if layer_id == "osm_bridges":
        return "Pod"
    tags = properties.get("tags") if isinstance(properties.get("tags"), dict) else properties
    return str(
        tags.get("amenity")
        or tags.get("healthcare")
        or tags.get("emergency")
        or tags.get("power")
        or "Obiectiv critic"
    )


def _osm_tooltip(features: list[dict[str, Any]]) -> folium.GeoJsonTooltip | None:
    property_sets = [
        set((feature.get("properties") or {}).keys())
        for feature in features
    ]
    if not property_sets:
        return None
    available = set.intersection(*property_sets)
    candidates = (
        ("name", "Nume"),
        ("status", "Status"),
        ("distance_to_water_m", "Distanță până la apă (m)"),
    )
    fields = [field for field, _ in candidates if field in available]
    if not fields:
        return None
    aliases = [alias for field, alias in candidates if field in available]
    return folium.GeoJsonTooltip(fields=fields, aliases=aliases, localize=True)


class _ZoomVisibility(MacroElement):
    _template = Template(
        """
        {% macro script(this, kwargs) %}
        (function () {
          var map = {{ this._parent.get_name() }};
          var layer = {{ this.layer_name }};
          function syncReferenceVisibility() {
            if (map.getZoom() >= {{ this.minimum_zoom }}) {
              if (!map.hasLayer(layer)) { layer.addTo(map); }
            } else if (map.hasLayer(layer)) {
              map.removeLayer(layer);
            }
          }
          map.on('zoomend', syncReferenceVisibility);
          syncReferenceVisibility();
        })();
        {% endmacro %}
        """
    )

    def __init__(self, layer_name: str, minimum_zoom: int) -> None:
        super().__init__()
        self._name = "ZoomVisibility"
        self.layer_name = layer_name
        self.minimum_zoom = minimum_zoom
