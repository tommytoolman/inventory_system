# CODEX.md - Interaction Notes for Codex Agent

## Engagement Expectations
- Maintain active dialogue when investigating issues; confirm findings and explain reasoning before taking action.
- When adding or modifying code, describe the verification performed (or still required) and highlight any assumptions or potential risks.
- Cross-check existing services/utilities before introducing new helpers; if gaps exist, explain why a new abstraction is necessary.

## Reverb Listing Flow Reminder
- `ReverbService.create_listing_from_product` now centralises listing creation. Reuse this helper from UI routes or automations rather than duplicating payload logic.
- Ensure product images referenced in payloads are publicly accessible (`http/https`), otherwise Reverb will reject the request.
