"""System Stats API endpoints."""

import psutil
import subprocess
from typing import Optional
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/system", tags=["system"])


class GPUStats(BaseModel):
    """GPU statistics."""
    name: str
    memory_used: int  # MB
    memory_total: int  # MB
    memory_percent: float
    gpu_utilization: Optional[float] = None
    temperature: Optional[float] = None


class SystemStats(BaseModel):
    """System statistics response."""
    cpu_percent: float
    cpu_count: int
    ram_used: int  # MB
    ram_total: int  # MB
    ram_percent: float
    gpu: Optional[GPUStats] = None


def get_nvidia_gpu_stats() -> Optional[GPUStats]:
    """Get NVIDIA GPU stats using nvidia-smi."""
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.used,memory.total,utilization.gpu,temperature.gpu",
                "--format=csv,noheader,nounits"
            ],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            line = result.stdout.strip().split("\n")[0]
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 5:
                name = parts[0]
                memory_used = int(parts[1])
                memory_total = int(parts[2])
                gpu_util = float(parts[3]) if parts[3] != "[N/A]" else None
                temp = float(parts[4]) if parts[4] != "[N/A]" else None

                return GPUStats(
                    name=name,
                    memory_used=memory_used,
                    memory_total=memory_total,
                    memory_percent=round((memory_used / memory_total) * 100, 1) if memory_total > 0 else 0,
                    gpu_utilization=gpu_util,
                    temperature=temp
                )
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
        pass
    return None


@router.get("/stats", response_model=SystemStats)
async def get_system_stats():
    """Get current system statistics (CPU, RAM, GPU)."""
    # CPU stats
    cpu_percent = psutil.cpu_percent(interval=0.1)
    cpu_count = psutil.cpu_count()

    # RAM stats
    memory = psutil.virtual_memory()
    ram_used = memory.used // (1024 * 1024)  # Convert to MB
    ram_total = memory.total // (1024 * 1024)
    ram_percent = memory.percent

    # GPU stats (NVIDIA)
    gpu_stats = get_nvidia_gpu_stats()

    return SystemStats(
        cpu_percent=cpu_percent,
        cpu_count=cpu_count,
        ram_used=ram_used,
        ram_total=ram_total,
        ram_percent=ram_percent,
        gpu=gpu_stats
    )
