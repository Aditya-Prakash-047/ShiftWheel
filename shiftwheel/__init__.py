import os

__version__ = "1.5.1"

# numpy's OpenBLAS reserves a work buffer per CPU thread at import: ~490 MB of committed memory
# on a 16-thread CPU, for linear algebra ShiftWheel never does. One thread costs ~8 MB.
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
