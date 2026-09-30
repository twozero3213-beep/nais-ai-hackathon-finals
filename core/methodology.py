"""case20 verification methodology registry.

WHY THIS EXISTS (case20): team members must not scatter statistical-method rules across UI code.
Every method has one reusable contract: supported claim shape, required inputs, diagnostics,
and the evidence that must be preserved. When a method is changed, update this registry and
its tests so future collaborators can see *why* the rule exists.
"""
from __future__ import annotations

METHOD_REGISTRY = {
    "mean": {"family":"descriptive","requires":["outcome"],"diagnostics":[],"auto_reproduce":True},
    "proportion": {"family":"descriptive","requires":["outcome","success_value"],"diagnostics":[],"auto_reproduce":True},
    "welch_t": {"family":"two_group","requires":["outcome","group_column","group_a","group_b"],"diagnostics":["sample_size","variance","normality_context"],"auto_reproduce":False},
    "independent_t": {"family":"two_group","requires":["outcome","group_column","group_a","group_b"],"diagnostics":["sample_size","variance","normality_context"],"auto_reproduce":False},
    "paired_t": {"family":"paired","requires":["outcome","x_column"],"diagnostics":["paired_structure","difference_distribution"],"auto_reproduce":False},
    "mannwhitney_u": {"family":"two_group_nonparametric","requires":["outcome","group_column","group_a","group_b"],"diagnostics":["sample_size","distribution_shape_context"],"auto_reproduce":False},
    "wilcoxon_signed": {"family":"paired_nonparametric","requires":["outcome","x_column"],"diagnostics":["paired_structure"],"auto_reproduce":False},
    "pearson_r": {"family":"association","requires":["outcome","x_column"],"diagnostics":["linearity","outliers"],"auto_reproduce":False},
    "spearman_r": {"family":"association","requires":["outcome","x_column"],"diagnostics":["monotonicity"],"auto_reproduce":False},
    "chi_square": {"family":"categorical","requires":["outcome","group_column"],"diagnostics":["expected_counts"],"auto_reproduce":False},
    "fisher_exact": {"family":"categorical_2x2","requires":["outcome","group_column"],"diagnostics":["table_shape"],"auto_reproduce":False},
    "linear_regression": {"family":"regression","requires":["outcome","x_column"],"diagnostics":["linearity","residuals","homoscedasticity","influence"],"auto_reproduce":False},
    "logistic_regression": {"family":"regression_binary","requires":["outcome","x_column"],"diagnostics":["binary_outcome","convergence","separation"],"auto_reproduce":False},
}


def method_contract(method: str) -> dict:
    """Return a copy so UI/callers cannot mutate the shared registry accidentally."""
    return dict(METHOD_REGISTRY.get(method, {"family":"unknown","requires":[],"diagnostics":["human_review"],"auto_reproduce":False}))
