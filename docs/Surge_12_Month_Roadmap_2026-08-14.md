# Surge 12 Month Roadmap

Prepared for: Tom Carter / AMPD Energy  
Date: 2026-08-14  
Status: Working product roadmap

## 1. North Star

Surge should become AMPD's central temporary-power intelligence layer.

It should not just be a chatbot or a document search tool. The stronger product is one Surge brain with several safe front doors:

- internal AMPD team use
- partner/customer portal use
- AMPD app/company portal integration
- service and troubleshooting support
- WhatsApp/email notification and escalation routes

The principle remains:

> Many front doors, one Surge brain.

Surge should improve as AMPD uses it. Every validated field case, resolved support issue, corrected assumption, accepted proposal, and engineer-approved answer should make the system sharper.

## 2. Current Version - Now

Surge currently exists as a working sales-engineering and evidence assistant.

Current strengths:

- quick AMPD sizing and commercial screening
- Loadout-style generator displacement logic
- plant/model matching and assumption-led scenario handling
- saved field evidence records
- proposal-style answer generation
- internal Discord/WhatsApp-style interaction
- AMPD/Mobilise portal prototypes with project, Gantt, unit, and Surge-chat concepts

Current product rule:

- answer simple viability questions quickly
- verify the assumed make/model in the wording
- use instantly available field evidence when present
- use spec/database evidence where available
- deep dive only when the fit is marginal, risk is material, or the answer is customer/proposal-facing

Example target pattern:

> Quick screen: yes - assuming you mean the Wolffkran 166B, it should be workable on an Ampd 200 for normal crane operation. This is based on the AMPD/spec envelope and field evidence from similar tower crane duty cycles running successfully on Ampd 200-class setups. I would only deep dive if recharge access is limited, the crane is sharing supply with other large loads, or the duty cycle is unusually heavy.

## 3. 0-3 Months - Make Surge Reliable And Useful

Goal: make Surge a dependable AMPD commercial/sizing assistant before adding wider product complexity.

Priority outcomes:

- fast quick-screen answers for common plant-fit questions
- cleaner evidence labels: field evidence, spec/database, customer-supplied, assumption-led
- stronger plant verification flow without blocking every answer
- central manufacturer/spec database as the source of truth
- central field-evidence layer kept separate from spec truth
- repeatable proposal and customer-summary formats
- feedback capture on good/bad answers

Core work:

- tighten prompt/answer patterns
- create a small approved-answer library for common scenarios
- standardise "quick screen" vs "proposal-grade" behaviour
- keep model/spec fallback behaviour practical: use credible alternatives and disclose material gaps
- prevent over-engineered 20-minute answers for simple questions

Success measure:

- AMPD users trust Surge for first-pass sizing and commercial guidance.
- Surge is fast enough to use in real conversations.
- Tom/AMPD can see why the answer was given without reading an engineering essay.

## 4. 3-6 Months - AMPD Branded Portal And Partner Workflow

Goal: move Surge out of workshop channels and into a clean AMPD access layer.

Priority outcomes:

- AMPD-branded web portal using the existing Surge/Mobilise portal pattern
- customer/partner/project login or magic link
- scoped unit/project context
- partner-visible fleet and hire timeline
- saved assessments and requests
- "Ask Surge" chat inside the portal
- escalation button for AMPD review

Portal boundary:

- customers/partners see only their own project, units, documents, health status, and approved answers
- AMPD internal fleet position, raw Jira incidents, unresolved engineering notes, and internal evidence stay hidden

Success measure:

- one or two friendly pilot partners can use Surge through a portal instead of Discord.
- Surge can answer commercial and unit/project questions using scoped context.
- AMPD avoids creating a third system of record; the portal remains an access layer over Surge.

## 5. 6-9 Months - Company Portal / App Integration

Goal: integrate Surge into AMPD's normal digital environment.

Likely route:

- keep the central Surge backend
- expose Surge via an embeddable web component or webview
- pass AMPD app/company portal context into Surge
- preserve the same evidence, calculation, and answer rules

Required context from AMPD systems:

- user identity and role
- customer/account
- project/site
- visible AMPD units
- unit model and status
- permitted telemetry/document fields
- whether user can request proposal, raise support, or view only

Success measure:

- Surge appears inside the AMPD portal/app without becoming a separate app-store product.
- customers and AMPD users do not have to repeat basic context.
- every conversation is scoped to what the user is allowed to see.

## 6. 9-12 Months - Service, Troubleshooting, And Fleet Intelligence

Goal: expand Surge from commercial sizing into live operational support.

Priority outcomes:

- unit health cards in the portal
- troubleshooting chat based on known fixes, incidents, and approved learnings
- partner/customer-visible alerts for meaningful issues
- WhatsApp/email notification routes
- cheap scheduled unit-health scans
- exception summaries for AMPD service teams

Recommended architecture:

1. Rules and scripts scan unit data cheaply.
2. Cheap model reviews exceptions only.
3. Stronger Surge model handles ambiguous, commercial, safety, or customer-facing questions.

Example checks:

- low SOC or charge-window risk
- stale telemetry
- pack missing / abnormal pack voltage
- charger fault pattern
- repeated warning pattern
- unit offline before critical project period
- support incident matching known fix history

Notification rule:

- notify only when there is a real action, risk, or useful customer/service update
- avoid spamming normal noise
- route urgent/customer-facing alerts differently from internal AMPD service alerts

Success measure:

- Surge can explain what is happening with a unit in plain English.
- partners/customers get useful confidence and actions.
- AMPD service gets earlier exception visibility without paying an expensive model to read every normal datapoint.

## 7. Data And API Roadmap

Surge will need sanctioned AMPD data access. Do not scrape around the UI.

Likely API/data sources:

- manufacturer/spec database
- field evidence store
- Loadout/Surge calculation database
- AMPD app/company portal context
- Enernet/unit telemetry where approved
- battery health data
- asset/EJT or order lifecycle data
- Jira incidents and resolved learnings
- proposal outcomes and engineer feedback
- customer/partner permissions

Minimum API ask:

- service account or token-based API route
- documented endpoints
- role/permission model
- rate limits
- audit logging
- clear list of customer-safe fields
- clear list of internal-only fields

## 8. Governance

Surge should remain helpful without overclaiming.

Rules:

- separate field evidence, spec data, customer-supplied data, and assumptions
- never present assumption-led screening as proof
- verify plant models where possible before proposal-grade output
- use credible nearby alternatives instead of blocking when exact matches are missing
- disclose material gaps only when they affect the recommendation
- avoid nitpicking immaterial differences
- no final engineering sign-off without AMPD approval
- no customer access to internal fleet or unresolved engineering notes

## 9. What Help We Need From Tom / AMPD

From Tom:

- confirm the priority use cases for the first AMPD pilot
- provide the real questions AMPD users ask most often
- nominate one or two friendly pilot partners/customers
- decide which outputs need to be customer-ready versus internal-only
- keep challenging bad answer behaviour early, especially if Surge is too slow, too cautious, or overconfident

From AMPD product/tech:

- confirm whether the existing AMPD portal/app can embed Surge
- provide approved authentication route or service account model
- document available internal APIs
- define user roles and permissions
- define what telemetry can be shown to customers
- provide API access to unit, battery, incident, and asset data when ready

From AMPD service/engineering:

- approve known troubleshooting fixes
- label which incident learnings are customer-safe
- identify high-value fault patterns
- confirm escalation paths and notification thresholds

From AMPD commercial:

- approve proposal wording
- approve partner/customer evidence language
- confirm regional assumptions and price-book handling
- define when a quick screen is acceptable versus when proposal-grade review is required

## 10. Suggested 12 Month Milestones

### Month 1

- lock quick-screen and proposal-grade answer behaviour
- clean up evidence hierarchy
- capture common plant-fit questions
- build feedback loop for corrected answers

### Month 2

- improve manufacturer/spec matching
- expand field-evidence library
- standardise saved assessment format
- run internal AMPD pilot with real questions

### Month 3

- package Surge as a reliable internal AMPD assistant
- agree portal/app integration approach
- define API and permission requirements

### Months 4-5

- launch AMPD-branded web portal pilot
- add scoped customer/project/unit context
- add saved assessments and escalation queue

### Month 6

- pilot with one or two partners/customers
- review what customers ask and what AMPD has to correct
- decide whether to proceed to app/company portal embedding

### Months 7-8

- embed Surge into AMPD portal/app or prepare embeddable component
- add API-backed context packs
- improve admin/evidence approval workflow

### Month 9

- add first service/troubleshooting use cases
- connect approved incident learnings
- add unit-health summary cards for partner-visible units

### Months 10-11

- add hourly/regular fleet exception scan
- route exceptions to AMPD service
- add WhatsApp/email alerts for meaningful customer/service events

### Month 12

- review adoption, answer quality, commercial impact, service impact, and cost
- decide whether Surge becomes a formal AMPD platform layer across sales, customer portal, and service operations

## 11. The Simple Story

Now:

> Surge helps AMPD answer power-sizing questions faster and with better evidence.

Next:

> Surge becomes the AMPD-branded portal assistant for customers, partners, and projects.

Later:

> Surge becomes the intelligence layer across commercial sizing, live unit health, troubleshooting, service alerts, and fleet learning.

The aim is not to build lots of separate tools.

The aim is:

> One Surge brain, connected to the right AMPD data, exposed through the right front door for each user.
