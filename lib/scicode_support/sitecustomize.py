"""Names that newer numpy and scipy removed, put back for SciCode's step scripts.

Not part of SciCode: this file is the plugin's. The step scripts run on today's
packages (Python 3.14 has no wheels for the old ones), but SciCode was written
against numpy 1.x and scipy < 1.14, and two of its problems import
`scipy.integrate.simps` in their own dependency line, so they could not pass at
all. Models also write `np.trapz` and friends out of habit. Every alias here is
the documented replacement for the removed name, so a wrong answer still fails;
only code that would have run on the old versions now runs on the new ones.

Python imports `sitecustomize` at startup from the path, and the sandbox puts
lib/scicode_support on PYTHONPATH.
"""

try:
  import numpy as _np

  _numpy_aliases = {
    "trapz": _np.trapezoid,
    "float_": _np.float64,
    "complex_": _np.complex128,
    "cfloat": _np.complex128,
    "singlecomplex": _np.complex64,
    "longfloat": _np.longdouble,
    "string_": _np.bytes_,
    "unicode_": _np.str_,
    "round_": _np.round,
    "product": _np.prod,
    "cumproduct": _np.cumprod,
    "alltrue": _np.all,
    "sometrue": _np.any,
    "row_stack": _np.vstack,
    "mat": _np.asmatrix,
    "NaN": _np.nan,
    "Inf": _np.inf,
    "PINF": _np.inf,
    "NINF": -_np.inf,
    "infty": _np.inf,
    "Infinity": _np.inf,
    "float": float,
    "int": int,
    "complex": complex,
    "object": object,
  }

  def _in1d(ar1, ar2, assume_unique=False, invert=False, **kwargs):
    return _np.isin(_np.asarray(ar1).ravel(), ar2, assume_unique=assume_unique, invert=invert, **kwargs)

  def _asfarray(a, dtype=_np.float64):
    if not _np.issubdtype(dtype, _np.inexact):
      dtype = _np.float64
    return _np.asarray(a, dtype=dtype)

  def _msort(a):
    return _np.sort(a, axis=0)

  _numpy_aliases.update({"in1d": _in1d, "asfarray": _asfarray, "msort": _msort})
  for _name, _value in _numpy_aliases.items():
    if _name not in _np.__dict__:
      setattr(_np, _name, _value)
except Exception:  # noqa: BLE001 - a broken shim must never break a step script
  pass

try:
  import scipy.integrate as _integrate

  def _simps(y, x=None, dx=1.0, axis=-1, even=None):
    # simpson has no `even`; it is accepted and ignored, and simpson's own
    # handling of an even number of samples applies.
    return _integrate.simpson(y, x=x, dx=dx, axis=axis)

  for _name, _value in {"simps": _simps, "trapz": _integrate.trapezoid,
                        "cumtrapz": _integrate.cumulative_trapezoid}.items():
    if not hasattr(_integrate, _name):
      setattr(_integrate, _name, _value)
except Exception:  # noqa: BLE001
  pass
