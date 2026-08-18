# Surge End User Access Layer Options

Prepared for: AMPD Energy  
Date: 2026-08-04  
Status: Working product note

## 1. Recommendation

Do not make Discord the end-user interface for Surge.

Discord can remain useful as an internal AMPD control/review channel, but most customers, site teams, and rental partners will not naturally use it. End users need AMPD-branded access through a normal product surface.

Recommended direction:

> Build a Surge access layer that can be embedded into the existing AMPD app and also used as a lightweight web portal. Keep the information-gathering workflow the same underneath.

Avoid building another App Store app. AMPD already has its own app and Enernet already exists as a separate operational/telemetry surface. A third standalone mobile app would create product sprawl, release-management overhead, duplicated login flows, and customer confusion.

The better route is:

- AMPD-branded web portal first
- progressive web app behaviour if needed
- magic-link or single sign-on access
- QR/link access from unit/project documents
- later embed the same portal inside the existing AMPD app as a webview or native tab

This gives AMPD two routes:

- Existing AMPD app: best for customers who already have AMPD units and app access.
- Web portal: best for partners, prospects, temporary project users, or customers who do not want another app flow.

## 2. What We Must Preserve

The access layer should not change the core Surge workflow. It should make the workflow easier to use.

Keep:

- the same information gathering
- the same evidence hierarchy
- the same calculation/sizing logic
- the same source-of-truth data
- the same approval rules for customer-facing claims
- the same escalation route for unknown assumptions

Change:

- the user interface
- the login/access method
- the way users select their units/projects
- the way Surge scopes answers to what the user is allowed to see

## 3. The Product Concept

Create a customer-facing layer called something like:

- Ask Surge
- Surge Assistant
- AMPD Power Assistant
- Unit Advisor

The user should be able to ask:

- What can my AMPD unit support?
- Is my current setup suitable for this load?
- What happens if I add a hoist or crane?
- Why did the battery discharge overnight?
- Can I reduce generator runtime?
- What information do you need to assess this site?
- Can you produce a quick customer/project summary?

Surge should answer based only on:

- the units they own or are assigned to
- their project/site data
- approved AMPD product data
- approved or internal-only evidence depending on user permission
- the assumptions they provide in the conversation

## 4. Best Access Options

### Option A - Embed Surge In The Existing AMPD App

Best long-term option if AMPD already has an app in customer use.

How it would work:

- Add an "Ask Surge" button or tab inside the AMPD app.
- User logs into the AMPD app as normal.
- Surge receives a scoped context pack from the app:
  - customer/account
  - site/project
  - assigned AMPD units
  - unit model
  - live/recent telemetry if available
  - allowed documents
  - regional settings
  - customer permissions
- User can ask questions about their own units and projects.
- Surge writes back a saved conversation, recommendation, or support/request record.

Pros:

- Strongest AMPD product experience.
- No new login habit for existing AMPD app users.
- Naturally scopes Surge to units the customer owns or has hired.
- Easier to control customer permissions.
- Fits AMPD's existing product ecosystem.

Cons:

- Needs AMPD app team involvement.
- Slower if the app release cycle is controlled or busy.
- Requires API design between app and Surge.

Verdict:

> Best strategic route. This should be the target product direction.

### Option B - AMPD-Branded Web Portal

Best near-term route while app integration is planned.

How it would work:

- Customer receives a secure AMPD link.
- They log in or use a magic link.
- Portal shows only their projects and AMPD units.
- Surge chat sits inside the portal.
- The portal can include Gantt/programme, project assumptions, documents, support contacts, and unit history.

This is similar to the Northern Site customer portal direction.

Pros:

- Faster to build than app integration.
- Works for partners and prospects, not only app users.
- Easy to demo.
- Can be AMPD-branded and region-specific.
- Useful for customer portals, rental partners, and project handover packs.

Cons:

- Another place for customers to go unless linked from the app/email/QR.
- Needs login/security/tenant isolation.
- Could become fragmented if not tied to the same Surge backend.

Verdict:

> Best first build. Use it to prove the workflow, then embed the same layer into the AMPD app.

### Option C - WhatsApp / Teams / Email Front Door

Useful for lightweight intake, not the main customer product.

How it would work:

- User messages Surge via WhatsApp, Teams, or email.
- Surge asks for missing data and creates a structured assessment.
- If the request needs customer-specific unit data, Surge sends a secure portal/app link.

Pros:

- Low friction.
- Good for first contact and sales qualification.
- Keeps information gathering natural.

Cons:

- Harder to control customer-specific access.
- Poorer for visual information like Gantt, telemetry, documents, unit selection.
- Higher risk of users asking about units they should not see.

Verdict:

> Keep as an intake layer, not the primary end-user portal.

### Option D - Keep Discord Only For Internal AMPD

Discord should move to internal use only.

Good use cases:

- AMPD team review
- Brandon/Raymond technical comments
- regional internal channels
- evidence approval discussion
- escalation on assumptions
- admin/control room for early rollout

Bad use cases:

- normal end customers
- site teams with no Discord habit
- customer-specific unit access
- customer-facing support records

Verdict:

> Discord is an internal workshop, not the shopfront.

## 5. Recommended Architecture

Use one central Surge backend with multiple front ends.

Suggested layers:

1. Surge Core
   - parser
   - calculation/sizing logic
   - evidence rules
   - model routing
   - recommendation generator

2. Customer Context API
   - who is the user?
   - what account/customer are they linked to?
   - what sites/projects can they see?
   - what AMPD units can they see?
   - what telemetry/documents are allowed?

3. Access Layer
   - existing AMPD app embed
   - AMPD web portal
   - partner portal
   - WhatsApp/intake route

4. Admin Layer
   - evidence approval
   - assumption library
   - partner price books
   - region defaults
   - support/escalation queue

Principle:

> Many front doors, one Surge brain.

## 6. Unit-Scoped Conversations

Yes, we can create a layer that lets end users talk about their own units.

The key is to give Surge a safe context pack before the conversation starts.

Example context pack:

```json
{
  "user": {
    "role": "customer_user",
    "company": "Example Contractor"
  },
  "site": {
    "name": "Project A",
    "region": "UK"
  },
  "visible_units": [
    {
      "model": "Ampd 200",
      "asset_label": "Unit 1",
      "status": "on hire",
      "telemetry_allowed": true
    }
  ],
  "permissions": {
    "can_view_internal_evidence": false,
    "can_request_proposal": true,
    "can_raise_support_ticket": true
  }
}
```

Surge can then answer:

- "Your Ampd 200 is suitable for this type of load if the peak and recharge assumptions are confirmed."
- "I can assess this, but I need the crane model or existing generator size."
- "Your current question needs AMPD technical review because it affects connection design."

Surge should not answer:

- questions about other customers
- internal pricing/margins
- unapproved evidence
- final engineering sign-off
- anything outside the user's unit/project permissions

## 7. Information Gathering Flow

Keep the intake flow simple.

Surge should collect:

1. What are you trying to power?
2. How many items?
3. Do you know kVA/kW or model?
4. How long is the project?
5. What is the charge source: mains, generator, or no charge?
6. What is the operating pattern?
7. Is this for a quick screen, proposal, support question, or live optimisation?

For app/portal users, pre-fill:

- customer
- site
- region
- AMPD unit model
- known telemetry
- project dates if available

This keeps the information gathering as-is, but removes duplicated typing.

## 8. MVP Build Path

### MVP 1 - Web Portal Wrapper

Build a simple AMPD-branded portal:

- login or magic link
- customer/project selection
- unit list
- "Ask Surge" chat
- saved assessments
- escalation button
- disclaimer and evidence labels

Use the existing Northern Site/Gantt work as the pattern.

Indicative build time:

- prototype: 3-5 working days if using the current Surge/Mobilise portal patterns
- usable pilot: 1-2 weeks for a secure branded portal with login/magic link, project/unit context, and Surge chat
- polished AMPD pilot: 3-4 weeks with saved assessments, admin review, basic support/escalation, documents, and Gantt/project view
- production-grade rollout: 6-10 weeks depending on AMPD app/API access, SSO requirements, telemetry permissions, security review, and evidence-approval workflow

The first build should be deliberately narrow:

- one or two pilot customers/partners
- assigned units only
- one region
- first-pass assessment and support questions
- no uncontrolled customer-facing evidence
- no final engineering sign-off

This avoids creating a third "system of record". The portal should be an access layer over Surge, not a replacement for Enernet or the AMPD app.

### MVP 2 - App Embed

Once the web portal workflow is proven:

- expose the same Surge chat as an embeddable webview/component
- pass user/project/unit context from the AMPD app
- keep all logic in the central Surge backend

### MVP 3 - Customer/Partner Workspaces

Add:

- partner-specific price books
- fleet/request view
- project Gantt/programme view
- support tickets
- proposal outputs
- evidence approval workflow

## 9. What To Tell Brandon/Anthony

Suggested wording:

> If Discord is not natural for AMPD users, we should not make it the front end. Keep Discord as an internal review channel if useful, but put Surge behind AMPD-branded access: first a web portal, then embedded into the existing AMPD app. The important thing is that the Surge brain stays the same. We preserve the information-gathering workflow and evidence rules, but give end users a cleaner way to talk about the units and projects they are actually allowed to see.

Short version:

> Discord was a useful workshop. The product should be an AMPD app/web access layer over the same Surge engine.

## 10. Decision Needed

Ask AMPD:

1. Can Surge be embedded in the existing AMPD app as a webview or native module?
2. Can the AMPD app provide user, customer, site, and unit context to Surge?
3. Who owns app-side development?
4. Should the first customer-facing version be a web portal while app integration is planned?
5. What user roles exist today in the AMPD app?
6. What unit/telemetry data can be safely exposed to customers?
7. Who approves customer-facing answers and evidence wording?

Recommended answer for now:

> Build the AMPD-branded web portal first, using the same access layer that can later be embedded into the AMPD app.
