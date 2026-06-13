# Manual Test Checklist

- [ ] Fresh clone installs with Python 3.12.
- [ ] Application starts without `.env` and explains missing optional configuration.
- [ ] GEE status is correct after local authorization.
- [ ] County click and selector center the map.
- [ ] BEFORE/AFTER validation rejects incompatible pairs unless explicitly overridden.
- [ ] Only one comparison divider is visible.
- [ ] Comparator swap and close clean temporary layers.
- [ ] SAR completes without OSM or external API keys.
- [ ] Dynamic World runs independently.
- [ ] MapTiler context is optional and attributed.
- [ ] Geoapify facilities are clustered and have detailed popups.
- [ ] Targeted OSM reports partial results instead of crashing on category failure.
- [ ] Buffer change invalidates OSM impact/report only.
- [ ] Layer toggles control visible analytical layers.
- [ ] PDF downloads after SAR even when OSM is unavailable.
- [ ] PDF includes methodology, sources, limitations, warnings, and preliminary-result disclaimer.
- [ ] No secrets, cache, raster, archive, or generated output is tracked.
