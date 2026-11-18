# SPDX-FileCopyrightText: The Docling Contributors
# SPDX-License-Identifier: MIT

import logging
import os

_log = logging.getLogger(__name__)


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

        # 3. Auto-detect on ROCm via lightweight canary probe
        if hasattr(torch, "cuda") and torch.cuda.is_available():
            device_id = torch.cuda.current_device()
            arch_name = getattr(
                torch.cuda.get_device_properties(device_id), "gcnArchName", "unknown"
            )
            try:
                # Test 1-token SDPA probe on GPU
                q = torch.zeros(
                    (1, 1, 1, 64), device=f"cuda:{device_id}", dtype=torch.float16
                )
                torch.nn.functional.scaled_dot_product_attention(q, q, q)
                _log.debug(
                    "ROCm SDPA: Flash/Mem-Efficient kernels verified on %s", arch_name
                )
            except Exception as exc:
                if "invalid" in str(exc).lower() or "image" in str(exc).lower():
                    torch.backends.cuda.enable_flash_sdp(False)
                    torch.backends.cuda.enable_mem_efficient_sdp(False)
                    torch.backends.cuda.enable_math_sdp(True)
                    _log.warning(
                        "ROCm SDPA: Device %s lacks precompiled FlashAttention kernels. "
                        "Fallback to Math SDPA enabled (hipErrorInvalidImage avoided).",
                        arch_name,
                    )
                else:
                    _log.debug("ROCm SDPA probe returned non-kernel error: %s", exc)
    except Exception as exc:
        _log.debug("SDPA configuration skipped: %s", exc)


# Backwards compatibility alias
_configure_rocm_sdpa = _configure_sdpa

_configure_sdpa()
