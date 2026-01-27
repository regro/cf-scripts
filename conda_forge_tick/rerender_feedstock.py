import os

from conda_forge_feedstock_ops.rerender import rerender as _rerender


def rerender_feedstock(feedstock_dir, timeout=900, use_container=None):
    """Rerender a feedstock.

    Parameters
    ----------
    feedstock_dir : str
        The path to the feedstock directory.
    timeout : int, optional
        The timeout for the rerender in seconds, by default 900.
    use_container
        Whether to use a container to run the parsing.
        If None, the function will use a container if the environment
        variable `CF_FEEDSTOCK_OPS_IN_CONTAINER` is 'false'. This feature can be
        used to avoid container in container calls.

    Returns
    -------
    str
        The commit message for the rerender. If None, the rerender didn't change anything.
    """
    local_pinnings = os.path.join(
        os.path.expandvars("${CONDA_PREFIX}"), "conda_build_config.yaml"
    )
    return _rerender(
        feedstock_dir,
        exclusive_config_file=local_pinnings,
        timeout=timeout,
        use_container=use_container,
    )
