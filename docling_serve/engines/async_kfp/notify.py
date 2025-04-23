import ssl

import certifi
import httpx

from docling_serve.datamodel.callback import ProgressCallbackRequest
from docling_serve.datamodel.kfp import CallbackSpec


def notify_callbacks(
    payload: ProgressCallbackRequest,
    callbacks: list[CallbackSpec],
):
    if len(callbacks) == 0:
        return

    for callback in callbacks:
        # https://www.python-httpx.org/advanced/ssl/#configuring-client-instances
        if callback.ca_cert:
            ctx = ssl.create_default_context(cadata=callback.ca_cert)
        else:
            ctx = ssl.create_default_context(cafile=certifi.where())

        try:
            httpx.post(
                str(callback.url),
                headers=callback.headers,
                json=payload.model_dump(mode="json"),
                verify=ctx,
            )
        except httpx.HTTPError as err:
            print(f"Error notifying callback {callback.url}: {err}")
