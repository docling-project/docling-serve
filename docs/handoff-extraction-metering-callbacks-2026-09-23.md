# Extraction metering follow-up

Open, updated 2026-10-01. Extraction emits the shared callback lifecycle, but callback billing data and Prometheus metrics are not yet aligned with conversion.

## Existing behavior

- Ray sends `set_num_docs`, per-document completion, processed update and terminal task completion.
- Artifacts are uploaded before the corresponding document completion is emitted. Events are dispatched on separate threads; arrival order is not guaranteed.
- Failed-item reasons now reach document callbacks in the October 1 Jobkit changes.
- Extraction's callback projection has no converted `DoclingDocument`, timings or hash. Work counts/hash are therefore unset. The extraction worker does not emit conversion-style metrics.

## Work to scope and implement

| Owner | Change | Acceptance check |
|---|---|---|
| Jobkit | Populate extraction `num_pages` from selected page-scoped items and `doc_hash` from source input; retain zero pages for unpaginated input and unknown for failure before selection. | Selected-page, unpaginated, pre-inference failure and target-write failure cases. |
| Docling + Jobkit | Identify operation in callbacks with optional task type, unless the billing gateway already records it at submission. | Every lifecycle event can be attributed to convert/chunk/extract. |
| Jobkit | Emit extraction success/failure/work metrics without pretending extraction output is a converted document. | Metrics observable after successful, partial and failed extraction. |
| Billing owner | Define chargeable work for timeouts, retries, partial success and failed exports, and whether tokens or attempted pages are the billing unit. | Written policy matches callback/metric fields; no double counting across retries. |

Do not repurpose conversion output character/table/picture counts for extraction. Provider token usage can be absent on timeouts and varies by backend. Processing time should retain its existing meaning. Avoid promising callback arrival order unless delivery is serialized.

This is a separate SaaS billing/observability follow-up; it does not block using or finalizing the extraction API contract itself.
