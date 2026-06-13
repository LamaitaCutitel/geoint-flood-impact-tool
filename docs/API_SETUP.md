# API Setup

Copy `.env.example` to `.env` and configure only the services you use.

```text
GEE_PROJECT_ID=
MAPTILER_API_KEY=
GEOAPIFY_API_KEY=
OVERPASS_ENDPOINT=https://overpass-api.de/api/interpreter
OVERPASS_FALLBACK_ENDPOINTS=https://overpass.kumi.systems/api/interpreter,https://overpass.osm.ch/api/interpreter
EXTERNAL_API_TIMEOUT_SECONDS=25
```

`GEE_PROJECT_ID` is required for Earth Engine analysis. MapTiler and Geoapify are optional. Overpass endpoints have public-service availability and rate limits.

Never commit `.env`, credentials, tokens, service-account files, or local Earth Engine authorization data.
