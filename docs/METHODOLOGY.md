# Methodology

The application identifies preliminary new water observed through Sentinel-1 SAR
using a strict BEFORE / AFTER comparison. JRC and DEM are not used.

The principal result is derived by comparing water-compatible radar observations in a selected AFTER scene against the selected BEFORE scene. Processing is clipped to the exact active county or AOI geometry.

Dynamic World is an optional corroborating source. Its differences are presented separately and do not replace the SAR result.

Use cautious interpretation: the output is `apa observata automat prin SAR`, an `extindere preliminara`, and a preliminary GEOINT decision-support product. It is not a field-confirmed flood map.
