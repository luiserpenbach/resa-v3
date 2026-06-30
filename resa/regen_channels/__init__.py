"""regen_channels — high-fidelity regen cooling channel generator + solver.

YAML-as-truth: contour, channel layout (straight / spiral / switching helix,
variable height, fixed or variable rib), 1D thermal-hydraulic solve, 3D
visualization, STL / CSV export.
"""
from .config import RegenConfig
from .contour import Contour, build_contour
from .layout import ChannelLayout

__all__ = ["RegenConfig", "Contour", "build_contour", "ChannelLayout"]
__version__ = "0.1.0"
