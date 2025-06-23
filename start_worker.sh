#!/usr/bin/env bash

# TODO: set url from settings

exec rq worker --url redis://valkey.docling-serve.local \
    --worker-class='docling_serve.engines.async_rq.job.Worker' \
    conversion_queue
