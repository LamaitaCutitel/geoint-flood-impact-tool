from __future__ import annotations

from html import escape
from typing import Any
import warnings

import folium
from folium.plugins import MarkerCluster
from shapely.geometry import shape

from src.app_support.county_boundaries import county_display_name
from src.impact_tool.osm_impact import normalized_feature_category


_LAYER_PREFIXES = {
    "sar_": "[SAR] ",
    "dynamic_world_": "[DW] ",
    "both_methods": "[DW] ",
    "only_sar": "[DW] ",
    "only_dynamic_world": "[DW] ",
}


def _prefixed_layer_name(layer: dict[str, Any]) -> str:
    name = str(layer.get("name") or layer.get("id") or "Layer")
    if name.startswith("["):
        return name
    layer_id = str(layer.get("id") or "")
    for prefix, label in _LAYER_PREFIXES.items():
        if layer_id.startswith(prefix):
            return f"{label}{name}"
    return name


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
        control=True,
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
        control=True,
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
            name=_prefixed_layer_name(layer),
            overlay=True,
            control=True,
            show=bool(layer.get("show", layer.get("shown", True))),
        ).add_to(folium_map)


def add_buffer_layer(folium_map: folium.Map, geometry: dict[str, Any] | None) -> None:
    if not geometry:
        return
    folium.GeoJson(
        {"type": "Feature", "properties": {}, "geometry": geometry},
        name="Buffer de avertizare",
        control=True,
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
        if layer_id == "osm_buildings":
            _add_building_groups(folium_map, features)
            continue
        group = folium.FeatureGroup(
            name=_osm_layer_name(layer_id, collection.get("display_name", layer_id)),
            overlay=True,
            control=True,
            show=bool(collection.get("show", True)),
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
                control=True,
                show=False,
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
                infrastructure_level = escape(
                    str(properties.get("infrastructure_level") or "context tehnic")
                )
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
                        f"Nivel infrastructură: {infrastructure_level}<br>"
                        f"Status expunere: {status}<br>"
                        f"Distanță până la apă: {distance} m<br>"
                        f"Adresă: {address}<br>Sursă: {source}<br>"
                        f"Coordonate: {coordinates}",
                        max_width=320,
                    ),
                ).add_to(cluster)


def _add_building_groups(
    folium_map: folium.Map,
    features: list[dict[str, Any]],
) -> None:
    definitions = (
        ("Intersectat direct", "[OSM] Clădiri direct intersectate", True),
        ("În buffer de avertizare", "[OSM] Clădiri în buffer", True),
        ("Referință", "[OSM] Clădiri de referință", False),
    )
    for status, name, shown in definitions:
        selected = [
            feature
            for feature in features
            if feature.get("properties", {}).get("status") == status
        ]
        if not selected:
            continue
        group = folium.FeatureGroup(
            name=name,
            overlay=True,
            control=True,
            show=shown,
        ).add_to(folium_map)
        folium.GeoJson(
            {"type": "FeatureCollection", "features": selected},
            control=False,
            style_function=lambda feature: _osm_style(
                "osm_buildings",
                feature.get("properties", {}).get("status", ""),
            ),
            tooltip=_osm_tooltip(selected),
        ).add_to(group)
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
        return "bridge"
    tags = properties.get("tags") if isinstance(properties.get("tags"), dict) else properties
    amenity = tags.get("amenity") or tags.get("healthcare")
    names = {
        "hospital": "medical",
        "clinic": "medical",
        "doctors": "medical",
        "pharmacy": "pharmacy",
        "fire_station": "fire",
        "police": "shield",
        "school": "school",
        "kindergarten": "school",
        "fuel": "fuel",
        "shelter": "shelter",
        "ambulance_station": "ambulance",
        "railway_station": "train",
        "power_substation": "power",
        "power_plant": "power",
        "water_tower": "water",
        "wastewater_plant": "water",
    }
    normalized_category = normalized_feature_category(properties)
    if normalized_category in names:
        return names[normalized_category]
    if amenity in names:
        return names[amenity]
    if tags.get("power"):
        return "power"
    if tags.get("railway") == "station":
        return "train"
    return "warning"


def _svg_icon(kind: str, color: str) -> str:
    paths = {
        "medical": '<path d="M13 7h4v6h6v4h-6v6h-4v-6H7v-4h6z"/>',
        "pharmacy": '<path d="M8 9h14v4H8zm5-4h4v20h-4z"/>',
        "fire": '<path d="M15 5c4 5 6 8 6 12a6 6 0 1 1-12 0c0-3 2-6 5-9 0 4 2 5 3 6 1-3 0-6-2-9z"/>',
        "shield": '<path d="M15 4l9 4v7c0 6-4 9-9 11-5-2-9-5-9-11V8z"/>',
        "school": '<path d="M3 11l12-6 12 6-12 6zm5 4l7 4 7-4v6l-7 4-7-4z"/>',
        "fuel": '<path d="M7 5h10v20H7zm3 3v6h4V8zm8 3h3l3 4v9h-3v-7h-3z"/>',
        "shelter": '<path d="M4 14L15 5l11 9-3 1v10h-6v-7h-4v7H7V15z"/>',
        "ambulance": '<path d="M3 10h14v11H3zm14 4h5l4 4v3h-9zM8 12h4v2h2v4h-2v2H8v-2H6v-4h2z"/>',
        "train": '<path d="M7 5h16v15l-3 4h-2l2-4H10l2 4h-2l-3-4zm3 3v7h10V8z"/>',
        "power": '<path d="M17 3L7 17h7l-1 10 10-14h-7z"/>',
        "water": '<path d="M15 3C11 9 8 13 8 18a7 7 0 0 0 14 0c0-5-3-9-7-15z"/>',
        "bridge": '<path d="M4 20h22v4H4zm3-2c1-7 5-11 8-11s7 4 8 11h-4c-1-4-2-7-4-7s-3 3-4 7z"/>',
        "warning": '<path d="M15 3L28 26H2zm-2 8v8h4v-8zm0 10v4h4v-4z"/>',
    }
    path = paths.get(kind, paths["warning"])
    return (
        '<div class="impact-osm-icon">'
        '<svg xmlns="http://www.w3.org/2000/svg" width="30" height="30" viewBox="0 0 30 30">'
        f'<circle cx="15" cy="15" r="13" fill="white" stroke="{color}" stroke-width="2"/>'
        f'<g fill="{color}">{path}</g></svg></div>'
    )


def _feature_label(layer_id: str) -> str:
    return "Pod" if layer_id == "osm_bridges" else "Obiectiv critic"


def _feature_category(properties: dict[str, Any], layer_id: str) -> str:
    if layer_id == "osm_bridges":
        return "Pod"
    return normalized_feature_category(properties) or "Obiectiv critic"


def _osm_layer_name(layer_id: str, display_name: str) -> str:
    names = {
        "osm_roads": "[OSM] Drumuri afectate",
        "osm_railways": "[OSM] Căi ferate afectate",
        "osm_bridges": "[OSM] Poduri",
        "osm_critical": "[OSM] Obiective importante",
    }
    return names.get(layer_id, f"[OSM] {display_name}")


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
