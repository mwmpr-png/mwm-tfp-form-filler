"""MWM Ai TFP Form Filler application package."""

# Capture and install the HSBC-aware case builder before app.main imports
# ``build_case`` from app.extractor. The wrapper preserves the existing
# production extraction path unchanged for non-HSBC cases.
from . import extractor as _extractor
from .hsbc_entry import build_case as _hsbc_aware_build_case

_extractor.build_case = _hsbc_aware_build_case
