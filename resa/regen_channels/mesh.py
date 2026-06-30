"""3D channel mesh generation + binary STL export (no external CAD deps).

Each channel is swept along its 3D centerline. At every station the four
cross-section corners are placed using the local frame:
  * radial direction (floor at r + t_wall, ceiling at + h)
  * in-surface lateral direction perpendicular to the channel path:
    a width offset +/- w/2 decomposes into a circumferential shift
    (d_theta = +/- w/2 * cos(beta) / R) and a meridian shift
    (ds = -/+ w/2 * sin(beta)), the latter mapped to (dx, dr) via the wall
    slope. This keeps spiral channel side walls normal to the path.
"""
from __future__ import annotations

import struct

import numpy as np

from .layout import ChannelLayout


def channel_corner_curves(lay: ChannelLayout, k: int):
    """Return dict of 4 corner curves (n,3) for channel index k, in metres."""
    th0 = 2.0 * np.pi * k / lay.N
    th = th0 + lay.theta
    cosb, sinb = np.cos(lay.beta), np.sin(lay.beta)
    dxds = 1.0 / np.sqrt(1.0 + lay.drdx ** 2)      # dx per meridian length
    drds = lay.drdx * dxds

    half_w = 0.5 * lay.w
    out = {}
    for side, sgn in (("L", +1.0), ("R", -1.0)):
        ds_shift = -sgn * half_w * sinb            # meridian component
        dth = sgn * half_w * cosb / lay.r_ref      # circumferential comp.
        x_s = lay.x + ds_shift * dxds
        th_s = th + dth
        for lvl, radial in (("floor", lay.r + lay.t_wall + ds_shift * drds),
                            ("top", lay.r + lay.t_wall + lay.h + ds_shift * drds)):
            out[f"{lvl}_{side}"] = np.column_stack([
                x_s, radial * np.cos(th_s), radial * np.sin(th_s)])
    return out


def channel_centerline(lay: ChannelLayout, k: int):
    th = 2.0 * np.pi * k / lay.N + lay.theta
    rad = lay.r + lay.t_wall + 0.5 * lay.h
    return np.column_stack([lay.x, rad * np.cos(th), rad * np.sin(th)])


def _quad_strip_faces(i0: int, i1: int, n: int, flip=False):
    """Faces between two corner curves laid out as vertex rows i0.., i1.."""
    a = np.arange(n - 1)
    f1 = np.column_stack([i0 + a, i1 + a, i1 + a + 1])
    f2 = np.column_stack([i0 + a, i1 + a + 1, i0 + a + 1])
    f = np.vstack([f1, f2])
    return f[:, ::-1] if flip else f


def build_channel_mesh(lay: ChannelLayout, channel_ids=None,
                       scalar=None):
    """Triangle mesh of channel solids (flow volumes).

    Returns (verts (V,3) [m], faces (F,3), intensity (V,) or None).
    `scalar` is a per-station array broadcast to all vertices for coloring.
    """
    if channel_ids is None:
        channel_ids = range(lay.N)
    n = len(lay.x)
    all_v, all_f, all_c = [], [], []
    voff = 0
    for k in channel_ids:
        c = channel_corner_curves(lay, k)
        order = ["floor_L", "floor_R", "top_R", "top_L"]
        verts = np.vstack([c[name] for name in order])     # 4 rows of n
        idx = {name: voff + i * n for i, name in enumerate(order)}
        faces = [
            _quad_strip_faces(idx["floor_L"], idx["floor_R"], n),        # floor
            _quad_strip_faces(idx["top_R"], idx["top_L"], n),            # top
            _quad_strip_faces(idx["floor_R"], idx["top_R"], n),          # side R
            _quad_strip_faces(idx["top_L"], idx["floor_L"], n),          # side L
        ]
        # end caps
        for j, flip in ((0, True), (n - 1, False)):
            q = [idx[name] + j for name in order]
            cap = np.array([[q[0], q[1], q[2]], [q[0], q[2], q[3]]])
            faces.append(cap[:, ::-1] if flip else cap)
        all_v.append(verts)
        all_f.append(np.vstack(faces))
        if scalar is not None:
            all_c.append(np.tile(np.asarray(scalar, float), 4))
        voff += 4 * n
    verts = np.vstack(all_v)
    faces = np.vstack(all_f).astype(np.int64)
    inten = np.concatenate(all_c) if scalar is not None else None
    return verts, faces, inten


def write_binary_stl(path: str, verts: np.ndarray, faces: np.ndarray,
                     scale: float = 1000.0):
    """Binary STL (default mm for CAD import)."""
    v = verts[faces] * scale                     # (F, 3, 3)
    n = np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0])
    norm = np.linalg.norm(n, axis=1, keepdims=True)
    n = np.divide(n, np.maximum(norm, 1e-30))
    F = len(faces)
    rec = np.zeros(F, dtype=np.dtype([("n", "<3f4"), ("v", "<(3,3)f4"),
                                      ("attr", "<u2")]))
    rec["n"], rec["v"] = n.astype(np.float32), v.astype(np.float32)
    with open(path, "wb") as f:
        f.write(b"regen_channels binary STL".ljust(80, b" "))
        f.write(struct.pack("<I", F))
        rec.tofile(f)


def resolve_channel_ids(lay: ChannelLayout,
                        spec: int | list[int] | str | None = "all") -> list[int]:
    """Resolve channel index list from export config."""
    if spec is None or spec == "all":
        return list(range(lay.N))
    if isinstance(spec, int):
        ids = [spec]
    else:
        ids = list(spec)
    for k in ids:
        if k < 0 or k >= lay.N:
            raise ValueError(
                f"channel index {k} out of range for layout with {lay.N} channels")
    return ids


def mesh_export_basename(tag: str, channel_ids: list[int], ext: str) -> str:
    """Filename stem for STL/STEP: single channel vs compound."""
    if len(channel_ids) == 1:
        return f"{tag}_channel_{channel_ids[0]:02d}_mm.{ext}"
    return f"{tag}_channels_mm.{ext}"


def centerlines_export_basename(tag: str, channel_ids: list[int]) -> str:
    if len(channel_ids) == 1:
        return f"{tag}_channel_{channel_ids[0]:02d}_centerline_mm.csv"
    return f"{tag}_centerlines_mm.csv"


def html_3d_export_basename(tag: str, channel_ids: list[int]) -> str:
    if len(channel_ids) == 1:
        return f"{tag}_channel_{channel_ids[0]:02d}_3d.html"
    return f"{tag}_3d.html"


def _curve_wire_from_polyline(points: np.ndarray, scale: float):
    """Fit a B-spline edge wire through a 3D polyline (model units → mm)."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire
    from OCP.GeomAPI import GeomAPI_PointsToBSpline
    from OCP.gp import gp_Pnt
    from OCP.TColgp import TColgp_Array1OfPnt

    arr = TColgp_Array1OfPnt(1, len(points))
    for i, pt in enumerate(points):
        arr.SetValue(
            i + 1,
            gp_Pnt(float(pt[0] * scale), float(pt[1] * scale), float(pt[2] * scale)),
        )
    spline = GeomAPI_PointsToBSpline(arr)
    if not spline.IsDone():
        raise RuntimeError("failed to fit B-spline to channel edge curve")
    edge = BRepBuilderAPI_MakeEdge(spline.Curve()).Edge()
    return BRepBuilderAPI_MakeWire(edge).Wire()


def _loft_face_between_wires(wire_a, wire_b):
    """Ruled/lofted face between two open wires."""
    from OCP.BRepOffsetAPI import BRepOffsetAPI_ThruSections

    loft = BRepOffsetAPI_ThruSections(True, False, 1.0e-6)
    loft.AddWire(wire_a)
    loft.AddWire(wire_b)
    loft.CheckCompatibility(False)
    loft.Build()
    if not loft.IsDone():
        raise RuntimeError("failed to loft channel surface")
    return loft.Shape()


def _cap_face_from_corners(corners: np.ndarray, scale: float):
    """Coons patch closing one channel end (works for skewed helix ends)."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
    from OCP.BRepFill import BRepFill_Filling
    from OCP.GeomAbs import GeomAbs_Shape
    from OCP.gp import gp_Pnt

    fill = BRepFill_Filling()
    n = len(corners)
    for i in range(n):
        p0, p1 = corners[i], corners[(i + 1) % n]
        edge = BRepBuilderAPI_MakeEdge(
            gp_Pnt(float(p0[0] * scale), float(p0[1] * scale), float(p0[2] * scale)),
            gp_Pnt(float(p1[0] * scale), float(p1[1] * scale), float(p1[2] * scale)),
        ).Edge()
        fill.Add(edge, GeomAbs_Shape.GeomAbs_C0)
    fill.Build()
    if not fill.IsDone():
        raise RuntimeError("failed to build channel end cap")
    return fill.Face()


def build_channel_smooth_shape(lay: ChannelLayout, k: int, scale: float = 1000.0):
    """Closed shell/solid for one channel as six analytic surfaces."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Sewing

    c = channel_corner_curves(lay, k)
    order = ["floor_L", "floor_R", "top_R", "top_L"]
    side_pairs = [
        ("floor_L", "floor_R"),
        ("top_R", "top_L"),
        ("floor_R", "top_R"),
        ("top_L", "floor_L"),
    ]

    sewer = BRepBuilderAPI_Sewing(max(0.01, 1.0e-5 * scale))
    for a, b in side_pairs:
        wire_a = _curve_wire_from_polyline(c[a], scale)
        wire_b = _curve_wire_from_polyline(c[b], scale)
        sewer.Add(_loft_face_between_wires(wire_a, wire_b))
    for j in (0, -1):
        corners = np.array([c[name][j] for name in order])
        sewer.Add(_cap_face_from_corners(corners, scale))
    sewer.Perform()
    if sewer.NbFreeEdges() > 0:
        raise RuntimeError(
            f"channel {k} smooth shell has {sewer.NbFreeEdges()} free edges after sewing")
    return sewer.SewedShape()


def build_channels_smooth_shape(lay: ChannelLayout, channel_ids,
                              scale: float = 1000.0):
    """Sew one or more channel solids into a single shape."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Sewing

    ids = list(channel_ids)
    if len(ids) == 1:
        return build_channel_smooth_shape(lay, ids[0], scale=scale)

    sewer = BRepBuilderAPI_Sewing(max(0.01, 1.0e-5 * scale))
    for k in ids:
        sewer.Add(build_channel_smooth_shape(lay, k, scale=scale))
    sewer.Perform()
    return sewer.SewedShape()


def _shape_from_stl(stl_path: str, sew_tolerance: float = 0.01):
    """Read binary STL and sew triangle shells into one BRep shape."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Sewing
    from OCP.StlAPI import StlAPI_Reader
    from OCP.TopoDS import TopoDS_Shape

    shape = TopoDS_Shape()
    if not StlAPI_Reader().Read(shape, stl_path):
        raise RuntimeError(f"OCP failed to read mesh: {stl_path}")

    sewer = BRepBuilderAPI_Sewing(sew_tolerance)
    sewer.Add(shape)
    sewer.Perform()
    return sewer.SewedShape()


def write_step(path: str, lay: ChannelLayout, channel_ids=None,
               scale: float = 1000.0, faceted: bool = False):
    """STEP export of channel solids (default mm).

    By default builds six B-spline faces per channel (four walls + two end caps)
    so CAD imports show smooth surfaces instead of STL triangles. Set
    ``faceted=True`` to fall back to the tessellated STL route.
    Requires ``cadquery-ocp`` (``pip install cadquery-ocp``).
    """
    try:
        from OCP.IFSelect import IFSelect_ReturnStatus
        from OCP.Interface import Interface_Static
        from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer
    except ImportError as e:
        raise ImportError(
            "STEP export requires cadquery-ocp — pip install cadquery-ocp"
        ) from e

    import os
    import tempfile

    if channel_ids is None:
        channel_ids = list(range(lay.N))

    if faceted:
        verts, faces, _ = build_channel_mesh(lay, channel_ids)
        with tempfile.TemporaryDirectory() as tmpdir:
            stl_path = os.path.join(tmpdir, "channels.stl")
            write_binary_stl(stl_path, verts, faces, scale=scale)
            shape = _shape_from_stl(stl_path)
    else:
        shape = build_channels_smooth_shape(lay, channel_ids, scale=scale)

    # AP214 + no assembly tree: avoids NX "cyclic assembly structure" on
    # facet models that previously became thousands of NAUO components.
    Interface_Static.SetCVal_s("write.step.schema", "AP214")
    Interface_Static.SetCVal_s("write.step.assembly", "0")
    Interface_Static.SetCVal_s("xstep.cascade.unit", "MM")
    writer = STEPControl_Writer()
    writer.Transfer(shape, STEPControl_AsIs)
    status = writer.Write(str(path))
    if status != IFSelect_ReturnStatus.IFSelect_RetDone:
        raise RuntimeError(f"STEP write failed for {path}")


def inner_wall_surface(lay: ChannelLayout, n_theta: int = 90):
    """Revolved hot wall surface for context in the 3D view."""
    th = np.linspace(0, 2 * np.pi, n_theta)
    X = np.tile(lay.x[:, None], (1, n_theta))
    R = lay.r[:, None]
    return X, R * np.cos(th)[None, :], R * np.sin(th)[None, :]
