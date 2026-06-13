from __future__ import annotations

from html import escape

from branca.element import MacroElement
from jinja2 import Template


class ImpactLegend(MacroElement):
    _template = Template(
        """
        {% macro html(this, kwargs) %}
        <div class="impact-map-legend">
          <strong>Legenda</strong>
          {{ this.entries_html }}
          <small>Sunt explicate numai layerele active implicit.</small>
        </div>
        <style>
          .impact-map-legend {
            position: fixed; left: 18px; bottom: 22px; z-index: 9999;
            background: rgba(255,255,255,.96); border: 1px solid #cbd5e1;
            border-radius: 6px; padding: 10px 12px; color: #0f172a;
            font: 12px/1.45 Arial, sans-serif; box-shadow: 0 2px 8px rgba(15,23,42,.18);
            max-height: 210px; overflow-y: auto; min-width: 190px;
          }
          .impact-map-legend div { margin: 6px 0; display:flex; align-items:center; gap:7px; }
          .impact-map-legend small { color:#64748b; display:block; max-width:210px; }
          .legend-swatch { width:22px; height:8px; border-radius:2px; display:inline-block; }
        </style>
        {% endmacro %}
        """
    )

    def __init__(self, entries: list[tuple[str, str]]) -> None:
        super().__init__()
        self._name = "ImpactLegend"
        self.entries_html = "".join(
            f'<div><span class="legend-swatch" style="background:{escape(color)}"></span>'
            f"{escape(label)}</div>"
            for label, color in entries
        )


def legend_entries(
    analysis_layers: list[dict] | None,
    has_buffer: bool,
    osm_layers: dict | None,
) -> list[tuple[str, str]]:
    entries = [("Județ / AOI", "#2563eb")]
    for layer in analysis_layers or []:
        entries.append((layer["name"], layer.get("color", "#64748b")))
    if has_buffer:
        entries.append(("Buffer de avertizare", "#f59e0b"))
    osm_entries = {
        "osm_buildings": (
            ("Clădiri intersectate direct", "#dc2626"),
            ("Clădiri în buffer", "#f97316"),
            ("Clădiri de referință", "#64748b"),
        ),
        "osm_roads": (
            ("Drumuri intersectate direct", "#dc2626"),
            ("Drumuri în buffer", "#f97316"),
        ),
        "osm_railways": (
            ("Căi ferate intersectate direct", "#dc2626"),
            ("Căi ferate în buffer", "#f97316"),
        ),
        "osm_bridges": (
            ("Poduri intersectate direct", "#dc2626"),
            ("Poduri în buffer", "#f97316"),
        ),
        "osm_critical": (
            ("Obiective critice intersectate direct", "#dc2626"),
            ("Obiective critice în buffer", "#f97316"),
        ),
    }
    for layer_id in (osm_layers or {}):
        entries.extend(osm_entries.get(layer_id, ()))
    return entries
