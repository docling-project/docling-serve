import torch

def check_cuda():
    if torch.cuda.is_available():
        print("CUDA is available!")
        print(f"CUDA device count: {torch.cuda.device_count()}")
        print(f"Device name: {torch.cuda.get_device_name(0)}")
    else:
        print("CUDA is not available.")

def check_rocm():
    if hasattr(torch.version, "hip") and torch.version.hip:
        print("ROCm (AMD) is available!")
        print(f"ROCm device count: {torch.cuda.device_count()}")
        print(f"Device name: {torch.cuda.get_device_name(0)}")
    else:
        print("ROCm is not available.")

def check_xpu():
    if hasattr(torch, "xpu") and torch.xpu.is_available():
        print("Intel XPU is available!")
    else:
        print("Intel XPU is not available.")

if __name__ == "__main__":
    print("== Checking for GPUs ==")
    check_cuda()
    check_rocm()
    check_xpu()