from __future__ import annotations

import base64
import hashlib
from io import BytesIO
import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from pyproj import Geod
from shapely.geometry import shape

from src.impact_tool.cache import PersistentCache
from src.impact_tool.models import ImpactToolState


REPORT_VERSION = "4.1"
DEFAULT_REPORTS_DIR = Path(__file__).resolve().parents[2] / "data" / "output" / "reports"
MANDATORY_NOTE = (
    "Rezultatele reprezintă produse GEOINT preliminare de suport decizional "
    "și nu constituie confirmare oficială din teren."
)
MANDATORY_NOTE_MARKER = "GEOINT_PRELIMINARY_NOT_OFFICIAL"
STRUCTURE_MARKER = "GEOINT_TABLES_AND_CHARTS"


def report_filename(state: ImpactToolState) -> str:
    event_date = state.event_date or "data-neprecizata"
    if event_date == "data-neprecizata" and state.after_scene:
        event_date = str(state.after_scene.get("acquisition_time", ""))[:10]
    county = state.county_name.lower().replace(" ", "_")
    return f"raport_geoint_inundatie_{county}_{event_date}.pdf"


def generate_cached_report(
    state: ImpactToolState,
    cache: PersistentCache | None = None,
) -> tuple[bytes, bool]:
    cache = cache or PersistentCache()
    key = _report_cache_key(cache, state)
    cached = cache.get("reports", key)
    if cached.hit and isinstance(cached.value, str):
        return base64.b64decode(cached.value), True
    pdf = generate_report_pdf(state)
    cache.set("reports", key, base64.b64encode(pdf).decode("ascii"))
    return pdf, False


def save_report_pdf(
    state: ImpactToolState,
    pdf: bytes,
    output_dir: Path | str | None = None,
) -> Path:
    destination = Path(output_dir) if output_dir else DEFAULT_REPORTS_DIR
    destination.mkdir(parents=True, exist_ok=True)
    report_path = destination / report_filename(state)
    report_path.write_bytes(pdf)
    return report_path


def _report_cache_key(cache: PersistentCache, state: ImpactToolState) -> str:
    dynamic = state.analysis_results.get("dynamic_world") or {}
    payload = {
        "analysis_hash": state.analysis_hash,
        "buffer_meters": state.buffer_meters,
        "osm_metadata": state.osm_status,
        "dynamic_world_dates": dynamic.get("acquisition_dates", {}),
        "dynamic_world_products": dynamic.get("product_types", {}),
        "sar_metrics": (state.analysis_results.get("sar") or {}).get("metrics", {}),
        "dynamic_world_status": dynamic.get("status"),
        "dynamic_world_metrics": dynamic.get("metric_values", {}),
        "osm_metrics": (state.analysis_results.get("osm_impact") or {}).get(
            "metrics",
            {},
        ),
        "osm_dynamic_world": state.analysis_results.get("osm_dynamic_world", {}),
        "timings": state.timings,
        "analysis_mode": state.analysis_mode,
        "scene_pair_validation": state.scene_pair_validation,
        "sar_threshold_mode": state.sar_threshold_mode,
        "report_version": REPORT_VERSION,
    }
    payload_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str).encode(
            "utf-8"
        )
    ).hexdigest()
    return cache.key("reports", payload_hash)


def generate_report_pdf(state: ImpactToolState) -> bytes:
    output = BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=1.5 * cm,
        leftMargin=1.5 * cm,
        topMargin=1.4 * cm,
        bottomMargin=1.4 * cm,
        title="Raport GEOINT privind impactul unei inundații",
        subject=MANDATORY_NOTE_MARKER,
        keywords=STRUCTURE_MARKER,
        pageCompression=0,
    )
    styles = getSampleStyleSheet()
    _configure_fonts(styles)
    styles.add(
        ParagraphStyle(
            name="CoverTitle",
            parent=styles["Title"],
            alignment=TA_CENTER,
            fontSize=24,
            leading=30,
            textColor=colors.HexColor("#0f172a"),
            spaceAfter=18,
            fontName="ImpactSans",
        )
    )
    story: list[Any] = [
        Spacer(1, 3 * cm),
        Paragraph("Evaluarea impactului unei inundații", styles["CoverTitle"]),
        Paragraph("Analiză multisursă SAR, Dynamic World și OpenStreetMap", styles["Heading2"]),
        Spacer(1, 1 * cm),
        _summary_table(state),
        Spacer(1, 1 * cm),
        Paragraph(MANDATORY_NOTE, styles["Italic"]),
        PageBreak(),
    ]
    _section(story, styles, "1. Rezumat executiv", _executive_summary(state))
    _section(
        story,
        styles,
        "2. Județ și AOI",
        f"Județ analizat: {state.county_name}. Arie activă: "
        f"{'AOI desenat' if state.aoi_active else 'județ complet'}, "
        f"{state.active_area_km2:.2f} km².",
    )
    _section(story, styles, "3. Buffer utilizat", f"Buffer de avertizare: {state.buffer_meters} m.")
    _section(story, styles, "4. Scene Sentinel-1 BEFORE / AFTER", "")
    story.append(_scene_table(state))
    _section(
        story,
        styles,
        "5. Metodologia SAR",
        "Analiza este strict BEFORE / AFTER. Apa nouă evidențiată prin SAR este "
        "diferența dintre apa observată AFTER și apa observată BEFORE, după filtrarea "
        "pixelilor izolați și decuparea la aria activă.",
    )
    _section(story, styles, "6. Rezultatele SAR", "")
    story.append(_metrics_table((state.analysis_results.get("sar") or {}).get("metrics", {})))
    _section(
        story,
        styles,
        "6.1 Justificarea pragului SAR",
        "Analiza de sensibilitate este un instrument QA separat și nu schimbă "
        "metodologia principală BEFORE / AFTER.",
    )
    story.append(_sar_qa_table(state))
    _section(story, styles, "7. Dynamic World", _dynamic_world_summary(state))
    _section(
        story,
        styles,
        "7.1 Disponibilitatea layerelor Dynamic World",
        _dynamic_world_tile_summary(state),
    )
    _section(story, styles, "8. Corelare SAR × Dynamic World", _correlation_summary(state))
    _section(
        story,
        styles,
        "9. Impact OSM",
        "Datele OSM sunt încărcate separat după analiza SAR. Geoapify Places "
        "furnizează obiective importante, iar Overpass furnizează infrastructura "
        "țintită numai în extinderea apei noi și bufferul de avertizare. "
        + _osm_summary(state),
    )
    _section(
        story,
        styles,
        "10. Analiza OSM × Dynamic World",
        "Elementele OSM sunt interpretate ca potențial expuse și necesită verificare în teren.",
    )
    story.append(Paragraph("Corelare OSM × Dynamic World", styles["Heading3"]))
    story.append(Paragraph(_osm_dynamic_world_summary(state), styles["BodyText"]))
    story.append(_osm_dynamic_world_table(state))
    story.append(Paragraph("Completitudine OpenStreetMap", styles["Heading3"]))
    story.append(_osm_status_table(state))
    story.append(PageBreak())
    _section(story, styles, "11. Harta sintetică a impactului inundației", "")
    story.append(Image(_synthetic_map(state), width=17 * cm, height=9.5 * cm))
    _section(story, styles, "12. Grafice", "")
    for title, values in _chart_datasets(state):
        story.append(Paragraph(title, styles["Heading3"]))
        story.append(Image(_bar_chart(title, values), width=15.5 * cm, height=6 * cm))
    _section(story, styles, "13. Tabele detaliate", "")
    story.append(_metrics_table((state.analysis_results.get("osm_impact") or {}).get("metrics", {})))
    _section(
        story,
        styles,
        "14. Limitări",
        "Limitările includ sensibilitatea SAR la geometria de achiziție și rugozitatea "
        "suprafeței, clasificarea automată Dynamic World, completitudinea variabilă OSM, "
        "decalaje temporale și necesitatea verificării în teren. MapTiler este folosit "
        "numai pentru vizualizare contextuală și nu contribuie la statisticile exacte.",
    )
    _section(
        story,
        styles,
        "15. Surse",
        _source_summary(state),
    )
    _section(story, styles, "16. Anexă tehnică", "")
    story.append(_parameters_table(state))
    _section(
        story,
        styles,
        "17. Durata procesării",
        _timings_summary(state),
    )
    _section(
        story,
        styles,
        "18. Informații cache",
        " | ".join(state.cache_events[-8:]) or "Nu există evenimente cache înregistrate.",
    )
    story.append(Paragraph(MANDATORY_NOTE, styles["Italic"]))
    document.build(story)
    return output.getvalue()


def validate_report_pdf(
    pdf: bytes,
    path: Path | str | None = None,
) -> dict[str, Any]:
    report_path = Path(path) if path else None
    page_count = len(re.findall(rb"/Type\s*/Page(?!s)\b", pdf))
    note_present = MANDATORY_NOTE_MARKER.encode("ascii") in pdf
    structure_present = STRUCTURE_MARKER.encode("ascii") in pdf
    valid = (
        pdf.startswith(b"%PDF")
        and b"%%EOF" in pdf[-1024:]
        and page_count > 0
        and note_present
        and structure_present
        and (report_path is None or report_path.is_file())
    )
    return {
        "status": "disponibil" if valid else "eroare",
        "path": str(report_path) if report_path else None,
        "exists": report_path.is_file() if report_path else True,
        "size_bytes": len(pdf),
        "page_count": page_count,
        "mandatory_note_present": note_present,
        "tables_and_charts_present": structure_present,
        "error": None if valid else "Validarea structurală PDF a eșuat.",
    }


def _configure_fonts(styles: Any) -> None:
    if "ImpactSans" not in pdfmetrics.getRegisteredFontNames():
        font_root = matplotlib.get_data_path() + "/fonts/ttf/"
        pdfmetrics.registerFont(
            TTFont("ImpactSans", font_root + "DejaVuSans.ttf")
        )
        pdfmetrics.registerFont(
            TTFont("ImpactSans-Bold", font_root + "DejaVuSans-Bold.ttf")
        )
        pdfmetrics.registerFont(
            TTFont("ImpactSans-Italic", font_root + "DejaVuSans-Oblique.ttf")
        )
    for name in ("Normal", "BodyText"):
        styles[name].fontName = "ImpactSans"
    for name in ("Title", "Heading1", "Heading2", "Heading3"):
        styles[name].fontName = "ImpactSans-Bold"
    styles["Italic"].fontName = "ImpactSans-Italic"


def _section(story: list[Any], styles: Any, title: str, text: str) -> None:
    story.append(Paragraph(title, styles["Heading2"]))
    if text:
        story.append(Paragraph(text, styles["BodyText"]))
    story.append(Spacer(1, 0.25 * cm))


def _summary_table(state: ImpactToolState) -> Table:
    table = Table(
        [
            ["Județ", state.county_name],
            ["Arie activă", f"{state.active_area_km2:.2f} km²"],
            ["Buffer", f"{state.buffer_meters} m"],
            ["Generat la", datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")],
            ["Metodă principală", "Apă nouă evidențiată prin SAR"],
        ],
        colWidths=[5 * cm, 9 * cm],
    )
    table.setStyle(_table_style())
    return table


def _scene_table(state: ImpactToolState) -> Table:
    rows = [["Rol", "Data", "Polarizare", "Orbit pass", "Orbită relativă"]]
    for role, scene in (("BEFORE", state.before_scene), ("AFTER", state.after_scene)):
        scene = scene or {}
        rows.append(
            [
                role,
                str(scene.get("acquisition_time", "[NECALCULAT]"))[:19],
                scene.get("polarization", "[NECALCULAT]"),
                scene.get("orbit_pass", "[NECALCULAT]"),
                scene.get("relative_orbit", "[NECALCULAT]"),
            ]
        )
    compatibility = state.scene_pair_validation.get("compatibility", {})
    overrides = state.scene_pair_validation.get("overrides", {})
    rows.append(
        [
            "COMPATIBILITATE",
            "orbită relativă identică"
            if compatibility.get("same_relative_orbit")
            else "orbită relativă diferită",
            "override experimental"
            if overrides.get("relative_orbit_experimental")
            else "fără override",
            "acoperire acceptată"
            if overrides.get("low_coverage")
            else "prag final standard",
            state.sar_threshold_mode,
        ]
    )
    table = Table(rows, repeatRows=1)
    table.setStyle(_table_style())
    return table


def _metrics_table(metrics: dict[str, Any]) -> Table:
    rows = [["Indicator", "Valoare"]]
    rows.extend(
        [[_metric_label(key), _format_value(value)] for key, value in metrics.items()]
        or [["Date", "indisponibile"]]
    )
    table = Table(rows, repeatRows=1, colWidths=[10 * cm, 5 * cm])
    table.setStyle(_table_style())
    return table


def _parameters_table(state: ImpactToolState) -> Table:
    rows = [["Parametru", "Valoare"]]
    rows.extend(
        [
            [_metric_label(str(key)), _format_value(value)]
            for key, value in state.analysis_parameters.items()
        ]
        or [["Parametri", "indisponibili"]]
    )
    table = Table(rows, repeatRows=1, colWidths=[10 * cm, 5 * cm])
    table.setStyle(_table_style())
    return table


def _sar_qa_table(state: ImpactToolState) -> Table:
    qa = state.analysis_results.get("sar_qa") or {}
    rows = [[
        "Prag dB",
        "Apă BEFORE km²",
        "Apă AFTER km²",
        "Apă nouă km²",
        "Diferență vs echilibrat",
        "Status",
    ]]
    for item in qa.get("rows", []):
        rows.append(
            [
                item.get("threshold_db"),
                _format_value(item.get("water_before_km2")),
                _format_value(item.get("water_after_km2")),
                _format_value(item.get("new_water_km2")),
                (
                    f"{item['difference_from_balanced_percent']:.2f}%"
                    if item.get("difference_from_balanced_percent") is not None
                    else "[NECALCULAT]"
                ),
                item.get("status", "[NECALCULAT]"),
            ]
        )
    if len(rows) == 1:
        rows.append(
            [
                "[NEVALIDAT TEHNIC]",
                "-",
                "-",
                "-",
                "-",
                "QA nerulat",
            ]
        )
    table = Table(rows, repeatRows=1)
    table.setStyle(_table_style())
    return table


METRIC_LABELS = {
    "sar_water_before_area_km2": "Suprafață apă BEFORE (km²)",
    "sar_water_after_area_km2": "Suprafață apă AFTER (km²)",
    "sar_new_water_area_km2": "Extindere preliminară SAR (km²)",
    "buildings_direct": "Clădiri intersectate direct",
    "buildings_buffer": "Clădiri în buffer",
    "buildings_area_m2": "Suprafață totală clădiri (m²)",
    "buildings_overlap_m2": "Suprapunere clădiri-apă (m²)",
    "buildings_complete": "Clădiri complet intersectate",
    "buildings_partial": "Clădiri parțial intersectate",
    "roads_direct_km": "Drumuri intersectate direct (km)",
    "roads_buffer_km": "Drumuri în buffer (km)",
    "railways_direct_km": "Căi ferate intersectate direct (km)",
    "railways_buffer_km": "Căi ferate în buffer (km)",
    "bridges_direct": "Poduri intersectate direct",
    "bridges_buffer": "Poduri în buffer",
    "critical_direct": "Obiective critice intersectate direct",
    "critical_buffer": "Obiective critice în buffer",
}


def _metric_label(key: str) -> str:
    return METRIC_LABELS.get(key, key.replace("_", " ").capitalize())


def _format_value(value: Any) -> str:
    if isinstance(value, dict) and {"status", "value", "error"} <= set(value):
        if value.get("status") == "reușit":
            return _format_value(value.get("value"))
        return f"[NECALCULAT] {value.get('error') or value.get('status')}"
    if isinstance(value, dict):
        return "; ".join(
            f"{_metric_label(str(key))}: {_format_value(item)}"
            for key, item in value.items()
        ) or "indisponibil"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def _dynamic_metric_value(result: dict[str, Any], key: str) -> float:
    if key in result.get("metric_values", {}):
        return float(result["metric_values"][key])
    item = result.get("metrics", {}).get(key, 0)
    if isinstance(item, dict):
        value = item.get("value")
        return float(value) if value is not None else 0.0
    return float(item or 0)


def _osm_status_table(state: ImpactToolState) -> Table:
    rows = [[
        "Categorie OSM",
        "Obiecte",
        "Sursă",
        "Data cache",
        "Completitudine",
        "Durată",
    ]]
    for category, status in state.osm_status.items():
        rows.append(
            [
                category.capitalize(),
                str(status.get("count", 0)),
                status.get("source", "indisponibil"),
                str(status.get("cache_date", "indisponibil"))[:19],
                status.get("completeness", "necunoscută"),
                (
                    f"{float(status['duration_seconds']):.2f} s"
                    if status.get("duration_seconds") is not None
                    else "indisponibilă"
                ),
            ]
        )
    if len(rows) == 1:
        rows.append([
            "Date OSM",
            "indisponibil",
            "indisponibil",
            "indisponibil",
            "necunoscută",
            "indisponibilă",
        ])
    table = Table(rows, repeatRows=1)
    table.setStyle(_table_style())
    return table


def _osm_dynamic_world_summary(state: ImpactToolState) -> str:
    dynamic = state.analysis_results.get("dynamic_world") or {}
    osm = state.analysis_results.get("osm_impact") or {}
    overlap = _dynamic_metric_value(
        dynamic,
        "sar_dynamic_world_new_water_overlap_area_km2",
    )
    affected = (osm.get("metrics") or {}).get("status_counts", {})
    return (
        f"Suprapunerea SAR–Dynamic World calculată este {overlap} km². "
        f"Distribuția geometrică a elementelor OSM este: {_format_value(affected)}. "
        "Interpretarea este preliminară și necesită verificare în teren."
    )


def _osm_dynamic_world_table(state: ImpactToolState) -> Table:
    rows = [[
        "Element OSM",
        "Clasă BEFORE",
        "Clasă AFTER",
        "Tranziție",
        "Status expunere",
    ]]
    correlation = state.analysis_results.get("osm_dynamic_world") or {}
    for item in correlation.get("rows", [])[:100]:
        rows.append(
            [
                item.get("name") or item.get("feature_key", "fără nume"),
                item.get("before_class", "indisponibil"),
                item.get("after_class", "indisponibil"),
                item.get("transition", "indisponibil"),
                item.get("status", "indisponibil"),
            ]
        )
    if len(rows) == 1:
        rows.append([
            "Date indisponibile",
            "-",
            "-",
            "-",
            correlation.get("error", "Corelarea nu a fost calculată."),
        ])
    table = Table(rows, repeatRows=1)
    table.setStyle(_table_style())
    return table


def _table_style() -> TableStyle:
    return TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
            ("FONTNAME", (0, 0), (-1, -1), "ImpactSans"),
            ("FONTNAME", (0, 0), (-1, 0), "ImpactSans-Bold"),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("PADDING", (0, 0), (-1, -1), 6),
        ]
    )


def _executive_summary(state: ImpactToolState) -> str:
    metrics = (state.analysis_results.get("sar") or {}).get("metrics", {})
    new_water = _metric_numeric_value(metrics.get("sar_new_water_area_km2"))
    return (
        f"Analiza preliminară a evidențiat "
        f"{_format_value(new_water) if new_water is not None else '[NECALCULAT]'} km² "
        "de apă nouă prin SAR. "
        "Rezultatul este destinat suportului decizional."
    )


def _metric_numeric_value(metric: Any) -> float | None:
    if isinstance(metric, dict):
        if metric.get("status") != "reușit" or metric.get("value") is None:
            return None
        return float(metric["value"])
    if metric is None:
        return None
    return float(metric)


def _dynamic_world_summary(state: ImpactToolState) -> str:
    result = state.analysis_results.get("dynamic_world")
    if not result:
        return "Dynamic World nu a fost disponibil pentru această analiză."
    periods = result.get("periods", {})
    dates = result.get("acquisition_dates", {})
    coverage = result.get("coverage", {})
    product_types = result.get("product_types", {})
    return (
        f"Status: {result.get('status', 'indisponibil')}. "
        f"Sursă: {result.get('source', 'Google Dynamic World V1')}. "
        f"Durată: {_duration_label(result.get('duration_seconds'))}. "
        f"BEFORE: perioada {periods.get('before', 'indisponibilă')}, "
        f"data efectivă {dates.get('before', 'indisponibilă')}, "
        f"acoperire {_coverage_label(coverage.get('before'))}, "
        f"produs {product_types.get('before', 'indisponibil')}. "
        f"AFTER: perioada {periods.get('after', 'indisponibilă')}, "
        f"data efectivă {dates.get('after', 'indisponibilă')}, "
        f"acoperire {_coverage_label(coverage.get('after'))}, "
        f"produs {product_types.get('after', 'indisponibil')}."
    )


def _dynamic_world_tile_summary(state: ImpactToolState) -> str:
    result = state.analysis_results.get("dynamic_world") or {}
    tiles = result.get("tiles") or {}
    if not tiles:
        return "Nu există informații despre tile-urile Dynamic World."
    labels = {
        "dynamic_world_before": "BEFORE",
        "dynamic_world_after": "AFTER",
        "dynamic_world_changes": "diferențe observate",
        "dynamic_world_new_water": "apă nouă",
        "both_methods": "suprapunere SAR × Dynamic World",
        "only_sar": "doar SAR",
        "only_dynamic_world": "doar Dynamic World",
    }
    rows = []
    for layer_id, tile in tiles.items():
        if isinstance(tile, dict):
            status = tile.get("status", "indisponibil")
            error = tile.get("error")
        else:
            status = "reușit" if tile else "tile indisponibil"
            error = None
        detail = f"{labels.get(layer_id, layer_id)}: {status}"
        if error:
            detail += f" ({error})"
        rows.append(detail)
    return "; ".join(rows) + "."


def _correlation_summary(state: ImpactToolState) -> str:
    result = state.analysis_results.get("dynamic_world")
    if not result:
        return "Corelarea multisursă nu este disponibilă."
    overlap = _dynamic_metric_value(
        result,
        "sar_dynamic_world_new_water_overlap_area_km2",
    )
    only_sar = _dynamic_metric_value(result, "new_water_only_sar_area_km2")
    only_dynamic = _dynamic_metric_value(
        result,
        "new_water_only_dynamic_world_area_km2",
    )
    return (
        f"Suprapunere între metode: {overlap:.3f} km². "
        f"Apă nouă doar SAR: {only_sar:.3f} km². "
        f"Apă nouă doar Dynamic World: {only_dynamic:.3f} km²."
    )


def _osm_summary(state: ImpactToolState) -> str:
    impact = state.analysis_results.get("osm_impact")
    if not impact:
        return "Datele OSM sunt indisponibile sau parțiale."
    metrics = impact.get("metrics", {})
    if not metrics:
        return "Metricile de impact OSM sunt indisponibile."
    return (
        f"Clădiri intersectate direct: {_metric_or_unavailable(metrics, 'buildings_direct')}; "
        f"clădiri în buffer: {_metric_or_unavailable(metrics, 'buildings_buffer')}; "
        f"drumuri intersectate direct: {_metric_or_unavailable(metrics, 'roads_direct_km', ' km')}; "
        f"drumuri în buffer: {_metric_or_unavailable(metrics, 'roads_buffer_km', ' km')}; "
        f"căi ferate intersectate direct: "
        f"{_metric_or_unavailable(metrics, 'railways_direct_km', ' km')}; "
        f"căi ferate în buffer: {_metric_or_unavailable(metrics, 'railways_buffer_km', ' km')}; "
        f"poduri intersectate direct: {_metric_or_unavailable(metrics, 'bridges_direct')}; "
        f"poduri în buffer: {_metric_or_unavailable(metrics, 'bridges_buffer')}; "
        f"obiective importante intersectate direct: "
        f"{_metric_or_unavailable(metrics, 'important_features_direct')}; "
        f"obiective importante în buffer: "
        f"{_metric_or_unavailable(metrics, 'important_features_buffer')}."
    )


def _coverage_label(value: Any) -> str:
    if value is None:
        return "indisponibilă"
    return f"{float(value) * 100:.1f}%"


def _duration_label(value: Any) -> str:
    if value is None:
        return "indisponibilă"
    return f"{float(value):.2f} s"


def _metric_or_unavailable(
    metrics: dict[str, Any],
    key: str,
    suffix: str = "",
) -> str:
    value = metrics.get(key)
    if value is None:
        return "indisponibil"
    if isinstance(value, float):
        return f"{value:.3f}{suffix}"
    return f"{value}{suffix}"


def _timings_summary(state: ImpactToolState) -> str:
    if not state.timings:
        duration = (state.analysis_results.get("sar") or {}).get(
            "duration_seconds",
            0,
        )
        return f"SAR: {float(duration):.3f} s."
    return "; ".join(
        f"{stage}: {float(seconds):.3f} s"
        for stage, seconds in state.timings.items()
    ) + "."


def _source_summary(state: ImpactToolState) -> str:
    osm_sources = sorted(
        {
            str(status.get("source", "indisponibil"))
            for status in state.osm_status.values()
        }
    )
    last_runs = sorted(
        {
            str(status.get("last_run"))[:19]
            for status in state.osm_status.values()
            if status.get("last_run")
        }
    )
    warnings = sorted(
        {
            warning
            for status in state.osm_status.values()
            for warning in status.get("warnings", [])
            if warning
        }
    )
    return (
        "Copernicus Sentinel-1 pentru metodologia SAR; Google Dynamic World pentru "
        "diferențe observate opționale; Geoapify Places pentru obiective importante; "
        "Overpass API pentru infrastructura OSM țintită; MapTiler numai pentru "
        "vizualizare contextuală. © OpenStreetMap contributors. "
        f"Sursă OSM: {', '.join(osm_sources) or 'indisponibilă'}. "
        f"Ultima rulare OSM: {', '.join(last_runs) or 'indisponibilă'}. "
        f"Avertismente: {'; '.join(warnings) or 'niciunul raportat'}."
    )


def _synthetic_map(state: ImpactToolState) -> BytesIO:
    figure, axis = plt.subplots(figsize=(10, 5.5))
    axis.set_facecolor("#f8fafc")
    _plot_geometry(axis, state.active_geometry, "#2563eb", 1.5, 0.02)
    sar = state.analysis_results.get("sar") or {}
    _plot_geometry(
        axis,
        sar.get("new_water_display_geometry") or sar.get("new_water_geometry"),
        "#06b6d4",
        1.2,
        0.6,
    )
    impact = state.analysis_results.get("osm_impact") or {}
    _plot_geometry(axis, impact.get("buffer_geometry"), "#f59e0b", 1.0, 0.12)
    layer_styles = {
        "osm_buildings": ("#dc2626", 0.8, 0.28),
        "osm_roads": ("#f97316", 1.4, 0.9),
        "osm_railways": ("#7c3aed", 1.2, 0.9),
        "osm_bridges": ("#0ea5e9", 2.0, 0.9),
        "osm_critical": ("#b91c1c", 1.0, 1.0),
    }
    for layer_id, layer in impact.get("layers", {}).items():
        color, width, alpha = layer_styles.get(layer_id, ("#64748b", 1.0, 0.7))
        for feature in layer.get("features", []):
            if feature.get("properties", {}).get("status") == "Neexpus":
                continue
            geometry = (
                feature.get("clipped_geometry")
                if layer_id in {"osm_roads", "osm_railways", "osm_bridges"}
                else None
            ) or feature.get("geometry")
            _plot_osm_feature(axis, geometry, color, width, alpha)
    axis.set_title("Harta sintetică a impactului inundației")
    axis.grid(color="#e2e8f0", linewidth=0.5)
    axis.annotate(
        "N",
        xy=(0.96, 0.92),
        xytext=(0.96, 0.78),
        xycoords="axes fraction",
        arrowprops={"arrowstyle": "-|>", "color": "#0f172a", "lw": 1.5},
        ha="center",
        fontsize=11,
        fontweight="bold",
    )
    x_min, x_max = axis.get_xlim()
    y_min, y_max = axis.get_ylim()
    scale_width, scale_label = _real_scale_bar(x_min, x_max, (y_min + y_max) / 2)
    scale_y = y_min + (y_max - y_min) * 0.06
    scale_x = x_min + (x_max - x_min) * 0.05
    axis.plot([scale_x, scale_x + scale_width], [scale_y, scale_y], color="#0f172a", linewidth=3)
    axis.text(
        scale_x,
        scale_y + (y_max - y_min) * 0.02,
        scale_label,
        fontsize=7,
    )
    axis.legend(
        handles=[
            Patch(facecolor="#06b6d4", alpha=0.6, label="Apă nouă SAR"),
            Patch(facecolor="#f59e0b", alpha=0.2, label="Buffer"),
            Patch(facecolor="#dc2626", alpha=0.35, label="Clădiri"),
            Line2D([0], [0], color="#f97316", lw=2, label="Drumuri"),
            Line2D([0], [0], color="#7c3aed", lw=2, label="Căi ferate"),
            Line2D([0], [0], color="#0ea5e9", lw=2, label="Poduri"),
            Line2D([0], [0], marker="o", color="w", markerfacecolor="#b91c1c", label="Obiective"),
        ],
        loc="lower right",
        fontsize=7,
    )
    output = BytesIO()
    figure.subplots_adjust(left=0.08, right=0.98, bottom=0.12, top=0.9)
    figure.savefig(output, format="png", dpi=140)
    plt.close(figure)
    output.seek(0)
    return output


def _real_scale_bar(
    x_min: float,
    x_max: float,
    latitude: float,
) -> tuple[float, str]:
    span = max(0.0, x_max - x_min)
    if span == 0:
        return 0.0, "scară indisponibilă"
    _, _, total_meters = Geod(ellps="WGS84").inv(
        x_min,
        latitude,
        x_max,
        latitude,
    )
    target_max = max(1.0, total_meters * 0.2)
    magnitude = 10 ** math.floor(math.log10(target_max))
    target = max(
        candidate * magnitude
        for candidate in (1, 2, 5)
        if candidate * magnitude <= target_max
    )
    width = span * target / total_meters
    label = f"{target / 1000:g} km" if target >= 1000 else f"{target:g} m"
    return width, label


def _plot_geometry(
    axis: Any,
    geometry: dict[str, Any] | None,
    color: str,
    width: float,
    alpha: float,
) -> None:
    if not geometry:
        return
    item = shape(geometry)
    polygons = [item] if item.geom_type == "Polygon" else list(getattr(item, "geoms", []))
    for polygon in polygons:
        if polygon.geom_type == "Polygon":
            x, y = polygon.exterior.xy
            axis.fill(x, y, facecolor=color, edgecolor=color, linewidth=width, alpha=alpha)


def _plot_osm_feature(
    axis: Any,
    geometry: dict[str, Any] | None,
    color: str,
    width: float,
    alpha: float,
) -> None:
    if not geometry:
        return
    item = shape(geometry)
    parts = list(getattr(item, "geoms", [item]))
    for part in parts:
        if part.geom_type == "Polygon":
            x, y = part.exterior.xy
            axis.fill(x, y, facecolor=color, edgecolor=color, linewidth=width, alpha=alpha)
        elif part.geom_type in {"LineString", "LinearRing"}:
            x, y = part.xy
            axis.plot(x, y, color=color, linewidth=width, alpha=alpha)
        elif part.geom_type == "Point":
            axis.scatter([part.x], [part.y], c=[color], s=28, marker="o", zorder=6)


def _chart_datasets(state: ImpactToolState) -> list[tuple[str, dict[str, float]]]:
    sar = (state.analysis_results.get("sar") or {}).get("metrics", {})
    dynamic = state.analysis_results.get("dynamic_world") or {}
    osm = (state.analysis_results.get("osm_impact") or {}).get("metrics", {})
    return [
        (
            "Suprafețe de apă (km²)",
            {
                "SAR": _metric_numeric_value(
                    sar.get("sar_new_water_area_km2")
                ) or 0.0,
                "Dynamic World": _dynamic_metric_value(
                    dynamic,
                    "dynamic_world_new_water_area_km2",
                ),
                "Suprapunere": _dynamic_metric_value(
                    dynamic,
                    "sar_dynamic_world_new_water_overlap_area_km2",
                ),
            },
        ),
        (
            "Tranziții Dynamic World către apă (km²)",
            dynamic.get("transition_values", dynamic.get("transitions", {})),
        ),
        (
            "Număr elemente OSM",
            {
                "Clădiri direct": float(osm.get("buildings_direct", 0)),
                "Clădiri buffer": float(osm.get("buildings_buffer", 0)),
                "Poduri direct": float(osm.get("bridges_direct", 0)),
                "Poduri buffer": float(osm.get("bridges_buffer", 0)),
                "Obiective direct": float(osm.get("critical_direct", 0)),
                "Obiective buffer": float(osm.get("critical_buffer", 0)),
            },
        ),
        (
            "Lungimi infrastructură liniară (km)",
            {
                "Drumuri direct": float(osm.get("roads_direct_km", 0)),
                "Drumuri buffer": float(osm.get("roads_buffer_km", 0)),
                "Căi ferate direct": float(osm.get("railways_direct_km", 0)),
                "Căi ferate buffer": float(osm.get("railways_buffer_km", 0)),
            },
        ),
        (
            "Suprafețe clădiri (m²)",
            {
                "Total analizat": float(osm.get("buildings_area_m2", 0)),
                "Suprapunere apă": float(osm.get("buildings_overlap_m2", 0)),
            },
        ),
    ]


def _bar_chart(title: str, values: dict[str, float]) -> BytesIO:
    labels = list(values) or ["Fără date"]
    numbers = [float(values[label]) for label in labels] if values else [0.0]
    figure, axis = plt.subplots(figsize=(8.5, 3.2))
    axis.bar(labels, numbers, color="#0ea5e9")
    axis.set_title(title)
    axis.tick_params(axis="x", rotation=22)
    axis.grid(axis="y", color="#e2e8f0", linewidth=0.6)
    output = BytesIO()
    figure.tight_layout()
    figure.savefig(output, format="png", dpi=130)
    plt.close(figure)
    output.seek(0)
    return output
