import torch

def get_device_info():
    if torch.cuda.is_available():
        # This works for both CUDA and ROCm as PyTorch uses the same API
        count = torch.cuda.device_count()
        devices = [torch.cuda.get_device_name(i) for i in range(count)]
        return "CUDA or ROCm", count, devices
    return None, 0, []

def check_xpu():
    if hasattr(torch, "xpu") and torch.xpu.is_available():
        print("Intel XPU is available!")
    else:
        print("Intel XPU is not available.")

if __name__ == "__main__":
    print("== Checking for GPUs ==")
    backend, count, devices = get_device_info()
    if backend:
        print(f"{backend} is available!")
        print(f"Device count: {count}")
        for i, name in enumerate(devices):
            print(f"Device {i} name: {name}")
    else:
        print("CUDA or ROCm is not available.")

    check_xpu()
