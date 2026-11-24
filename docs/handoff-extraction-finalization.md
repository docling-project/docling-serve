# Extraction errors and metering handoff

Updated 2026-10-01. Error-handling fixes are implemented; deployment verification remains. Billing/metrics are a separate follow-up and do not block the extraction API contract.

## Error handling: verify on the service

Published Docling `b4d9be5d` includes transport/HTTP-body redaction, wrapped-timeout classification and scoped SDK item reasons; Jobkit `0065e095cb` carries the reasons into callbacks. Focused regressions pass. Main conflicts are resolved, branch updates and refreshed locks are pushed, and DCO is green. Serve package/UI/lint CI passes at `3df7c583`. GitHub image jobs remain part of the existing CI workflow.

Confirm the deployed image includes these fixes and `debug_error_details=false`. Public errors should retain safe context/status without backend addresses/bodies; internal logs retain detail, and debug opt-in exposes it. Rerun the formerly slow schema at the server's 60-second timeout using [docling-extractbench](https://github.ibm.com/docling-project/docling-extractbench/). Inspect document status/counts and item errors, not just terminal task status.

## Metering: define policy, then implement

Extraction emits the shared callback lifecycle, with artifacts uploaded before document completion. Independent dispatch threads mean arrival order is not guaranteed. Item failure reasons are preserved, but extraction work fields/hash are unset and conversion-style metrics are absent.

| Owner | Follow-up / acceptance |
|---|---|
| Billing owner | Define chargeable work for timeouts, retries, partial success and failed exports; choose attempted pages/tokens and prevent retry double counting. |
| Docling + Jobkit | Attribute every lifecycle event to convert/chunk/extract, using optional task type unless the gateway already records it at submission. |
| Jobkit | Add selected-page counts and source hash under that policy; distinguish unpaginated input from failure before selection. Test selected pages, unpaginated input, pre-inference failure and target-write failure. |
| Jobkit | Emit success/failure/work metrics for successful, partial and failed extraction. Keep processing time's existing meaning; do not reuse conversion character/table/picture counts. Token usage may be absent on timeouts. |
