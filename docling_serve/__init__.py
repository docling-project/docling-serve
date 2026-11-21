# SPDX-FileCopyrightText: The Docling Contributors
# SPDX-License-Identifier: MIT

import logging
import os

_log = logging.getLogger(__name__)

_HIP_KERNEL_ERROR_TOKENS = (
    "hiperrorinvalidimage",
    "invalid device image",
    "hiperrorinvalidkernelfile",
    "hiperrorinvaliddevicefunction",
    "invalid device function",
)


def _is_hip_kernel_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(token in msg for token in _HIP_KERNEL_ERROR_TOKENS)


def _configure_sdpa() -> None:
    """Configure PyTorch SDPA backends safely across platforms.

    On AMD ROCm architectures lacking precompiled FlashAttention / Composable-Kernel
    fatbin kernels (such as Strix Halo gfx1151 or Strix Point gfx1150), automatically
    fall back to PyTorch's native Math SDPA backend to prevent `hipErrorInvalidImage`.

    On NVIDIA CUDA (12.8, 13.0, OpenShift) and CPU, this is a complete no-op by
    default, preserving native FlashAttention-2 and cuDNN performance.
    """
    try:
        import torch

        force_math = os.environ.get("DOCLING_SERVE_FORCE_MATH_SDPA", "auto").lower()

        # 1. Explicit user override
        if force_math in ("1", "true", "yes"):
            if hasattr(torch, "backends") and hasattr(torch.backends, "cuda"):
                torch.backends.cuda.enable_flash_sdp(False)
                torch.backends.cuda.enable_mem_efficient_sdp(False)
                torch.backends.cuda.enable_math_sdp(True)
                _log.info(
                    "SDPA: Force Math backend enabled via env (flash=False, mem_efficient=False, math=True)"
                )
            return

        if force_math in ("0", "false", "no"):
            _log.debug(
                "SDPA: Auto-configuration disabled via DOCLING_SERVE_FORCE_MATH_SDPA=0"
            )
            return

        # 2. Platform guard: Only probe and modify ROCm/HIP systems
        is_rocm = (
            hasattr(torch, "version")
            and getattr(torch.version, "hip", None) is not None
        )
        if not is_rocm:
            # NVIDIA CUDA or CPU: leave PyTorch default backends intact
            return

        # 3. Auto-detect on ROCm via lightweight canary probe across all visible GPUs
        if hasattr(torch, "cuda") and torch.cuda.is_available():
            count_fn = getattr(torch.cuda, "device_count", None)
            num_devices = count_fn() if callable(count_fn) else 0
            device_ids = (
                list(range(num_devices))
                if num_devices > 0
                else [torch.cuda.current_device()]
            )
            probe_dtypes = tuple(
                dt
                for dt in (
                    getattr(torch, "float16", None),
                    getattr(torch, "bfloat16", None),
                )
                if dt is not None
            )

            for device_id in device_ids:
                arch_name = getattr(
                    torch.cuda.get_device_properties(device_id),
                    "gcnArchName",
                    "unknown",
                )
                try:
                    for dtype in probe_dtypes:
                        q = torch.zeros(
                            (1, 1, 1, 64),
                            device=f"cuda:{device_id}",
                            dtype=dtype,
                        )
                        torch.nn.functional.scaled_dot_product_attention(q, q, q)
                    _log.debug(
                        "ROCm SDPA: Flash/Mem-Efficient kernels verified on device %s (%s)",
                        device_id,
                        arch_name,
                    )
                except Exception as exc:
                    if _is_hip_kernel_error(exc):
                        torch.backends.cuda.enable_flash_sdp(False)
                        torch.backends.cuda.enable_mem_efficient_sdp(False)
                        torch.backends.cuda.enable_math_sdp(True)
                        _log.warning(
                            "ROCm SDPA: Device %s (%s) lacks precompiled FlashAttention kernels. "
                            "Fallback to Math SDPA enabled (hipErrorInvalidImage avoided).",
                            device_id,
                            arch_name,
                        )
                        return
                    _log.debug(
                        "ROCm SDPA probe on device %s returned non-kernel error: %s",
                        device_id,
                        exc,
                    )
    except Exception as exc:
        _log.debug("SDPA configuration skipped: %s", exc)
