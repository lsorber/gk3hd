"""Compatibility constants used by the vendored VAE.

Numz detects one old NVIDIA Conv3D allocator bug and enables an expensive
chunking workaround. Supported current PyTorch builds do not need it; ordinary
OOM handling remains in :mod:`memory_manager`.
"""

NVIDIA_CONV3D_MEMORY_BUG_WORKAROUND = False
