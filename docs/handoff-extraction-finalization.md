# Extraction errors and metering handoff

Updated 2026-10-01. Error-handling fixes are implemented; deployment verification remains. Billing/metrics are a separate follow-up and do not block the extraction API contract.

## Error handling: verify on the service

Transport redaction landed in Docling `7f237215`, with debug propagation in Jobkit `af845006` and Serve `b85ead7`. Docling `c8bccb025f` also gates HTTP error bodies and includes scoped item reasons in SDK exceptions; Jobkit `0065e095cb` carries those reasons into callbacks. Focused regressions pass.

Confirm the deployed image includes these fixes and `debug_error_details=false`. Public errors should retain safe context/status without backend addresses/bodies; internal logs retain detail, and debug opt-in exposes it. Rerun the formerly slow schema at the server's 60-second timeout using [docling-extractbench](https://github.ibm.com/docling-project/docling-extractbench/). Inspect document status/counts and item errors, not just terminal task status.

## Metering: define policy, then implement

Extraction emits the shared callback lifecycle, with artifacts uploaded before document completion. Independent dispatch threads mean arrival order is not guaranteed. Item failure reasons are preserved, but extraction work fields/hash are unset and conversion-style metrics are absent.

| Owner | Follow-up / acceptance |
|---|---|
| Billing owner | Define chargeable work for timeouts, retries, partial success and failed exports; choose attempted pages/tokens and prevent retry double counting. |
| Docling + Jobkit | Attribute every lifecycle event to convert/chunk/extract, using optional task type unless the gateway already records it at submission. |
| Jobkit | Add selected-page counts and source hash under that policy; distinguish unpaginated input from failure before selection. Test selected pages, unpaginated input, pre-inference failure and target-write failure. |
| Jobkit | Emit success/failure/work metrics for successful, partial and failed extraction. Keep processing time's existing meaning; do not reuse conversion character/table/picture counts. Token usage may be absent on timeouts. |
