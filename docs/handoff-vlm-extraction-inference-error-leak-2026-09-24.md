# Extraction model-backend errors: fixed

Updated 2026-10-01. The September 24 SaaS timeout exposed a raw Requests exception naming the internal backend. Transport redaction is committed in Docling `7f237215`, with debug-setting propagation in Jobkit `af845006` and Serve `b85ead7`.

October 1 local fixes extend the same debug gate to HTTP error response bodies, include item failure reasons in SDK `ExtractionError`, and project item reasons into Jobkit callbacks. Focused regression tests accompany the changes. These fixes are committed locally and still need push and deployment inclusion.

With `debug_error_details=false`, public errors retain safe model/request context and HTTP status but omit raw backend addresses/bodies. Debug true appends raw detail; internal logs retain it. Full result envelopes preserve structured item errors either way.

Final deployment check: confirm the image contains the fixes, debug is disabled, and the formerly slow schema is retried at the server's new 60-second timeout. Inspect document counts/status and item errors, not only terminal task status. ExtractBench's runner, examples and instructions now live in its `integrations/docling/` directory.
