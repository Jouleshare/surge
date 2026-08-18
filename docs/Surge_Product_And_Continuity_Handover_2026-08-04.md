# Surge Product And Continuity Handover

Prepared for: AMPD Energy  
Date: 2026-08-04  
Status: Working handover pack for AMPD product rollout

## 1. Executive Summary

Surge is AMPD's temporary-power intelligence assistant. It helps AMPD teams, regions, and approved partners turn early site-power questions into a structured first-pass answer:

- what plant or load is being powered
- whether an Ampd 200, Ampd 400, or other route is likely to fit
- what generator baseline is being displaced or reduced
- what recharge source is being assumed
- what the commercial, fuel, and CO2 impact might be
- what evidence supports the recommendation
- what still needs to be confirmed before a customer commitment

The important point: Surge is not just a chatbot. The product is the repeatable AMPD workflow around the chatbot: data capture, plant matching, evidence tagging, calculation, proposal output, and field-learning feedback.

Surge should be positioned as:

> A sales-engineering and evidence assistant for AMPD temporary-power assessment, recommendation, proposal generation, and live deployment learning.

It should not be positioned as:

> An unsupervised engineering sign-off tool, final quotation engine, or replacement for site electrical validation.

## 2. What Surge Is

Surge is a product layer that sits between messy customer/project information and AMPD's technical-commercial decision process.

It can receive a rough request such as:

> 2 tower cranes, 160 kVA each, 52-week project, generator recharge

and turn it into:

- a structured load scenario
- a generator baseline
- an AMPD option
- a recharge assumption
- indicative cost, fuel, and emissions comparison
- a short recommendation
- caveats and missing-data questions
- a customer-ready summary or proposal-style output

Surge currently exists across several working surfaces:

- WhatsApp-style chatbot flow for quick customer or sales enquiries
- Discord/internal AMPD working channels for region and partner support
- Loadout/Surge calculation logic for AMPD sizing and diesel comparison
- saved simulation artifacts for proposal-style outputs
- field evidence records for reusable learning
- customer portal prototypes, including the Northern Site style portal with Gantt view and embedded Surge chat

The rollout opportunity is to productise this into a clean AMPD-owned system with a dedicated server, central evidence database, controlled regional/partner workspaces, and a clear owner model.

## 3. How Surge Works

### 3.1 Input

Surge starts with a user request. Inputs can be rough or structured.

Typical inputs:

- plant type, for example tower crane, hoist, welfare, MRI, site kitchen, chargers, general site load
- quantity
- generator kVA or known kW demand
- manufacturer and model, for example WOLFF, Potain, Liebherr, Falcon
- project duration
- operating hours
- charge source: mains/grid, generator, or no charge window
- region or partner context
- commercial assumptions such as diesel price, weekly hire rates, or partner price book

If the request is incomplete, Surge can still give a first-pass screen using explicit assumptions, then ask for the missing data.

### 3.2 Parsing And Matching

Surge turns the message into structured inputs:

- equipment category
- quantity
- duration
- generator/mains recharge source
- region
- manufacturer/model match where available
- known or assumed kVA/kW allowance

Customer/user-supplied plant names are treated as leads to verify, not as gospel. For proposal-grade sizing, Surge must confirm the exact make/model/variant against a manufacturer spec sheet online or the manufacturer database before stating a firm AMPD unit count. If only a nearby model, generic category, or customer-described load is available, the answer must be labelled as unverified screening.

Lookup order should remain:

1. exact known plant, model, or spec-sheet data
2. manufacturer database
3. scenario-supplied load data
4. Loadout generator-kVA crane logic
5. generic fallback only when no better data exists

### 3.3 Evidence Layer

Surge must keep evidence layers separate:

1. measured field evidence
2. manufacturer/model data
3. customer-supplied scenario data
4. assumption-led screening

This is critical. Assumption-led screening is useful, but it is not proof.
Scenario-supplied plant names and loads are also not proof until tied back to an exact spec sheet, drawing, database record, or measured profile.

Recommended evidence fields:

- evidence ID
- region
- customer/site type
- plant or load type
- manufacturer/model
- measured_or_assumed
- source file/link
- approved_for_internal_use
- approved_for_customer_use
- approved_by
- approval_date
- restrictions
- approved customer wording

New field evidence should start as internal-only until AMPD approves the technical validity and external wording.

### 3.4 Calculation

Surge uses AMPD sizing and generator-displacement logic to calculate a first-pass comparison.

Core calculation areas:

- peak load screen
- average load screen
- AMPD unit recommendation
- generator baseline
- recharge mode
- diesel usage
- runtime reduction
- cost comparison
- CO2/fuel impact
- operational caveats

Hard rule:

> An AMPD unit can charge from one input source at a time only: mains/grid OR diesel generator OR no charge. Do not stack mains plus generator charging in the same period.

### 3.5 Recommendation

Surge should give the recommendation first, then show the assumptions.

Good output shape:

1. recommendation
2. why that route fits
3. key assumptions
4. evidence basis
5. caveats
6. one useful missing-data question
7. customer-ready wording if needed

Surge should avoid burying the user in engineering detail unless the user asks for it or the output is being used commercially.

### 3.6 Output

Surge can produce:

- quick chat answer
- sales qualification note
- customer email draft
- commercial comparison
- proposal-style summary
- PDF/visual artifact
- saved job reference
- portal handoff note
- partner request summary
- evidence feedback note

Customer-facing output should always label the basis clearly:

- "measured field evidence"
- "manufacturer data"
- "customer-supplied assumption"
- "first-pass screening assumption"

## 4. Current Product Architecture

Current working architecture:

- Surge app: Flask-based chatbot/service layer
- Loadout API: canonical calculation logic and AMPD product constraints
- Deploy/manufacturer API: manufacturer crane/spec lookup
- evidence files: saved field cases and simulation artifacts
- Discord/OpenClaw route: AMPD internal and regional working spaces
- WhatsApp/Twilio or Meta route: external chat interface
- Resend/email route: lead notification or follow-up support
- AMPD Mobilise prototype: partner/customer portal with Gantt, fleet/request view, and Surge chat integration
- DigitalOcean/VPS hosting route: current deployable infrastructure pattern

Product direction:

- move AMPD production data to a dedicated AMPD-controlled server
- keep one central Surge database
- tag data by region, partner, customer, and evidence status
- give each region or partner a scoped workspace
- preserve one global intelligence layer underneath

Principle:

> Surge should be global in knowledge, regional in assumptions, and explicit in evidence provenance.

## 5. AMPD Rollout Model

### Phase 1 - Controlled Internal Rollout

Use Surge internally for AMPD teams first.

Scope:

- AMPD UK
- AMPD Australia
- AMPD USA or other regions as approved
- internal sales/application support
- Brandon/Tom/engineering-supported evidence review

Aim:

- prove repeat usage
- find common request types
- build field evidence
- tune regional assumptions
- create approved wording

### Phase 2 - Partner Workspaces

Give selected partners a controlled workspace, not full AMPD internal access.

Partner workspace should include:

- partner projects
- partner-visible fleet or request data
- partner-specific price book
- scoped Surge chat
- saved assessments
- customer-safe proposal outputs

Partner should not see:

- AMPD internal margins
- other customer or partner records
- unapproved evidence
- internal approval discussions
- private regional assumptions outside their scope

### Phase 3 - Customer Portal

Surge can support customer-facing portals like the Northern Site demo.

Useful portal modules:

- project overview
- Gantt/programme view
- deployed units
- live or recent telemetry
- request/availability workflow
- Surge chat or guided assumption check
- proposal/download area
- support contacts and escalation route

This should be treated as a productised customer/partner control room, not just a demo page.

## 6. What Brandon Owns

Brandon should be framed as a technical knowledge and assumption-support owner, not the only person who can keep Surge alive.

Likely Brandon responsibilities:

- technical sense-check of AMPD assumptions
- approved wording for AMPD product capability
- escalation on edge cases
- product fit feedback
- region/product sign-off where required
- guidance on what can be customer-facing

Brandon should not be the sole operational dependency.

Continuity requirement:

- document the assumptions Brandon approves
- convert repeated answers into structured rules
- store approved wording in the Surge knowledge base
- make approval history visible
- appoint at least one AMPD backup approver

## 7. What Tom Owns

Tom has been carrying much of the sales-engineering workflow, practical site interpretation, product shaping, and customer language.

Likely Tom responsibilities:

- translating real site/customer problems into Surge workflows
- identifying useful commercial narratives
- finding gaps between sales needs and technical data
- capturing field evidence from live AMPD use cases
- building customer/partner portal concepts
- testing whether Surge outputs are useful in the real sales process

Tom should not be the sole product memory.

Continuity requirement:

- capture Tom's rules of thumb as structured assumptions
- save field cases with evidence status
- keep reusable customer wording in templates
- document regional and partner price books
- train at least one AMPD product owner and one technical owner on the workflow

## 8. Continuity Plan If Tom Or Brandon Is Unavailable

### 8.1 Minimum People Needed

Surge needs four named roles:

- Product owner: owns roadmap, use cases, rollout decisions
- Technical approver: validates AMPD technical assumptions and evidence
- Data/evidence owner: maintains plant data, field cases, price books, and evidence status
- Platform owner: maintains hosting, integrations, monitoring, and backups

The same person can hold more than one role during early rollout, but each role needs a named backup.

### 8.2 Critical Knowledge To Preserve

Store these in AMPD-controlled systems:

- AMPD 200 and AMPD 400 product constraints
- current charge-rate assumptions
- generator baseline assumptions
- region-specific fuel and generator hire rates
- partner-specific price books
- approved customer wording
- manufacturer/model database
- field evidence cases
- known caveats and exclusions
- lead-routing process
- support/escalation contacts
- deployment instructions
- backup/restore procedure

### 8.3 First 24 Hours Continuity Checklist

If Tom or Brandon becomes unavailable:

1. Confirm Surge is still online.
2. Check recent conversations and open customer/partner requests.
3. Pause customer-facing automation if there is uncertainty around output quality.
4. Keep internal assistant mode running for AMPD staff.
5. Assign a temporary product owner.
6. Assign a temporary technical approver.
7. Review any pending evidence or new assumptions before reuse.
8. Confirm lead notifications are reaching the right AMPD mailbox or CRM route.
9. Check the server, domain, SSL, webhook, and logs.
10. Tell users what Surge can still safely do: first-pass screening, assumption capture, and draft outputs.

### 8.4 First 7 Days Continuity Checklist

1. Export all recent Surge conversations and saved jobs.
2. Review open jobs by region/partner/customer.
3. Validate the current rate book.
4. Validate AMPD product constraints against the latest approved data.
5. Review field evidence records and approval status.
6. Reconfirm customer-facing disclaimers.
7. Make sure backups are running and restorable.
8. Create a rota for technical review.
9. Decide whether to keep external WhatsApp live or limit Surge to internal use temporarily.
10. Capture every continuity decision in the handover log.

### 8.5 Safe Degraded Mode

If technical confidence is low, Surge should operate in safe degraded mode:

- internal AMPD users only
- no final customer claims
- no named field evidence unless already approved
- no binding pricing
- no final engineering recommendation
- clear "first-pass screen" language
- one missing-data question per answer
- drafts only for customer communication

Safe degraded-mode wording:

> Surge can provide a first-pass AMPD screening view from the information provided. Final sizing, commercial quote, connection design, and customer-facing evidence must be approved by AMPD before issue.

## 9. Data And Evidence Governance

Surge becomes valuable when AMPD feeds it real cases.

Every new case should be saved as one of:

- assumption-led screen
- customer-supplied scenario
- manufacturer/spec record
- measured field case
- approved customer proof point

Promotion path:

1. Capture raw case.
2. Tag the source and confidence.
3. Technical owner validates.
4. Commercial owner approves external wording.
5. Data owner promotes it into reusable evidence.
6. Surge can cite it using only the approved wording.

Do not let live field data overwrite manufacturer/spec truth. They are separate evidence layers.

## 10. Cost And Model Strategy

Surge should be cost-effective by design.

Recommended model approach:

- use cheaper/fast models for parsing, classification, extraction, and simple drafting
- use stronger reasoning models only for complex assessment, proposal generation, or edge cases
- keep calculation deterministic where possible
- cache manufacturer/spec lookups
- store structured assumptions so repeated answers do not burn tokens repeatedly
- avoid sending whole evidence libraries into every request

Practical model routing:

- extraction/classification: low-cost model
- normal sales answer: mid-cost model
- complex multi-load/project reasoning: stronger model
- final customer proposal: stronger model plus human review
- evidence promotion: human-approved workflow, not model-only

## 11. Security And Access

Do not store credentials in this document.

Production handover should record:

- where the server lives
- who has admin access
- where secrets are stored
- how to rotate API keys
- how to disable external channels
- how to restore from backup
- who receives lead notifications
- which channels are approved for AMPD, region, partner, and customer use

Access rules:

- AMPD admin can see all AMPD-owned workspaces.
- Regional teams see their own region and approved global evidence.
- Partners see only their workspace, price book, projects, and approved outputs.
- Customers see only their project portal and approved published information.

## 12. Risks And Guardrails

Main risks:

- assumption-led output presented as proven
- unapproved field evidence used customer-facing
- region data used without provenance
- partner price books leaking across customers
- Surge becoming dependent on Tom or Brandon's memory
- external chatbot giving overly certain answers
- product scope expanding before the evidence database is controlled

Guardrails:

- evidence labels mandatory
- customer-facing proof requires approval
- one central database
- scoped regional/partner workspaces
- rate books versioned
- model outputs reviewed for proposals
- safe degraded mode available
- every material customer output should include assumptions and caveats

## 13. Recommended Next Build Items

1. AMPD dedicated server and production repo separation.
2. Central Postgres database for projects, jobs, evidence, rates, and approved wording.
3. Admin UI for evidence approval.
4. Region and partner workspace permissions.
5. Standard Surge prompt templates by use case.
6. Customer proposal generator with evidence labels.
7. Customer/partner portal template with Gantt and Surge request flow.
8. Backup, monitoring, and incident runbook.
9. Model-routing layer for cost control.
10. Handover session with Tom, Brandon, AMPD product owner, technical approver, and platform owner.

## 14. The Simple Version For AMPD

Surge helps AMPD answer this faster:

> Can this site use AMPD instead of running diesel, what unit would we recommend, what assumptions are we making, what evidence supports it, and what do we need to confirm next?

The product is not only the answer. The product is the repeatable system that makes AMPD's site-power knowledge reusable across regions, partners, proposals, and live deployments.
