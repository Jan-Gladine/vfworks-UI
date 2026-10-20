"""Template for Custom Monitor Validation

Filename should be renamed to match your designated filename in the Validity Frame
(e.g., 'custom_monitor_example.py') and is invoked automatically
when Monitor.validate_point(...) runs for that monitor.
"""

# Import your required third-party frameworks here
# import numpy as np
# import pandas as pd


def validate(monitor=None, **kwargs):
    """
    Dynamically executed by Monitor when this monitor has a matching custom script.

    Parameters:
    -----------
    **kwargs : dict
        Keyword context passed by Monitor.validate_point(...). Contains
        data_vector, monitor, and each feature name as a direct keyword.
    monitor : object, optional
        The active Monitor instance. Allows access to monitor.name,
        monitor.observes, monitor.spec_status, and monitor.last_observed_values.

    Returns:
    --------
    evaluations : dict
        Mapping of feature names to boolean validity statuses. Features omitted
        from this dictionary fall back to their built-in specification checks.
    """
    # 1. Pull out the context you need. The rest of this function is yours to define.
    data_vector = kwargs.get("data_vector", kwargs)
    monitor = kwargs.get("monitor", monitor)
    red = data_vector.get("colorRed", 0)
    green = data_vector.get("colorGreen", 0)
    blue = data_vector.get("colorBlue", 0)

    # =========================================================================
    # FUNCTIONAL CODE TEMPLATE (Customize for your monitor logic)
    # =========================================================================
    # Example: evaluate a cross-feature RGB envelope. This can express rules
    # that individual per-feature specifications cannot capture by themselves.
    # is_valid_red = 200 <= red <= 255
    # is_valid_green = 200 <= green <= 255
    # is_valid_blue = 200 <= blue <= 255
    #
    # return {
    #     "colorRed": is_valid_red,
    #     "colorGreen": is_valid_green,
    #     "colorBlue": is_valid_blue,
    # }
    # =========================================================================

    # Default fallback if code isn't implemented yet
    raise NotImplementedError(
        "The validate function must return a feature-to-bool mapping."
    )
