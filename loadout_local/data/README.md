# Loadout data pack

This directory is the portable Loadout reference-data layer copied onto the AMPD VPS with the local API. It contains no customer records, authentication database, billing data or secrets.

- `loadout_knowledge.json`: curated assumptions and decision rules.
- `equipment_config.json`: equipment specs, demand factors and utilisation rates.
- `bess_units.json`: approved Ampd unit records exported from the Loadout shared data model.
- `generator_rates.json`: fallback screening hire/fuel data used by the local calculation API.
- `manufacturers/`: manufacturer/model reference data used for crane matching.

The local API exposes this data through `/api/jarvis/loadout-knowledge` and `/api/manufacturers`. Rates remain screening assumptions and must be updated through the AMPD-approved data governance process.
