"""Stable public contract API introduced in case25.

WHY: version-suffixed modules accumulated from case21-case24 and made reuse ambiguous. New code should
import from ``core.contracts``; historical modules remain only for regression compatibility.
"""
from .typed_contracts import *
from .analysis_spec import AnalysisSpecification,build_analysis_spec,check_analysis_spec
