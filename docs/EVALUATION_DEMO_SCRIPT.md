# Evaluation Demo Script

1. Start the application with `scripts/start_app.ps1`.
2. Select Galați and confirm that the county outline is centered.
3. Search Sentinel-1 scenes for the event period.
4. Select compatible BEFORE and AFTER scenes.
5. Activate the scene comparator, drag the divider, then close it.
6. Confirm the pair and run `Rulează analiza SAR`.
7. Inspect `Apa nouă evidențiată prin SAR` and record SAR/vectorization timings.
8. Run Dynamic World separately and inspect the observed differences.
9. Enable the optional MapTiler county context when configured.
10. Load important facilities.
11. Run targeted OSM impact and record source, completeness, and duration.
12. Change the warning buffer and recalculate OSM impact.
13. Confirm from timings that SAR/GEE did not rerun.
14. Activate a thematic comparison preset, swap left/right, and close it.
15. Generate the PDF and verify sources, warnings, metrics, and disclaimer.
16. Save screenshots and timing observations outside the repository.
