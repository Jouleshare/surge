# Surge transfer context

This file is the product and operating context for a standalone AMPD Surge deployment. It is intentionally independent of any Jarvis/OpenClaw workspace, memory, sessions, or personal configuration.

## What Surge is

Surge is AMPD Energy's temporary-power sales-engineering and evidence assistant. It turns rough site-power questions into a structured first-pass assessment:

- plant/load and quantity
- project duration and operating assumptions
- likely Ampd unit route
- generator baseline and recharge source
- indicative cost, fuel and CO2 comparison
- evidence basis, caveats and next data request

The Flask service in this repository is the deployable WhatsApp/web service. It calls the canonical Loadout calculation API and the Deploy manufacturer API; those services are external dependencies and are not copied into this repository.

## Evidence rules

Keep these layers separate in every answer and record:

1. measured field evidence
2. manufacturer/model data
3. customer-supplied scenario data
4. assumption-led screening

Never present an assumption as proof. Exact manufacturer/model matches are preferred for proposal-grade output. A credible nearby model can be used for a quick screen only when the substitution is disclosed. No answer is final engineering sign-off.

## Calculation rules

- Use Loadout as the calculation source of truth for sizing, rates and generator-displacement logic.
- An Ampd unit charges from one input source at a time: mains/grid OR diesel generator OR no charge. Never stack mains and generator charging in one schedule.
- Regional rates in `surge/surge_rates.json` are screening assumptions. Site, customer or partner rates override them.
- Electricity pricing is a screening default unless a site tariff is supplied.
- For marginal, safety-sensitive, unusual or customer/proposal-grade cases, escalate for AMPD technical review.

## Current supported workflow

The service parses natural-language requests for tower cranes, hoists, welfare/site loads and related temporary-power scenarios. It can handle quantity, kVA, duration, region, mains/generator recharge, manufacturer/model clues, follow-ups, job references, contact capture and admin views.

Useful test/demo prompt:

> We have two tower cranes at 160 kVA each on a 52-week project. Recharge is from a diesel generator. Can Ampd support this and what would you recommend?

The result is an indicative screening conversation, not a quotation or electrical design.

## Data ownership and deployment boundary

- `data/loadout_knowledge.json`: approved calculation/product assumptions used by the local screening layer.
- `data/manufacturers/`: copied manufacturer/model reference data for local matching and artifact generation.
- `surge/surge_rates.json`: regional commercial screening rates and source metadata.
- `/var/lib/surge/`: runtime leads, conversations, jobs and artifacts. These are operational records and must not be committed.
- Loadout and Deploy APIs remain separate services; Brand/AMPD must provide network access and any required future authentication.

## Human controls

The deployment owner must supply fresh Meta, Resend and admin credentials through `/etc/surge/surge.env` or an equivalent secret manager. Rotate any credential that has previously appeared in another environment. Keep the admin routes private behind HTTPS and a trusted access boundary.

Do not copy Jarvis `SOUL.md`, `MEMORY.md`, session history, OpenClaw configuration, personal contacts, local workspace files or customer databases into this deployment.
