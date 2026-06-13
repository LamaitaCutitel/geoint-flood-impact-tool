from __future__ import annotations

from src.impact_tool.sar_qa import (
    run_sar_threshold_sweep,
    sar_qa_chart_data,
    sar_qa_layer_definitions,
)


def _scene(scene_id: str, polarization: str = "VH") -> dict:
    return {
        "ee_id": scene_id,
        "polarization": polarization,
        "acquisition_time": "2024-09-01T00:00:00Z",
    }


def test_threshold_sweep_produces_values_status_and_final_threshold(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "src.impact_tool.sar_qa.selected_scene_image",
        lambda ee, scene, aoi, smoothing_radius=0: object(),
    )
    monkeypatch.setattr(
        "src.impact_tool.sar_qa.sar_water_mask",
        lambda image, threshold, aoi, connected: threshold,
    )
    monkeypatch.setattr(
        "src.impact_tool.sar_qa.sar_water_change_masks",
        lambda before, after, aoi: {
            "sar_new_water": after,
            "sar_persistent_water": before,
            "sar_water_loss": after,
        },
    )
    monkeypatch.setattr(
        "src.impact_tool.sar_qa._metric_statuses",
        lambda ee, masks, aoi, scale: {
            "sar_water_before_area_km2": {
                "status": "reușit",
                "value": abs(float(masks["sar_water_before"])),
                "error": None,
            },
            "sar_water_after_area_km2": {
                "status": "reușit",
                "value": abs(float(masks["sar_water_after"])) + 1,
                "error": None,
            },
            "sar_new_water_area_km2": {
                "status": "reușit",
                "value": abs(float(masks["sar_new_water"])),
                "error": None,
            },
        },
    )
    monkeypatch.setattr(
        "src.impact_tool.sar_qa._qa_layers",
        lambda *args, **kwargs: {
            "qa_persistent_water": {
                "status": "reușit",
                "url": "https://tiles/persistent",
                "error": None,
            }
        },
    )

    result = run_sar_threshold_sweep(
        object(),
        object(),
        _scene("before"),
        _scene("after"),
        final_threshold=-18,
    )

    assert result["status"] == "reușit"
    assert len(result["rows"]) == 5
    assert all(row["new_water_km2"] is not None for row in result["rows"])
    assert result["final_threshold_db"] == -18
    assert result["balanced_threshold_db"] == -18


def test_qa_chart_is_absent_without_successful_values() -> None:
    assert sar_qa_chart_data({"rows": []}) == {}
    assert sar_qa_chart_data(
        {
            "rows": [
                {
                    "threshold_db": -18,
                    "status": "eroare",
                    "new_water_km2": None,
                }
            ]
        }
    ) == {}


def test_qa_layers_are_hidden_by_default() -> None:
    definitions = sar_qa_layer_definitions(
        {
            "layers": {
                "qa_persistent_water": {
                    "status": "reușit",
                    "url": "https://tiles/persistent",
                    "error": None,
                },
                "qa_water_loss": {
                    "status": "reușit",
                    "url": "https://tiles/loss",
                    "error": None,
                },
            }
        }
    )

    assert definitions
    assert all(layer["shown"] is False for layer in definitions)
