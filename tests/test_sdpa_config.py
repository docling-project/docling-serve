"""Unit tests for _configure_sdpa() in docling_serve."""

from types import SimpleNamespace

import pytest
import torch

from docling_serve import _configure_sdpa


class _SDPARecorder:
    def __init__(self) -> None:
        self.flash: list[bool] = []
        self.mem_efficient: list[bool] = []
        self.math: list[bool] = []
        self.probed_calls: list[tuple[str, object]] = []

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            torch.backends.cuda,
            "enable_flash_sdp",
            lambda enabled: self.flash.append(enabled),
        )
        monkeypatch.setattr(
            torch.backends.cuda,
            "enable_mem_efficient_sdp",
            lambda enabled: self.mem_efficient.append(enabled),
        )
        monkeypatch.setattr(
            torch.backends.cuda,
            "enable_math_sdp",
            lambda enabled: self.math.append(enabled),
        )
        monkeypatch.setattr(
            torch,
            "zeros",
            lambda shape, device=None, dtype=None: SimpleNamespace(
                shape=shape, device=device, dtype=dtype
            ),
        )


def test_configure_sdpa_force_math_env_enable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit DOCLING_SERVE_FORCE_MATH_SDPA=1 forces Math SDPA immediately."""
    recorder = _SDPARecorder()
    recorder.install(monkeypatch)
    monkeypatch.setenv("DOCLING_SERVE_FORCE_MATH_SDPA", "1")
    monkeypatch.setattr(torch.version, "hip", None, raising=False)

    _configure_sdpa()

    assert recorder.flash == [False]
    assert recorder.mem_efficient == [False]
    assert recorder.math == [True]


def test_configure_sdpa_force_math_env_disable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit DOCLING_SERVE_FORCE_MATH_SDPA=0 skips probing even on ROCm."""
    recorder = _SDPARecorder()
    recorder.install(monkeypatch)
    monkeypatch.setenv("DOCLING_SERVE_FORCE_MATH_SDPA", "0")
    monkeypatch.setattr(torch.version, "hip", "10.1.0", raising=False)
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)

    def _unexpected_probe(*args, **kwargs):
        raise AssertionError(
            "Probe should not run when DOCLING_SERVE_FORCE_MATH_SDPA=0"
        )

    monkeypatch.setattr(
        torch.nn.functional, "scaled_dot_product_attention", _unexpected_probe
    )

    _configure_sdpa()

    assert recorder.flash == []
    assert recorder.mem_efficient == []
    assert recorder.math == []


def test_configure_sdpa_noop_on_non_rocm(monkeypatch: pytest.MonkeyPatch) -> None:
    """On CUDA or CPU (torch.version.hip is None), _configure_sdpa is a no-op."""
    recorder = _SDPARecorder()
    recorder.install(monkeypatch)
    monkeypatch.delenv("DOCLING_SERVE_FORCE_MATH_SDPA", raising=False)
    monkeypatch.setattr(torch.version, "hip", None, raising=False)
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)

    def _unexpected_probe(*args, **kwargs):
        raise AssertionError("Probe should not run on non-ROCm platforms")

    monkeypatch.setattr(
        torch.nn.functional, "scaled_dot_product_attention", _unexpected_probe
    )

    _configure_sdpa()

    assert recorder.flash == []
    assert recorder.mem_efficient == []
    assert recorder.math == []


def test_configure_sdpa_rocm_probe_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    """On ROCm when SDPA probe succeeds for all dtypes, backends remain untouched."""
    recorder = _SDPARecorder()
    recorder.install(monkeypatch)
    monkeypatch.delenv("DOCLING_SERVE_FORCE_MATH_SDPA", raising=False)
    monkeypatch.setattr(torch.version, "hip", "10.1.0", raising=False)
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(torch.cuda, "device_count", lambda: 1)
    monkeypatch.setattr(
        torch.cuda,
        "get_device_properties",
        lambda idx: SimpleNamespace(gcnArchName="gfx942"),
    )

    def _healthy_sdpa(q, k, v):
        recorder.probed_calls.append((q.device, q.dtype))
        return q

    monkeypatch.setattr(
        torch.nn.functional, "scaled_dot_product_attention", _healthy_sdpa
    )

    _configure_sdpa()

    assert recorder.probed_calls == [
        ("cuda:0", torch.float16),
        ("cuda:0", torch.bfloat16),
    ]
    assert recorder.flash == []
    assert recorder.mem_efficient == []
    assert recorder.math == []


def test_configure_sdpa_rocm_fallback_on_hip_invalid_image(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On ROCm when SDPA raises hipErrorInvalidImage / invalid device image, fallback enables Math SDPA."""
    recorder = _SDPARecorder()
    recorder.install(monkeypatch)
    monkeypatch.delenv("DOCLING_SERVE_FORCE_MATH_SDPA", raising=False)
    monkeypatch.setattr(torch.version, "hip", "10.1.0", raising=False)
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(torch.cuda, "device_count", lambda: 1)
    monkeypatch.setattr(
        torch.cuda,
        "get_device_properties",
        lambda idx: SimpleNamespace(gcnArchName="gfx1151"),
    )

    def _broken_sdpa(q, k, v):
        raise RuntimeError("HIP error: invalid device image (hipErrorInvalidImage)")

    monkeypatch.setattr(
        torch.nn.functional, "scaled_dot_product_attention", _broken_sdpa
    )

    _configure_sdpa()

    assert recorder.flash == [False]
    assert recorder.mem_efficient == [False]
    assert recorder.math == [True]


def test_configure_sdpa_rocm_ignores_non_kernel_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unrelated errors like 'invalid argument' do not disable Flash/Mem-Efficient SDPA."""
    recorder = _SDPARecorder()
    recorder.install(monkeypatch)
    monkeypatch.delenv("DOCLING_SERVE_FORCE_MATH_SDPA", raising=False)
    monkeypatch.setattr(torch.version, "hip", "10.1.0", raising=False)
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(torch.cuda, "device_count", lambda: 1)
    monkeypatch.setattr(
        torch.cuda,
        "get_device_properties",
        lambda idx: SimpleNamespace(gcnArchName="gfx1100"),
    )

    def _invalid_arg_sdpa(q, k, v):
        raise RuntimeError("invalid argument: tensor shape mismatch")

    monkeypatch.setattr(
        torch.nn.functional, "scaled_dot_product_attention", _invalid_arg_sdpa
    )

    _configure_sdpa()

    assert recorder.flash == []
    assert recorder.mem_efficient == []
    assert recorder.math == []


def test_configure_sdpa_rocm_multi_gpu_fallback_on_second_device(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """In multi-GPU setups, if device 0 passes but device 1 fails, process-wide Math fallback is enabled."""
    recorder = _SDPARecorder()
    recorder.install(monkeypatch)
    monkeypatch.delenv("DOCLING_SERVE_FORCE_MATH_SDPA", raising=False)
    monkeypatch.setattr(torch.version, "hip", "10.1.0", raising=False)
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(torch.cuda, "device_count", lambda: 2)
    monkeypatch.setattr(
        torch.cuda,
        "get_device_properties",
        lambda idx: SimpleNamespace(gcnArchName="gfx1100" if idx == 0 else "gfx1151"),
    )

    def _mixed_sdpa(q, k, v):
        if q.device == "cuda:1":
            raise RuntimeError("HIP error: invalid device image")
        return q

    monkeypatch.setattr(
        torch.nn.functional, "scaled_dot_product_attention", _mixed_sdpa
    )

    _configure_sdpa()

    assert recorder.flash == [False]
    assert recorder.mem_efficient == [False]
    assert recorder.math == [True]
