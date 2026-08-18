# Surge Regional Rate Support

## Adding a new region

1. Add a top-level region block to `surge/surge_rates.json` using an ISO-style region code such as `AU`.
2. Include `currency`, `currency_code`, `fuel_price`, `fuel_price_display`, `electricity_rate`, and `electricity_rate_display`.
3. Add `bess_rates` and `gen_rates` only when credible region-specific or partner rates exist. Leave them empty rather than inventing quote-ready hire prices.
4. Add metadata notes under `_meta.region_notes.<REGION>` explaining whether assumptions are provisional, source-backed, or partner-supplied.
5. If a trustworthy public diesel source exists, add a region updater function in `surge/update_fuel_prices.py` and register it in `FUEL_UPDATERS`.
6. If no updater exists, the region can still be configured manually. The updater will report that no automatic updater is configured.

Diesel pricing is automatic where an updater is configured, subject to the 15% guardrail. The UK and US sources are official/public market data feeds. AU uses GlobalPetrolPrices as a third-party benchmark source, not an official government rate, and site/partner diesel prices override it.

Electricity pricing is not weekly-updated by Surge. Treat it as a screening default unless a site tariff, utility tariff, retailer contract, or customer-supplied rate is available. AU now records Canstar state/distributor electricity benchmarks for screening context, but Canstar is third-party consumer-market benchmark data, not a project/site tariff.

Surge prompts and customer output should require region-specific rates or ask for missing rates before presenting quote-level commercial comparisons.
