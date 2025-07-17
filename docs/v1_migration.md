# Migration to the `v1` API

Docling Serve from the initial prototype `v1alpha` API to the stable `v1` API.
This page provides simple instructions to upgrade your application to the new API.

## API changes

The breaking changes introduced in the `v1` release of Docling Serve are designed to provide a stable schema which
allows the project to provide new capabilities as new type of input sources, targets and also the definition of callback for event-driven applications.

### Endpoint names

All endpoints are renamed from `/v1alpha/` to `/v1/`.

### Sources

When using the `/v1/convert/source` endpoint, input documents have to be specified with the `sources: []` argument, which is replacing the usage of `file_sources` and `http_sources`.

Old version:

```jsonc
{
    "options": {},  // conversion options
    "file_sources": [  // input documents provided as base64-encoded strings
        {"base64_string": "abc123...", "filename": "file.pdf"}
    ],
    "http_sources": [  // input documents provided as http urls
        {"url": "https://..."}
    ]
}
```

New version:

```jsonc
{
    "options": {},  // conversion options
    "sources": [
        // input document provided as base64-encoded string
        {"kind": "kind", "base64_string": "abc123...", "filename": "file.pdf"},
        // input document provided as http urls
        {"kind": "http", "url": "https://..."},
    ]
}
```

### Targets

Switching between output formats, i.e. from the JSON inbody response to the zip archive response, users have to specify the `target` argument, which is replacing the usage of `options.return_as_file`.

Old version:

```jsonc
{
    "options": {
        "return_as_file": true  // <-- to be removed
    },
    // ...
}
```

New version:

```jsonc
{
    "options": {},
    "target": {"kind": "zip"},  // <-- add this
    // ...
}
```

## Continue with the old API

If you are not able to apply the changes above to your application, please consider pinning of the previous `v0.x` container images, e.g.

```sh
podman run -p 5001:5001 -e DOCLING_SERVE_ENABLE_UI=1 quay.io/docling-project/docling-serve:v0.16.1
```

_Note that the old prototype API will not be supported in new `v1.x` versions._
