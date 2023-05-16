import datetime
import traceback
import typing
import copy
import pprint
import warnings
from collections import defaultdict
import contextlib
import itertools
import logging
import tempfile
import io
import os
from typing import Any, Tuple, Iterable, Optional, Set
from concurrent.futures import (
    ProcessPoolExecutor,
    ThreadPoolExecutor,
    Executor,
)
import subprocess

import github3
import jinja2
import ruamel.yaml

import networkx as nx

from . import sensitive_env
from .lazy_json_backends import LazyJson

if typing.TYPE_CHECKING:
    from mypy_extensions import TypedDict
    from conda_forge_tick.migrators_types import MetaYamlTypedDict


logger = logging.getLogger("conda_forge_tick.utils")

T = typing.TypeVar("T")
TD = typing.TypeVar("TD", bound=dict, covariant=True)

PACKAGE_STUBS = [
    "_compiler_stub",
    "subpackage_stub",
    "compatible_pin_stub",
    "cdt_stub",
]

CB_CONFIG = dict(
    os=os,
    environ=defaultdict(str),
    compiler=lambda x: x + "_compiler_stub",
    pin_subpackage=lambda *args, **kwargs: args[0],
    pin_compatible=lambda *args, **kwargs: args[0],
    cdt=lambda *args, **kwargs: "cdt_stub",
    cran_mirror="https://cran.r-project.org",
    datetime=datetime,
)

CB_CONFIG_PINNING = dict(
    os=os,
    environ=defaultdict(str),
    compiler=lambda x: x + "_compiler_stub",
    # The `max_pin, ` stub is so we know when people used the functions
    # to create the pins
    pin_subpackage=lambda *args, **kwargs: {"package_name": args[0], **kwargs},
    pin_compatible=lambda *args, **kwargs: {"package_name": args[0], **kwargs},
    cdt=lambda *args, **kwargs: "cdt_stub",
    cran_mirror="https://cran.r-project.org",
    datetime=datetime,
)


# https://stackoverflow.com/questions/6194499/pushd-through-os-system
@contextlib.contextmanager
def pushd(new_dir):
    previous_dir = os.getcwd()
    os.chdir(new_dir)
    try:
        yield
    finally:
        os.chdir(previous_dir)


def yaml_safe_load(stream):
    """Load a yaml doc safely"""
    return ruamel.yaml.YAML(typ="safe", pure=True).load(stream)


def yaml_safe_dump(data, stream=None):
    """Dump a yaml object"""
    yaml = ruamel.yaml.YAML(typ="safe", pure=True)
    yaml.default_flow_style = False
    return yaml.dump(data, stream=stream)


def render_meta_yaml(text: str, for_pinning=False, **kwargs) -> str:
    """Render the meta.yaml with Jinja2 variables.

    Parameters
    ----------
    text : str
        The raw text in conda-forge feedstock meta.yaml file

    Returns
    -------
    str
        The text of the meta.yaml with Jinja2 variables replaced.

    """

    cfg = dict(**kwargs)

    env = jinja2.Environment(undefined=NullUndefined)
    if for_pinning:
        cfg.update(**CB_CONFIG_PINNING)
    else:
        cfg.update(**CB_CONFIG)

    try:
        return env.from_string(text).render(**cfg)
    except Exception:
        import traceback

        logger.debug("render failure:\n%s", traceback.format_exc())
        logger.debug("render template: %s", text)
        logger.debug("render context:\n%s", pprint.pformat(cfg))
        raise


def parse_meta_yaml(
    text: str,
    for_pinning=False,
    platform=None,
    arch=None,
    recipe_dir=None,
    cbc_path=None,
    log_debug=False,
    orig_cbc_path=None,
    **kwargs: Any,
) -> "MetaYamlTypedDict":
    """Parse the meta.yaml.

    Parameters
    ----------
    text : str
        The raw text in conda-forge feedstock meta.yaml file
    platform : str, optional
        The platform (e.g., 'linux', 'osx', 'win').
    arch : str, optional
        The CPU architecture (e.g., '64', 'aarch64').
    recipe_dir : str, optional
        The path to the recipe being parsed.
    cbc_path : str, optional
        The path to global pinning file.
    orig_cbc_path : str, optional
        If not None, the original conda build config file to put next to
        the recipe while parsing.
    log_debug : bool, optional
        If True, print extra debugging info. Default is False.
    **kwargs : glob for extra keyword arguments
        These are passed to the conda_build.config.Config constructor.

    Returns
    -------
    dict :
        The parsed YAML dict. If parsing fails, returns an empty dict. May raise
        for some errors. Have fun.
    """

    def _run(*, use_orig_cbc_path):
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="The environment variable",
                category=UserWarning,
                module=r"conda_build\.environ",
            )
            return _parse_meta_yaml_impl(
                text,
                for_pinning=for_pinning,
                platform=platform,
                arch=arch,
                recipe_dir=recipe_dir,
                cbc_path=cbc_path,
                log_debug=log_debug,
                orig_cbc_path=(orig_cbc_path if use_orig_cbc_path else None),
                **kwargs,
            )

    try:
        return _run(use_orig_cbc_path=True)
    except (SystemExit, Exception):
        logger.debug("parsing w/ conda_build_config.yaml failed! " "trying without...")
        try:
            return _run(use_orig_cbc_path=False)
        except (SystemExit, Exception) as e:
            raise RuntimeError(
                "cond build error: %s\n%s"
                % (
                    repr(e),
                    traceback.format_exc(),
                ),
            )


def _parse_meta_yaml_impl(
    text: str,
    for_pinning=False,
    platform=None,
    arch=None,
    recipe_dir=None,
    cbc_path=None,
    log_debug=False,
    orig_cbc_path=None,
    **kwargs: Any,
) -> "MetaYamlTypedDict":
    from conda_build.config import Config
    from conda_build.metadata import parse, MetaData
    import conda_build.api
    import conda_build.environ
    from conda_build.variants import explode_variants

    if (
        recipe_dir is not None
        and cbc_path is not None
        and arch is not None
        and platform is not None
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "meta.yaml"), "w") as fp:
                fp.write(text)
            if orig_cbc_path is not None and os.path.exists(orig_cbc_path):
                with open(orig_cbc_path) as fp_r:
                    with open(
                        os.path.join(tmpdir, "conda_build_config.yaml"),
                        "w",
                    ) as fp_w:
                        fp_w.write(fp_r.read())

            def _run_parsing():
                logger.debug(
                    "parsing for platform %s with cbc %s and arch %s"
                    % (
                        platform,
                        cbc_path,
                        arch,
                    ),
                )
                config = conda_build.config.get_or_merge_config(
                    None,
                    platform=platform,
                    arch=arch,
                    exclusive_config_file=cbc_path,
                )
                _cbc, _ = conda_build.variants.get_package_combined_spec(
                    tmpdir,
                    config=config,
                )
                return config, _cbc

            if not log_debug:
                fout = io.StringIO()
                ferr = io.StringIO()
                # this code did use wulritzer.sys_pipes but that seemed
                # to cause conda-build to hang
                # versions:
                #   wurlitzer 3.0.2 py38h50d1736_1    conda-forge
                #   conda     4.11.0           py38h50d1736_0    conda-forge
                #   conda-build   3.21.7           py38h50d1736_0    conda-forge
                with contextlib.redirect_stdout(
                    fout,
                ), contextlib.redirect_stderr(ferr):
                    config, _cbc = _run_parsing()
            else:
                config, _cbc = _run_parsing()

            cfg_as_dict = {}
            for var in explode_variants(_cbc):
                try:
                    m = MetaData(tmpdir, config=config, variant=var)
                except SystemExit as e:
                    raise RuntimeError(repr(e))
                cfg_as_dict.update(conda_build.environ.get_dict(m=m))

            logger.debug("jinja2 environmment:\n%s", pprint.pformat(cfg_as_dict))

        cbc = Config(
            platform=platform,
            arch=arch,
            variant=cfg_as_dict,
            **kwargs,
        )
    else:
        _cfg = {}
        _cfg.update(kwargs)
        if platform is not None:
            _cfg["platform"] = platform
        if arch is not None:
            _cfg["arch"] = arch
        cbc = Config(**_cfg)
        cfg_as_dict = {}

    if for_pinning:
        content = render_meta_yaml(text, for_pinning=for_pinning, **cfg_as_dict)
    else:
        content = render_meta_yaml(text, **cfg_as_dict)

    try:
        return parse(content, cbc)
    except Exception:
        import traceback

        logger.debug("parse failure:\n%s", traceback.format_exc())
        logger.debug("parse template: %s", text)
        logger.debug("parse context:\n%s", pprint.pformat(cfg_as_dict))
        raise


def eval_cmd(cmd, **kwargs):
    """run a command capturing stdout

    stderr is printed for debugging
    any kwargs are added to the env
    """
    env = copy.deepcopy(os.environ)
    timeout = kwargs.pop("timeout", None)
    env.update(kwargs)
    c = subprocess.run(
        cmd,
        shell=True,
        stdout=subprocess.PIPE,
        env=env,
        timeout=timeout,
    )
    if c.returncode != 0:
        print(c.stdout.decode("utf-8"), flush=True)
        c.check_returncode()

    return c.stdout.decode("utf-8")


class UniversalSet(Set):
    """The universal set, or identity of the set intersection operation."""

    def __and__(self, other: Set) -> Set:
        return other

    def __rand__(self, other: Set) -> Set:
        return other

    def __contains__(self, item: Any) -> bool:
        return True

    def __iter__(self) -> typing.Iterator[Any]:
        return self

    def __next__(self) -> typing.NoReturn:
        raise StopIteration

    def __len__(self) -> int:
        return float("inf")


class NullUndefined(jinja2.Undefined):
    def __unicode__(self) -> str:
        return self._undefined_name

    def __getattr__(self, name: Any) -> str:
        return f"{self}.{name}"

    def __getitem__(self, name: Any) -> str:
        return f'{self}["{name}"]'


def setup_logger(logger: logging.Logger, level: Optional[str] = "INFO") -> None:
    """Basic configuration for logging"""
    logger.setLevel(level.upper())
    ch = logging.StreamHandler()
    ch.setLevel(level.upper())
    ch.setFormatter(
        logging.Formatter("%(asctime)-15s %(levelname)-8s %(name)s || %(message)s"),
    )
    logger.addHandler(ch)
    # this prevents duplicate logging messages
    logger.propagate = False


# TODO: upstream this into networkx?
def pluck(G: nx.DiGraph, node_id: Any) -> None:
    """Remove a node from a graph preserving structure.

    This will fuse edges together so that connectivity of the graph is not affected by
    removal of a node.  This function operates in-place.

    Parameters
    ----------
    G : networkx.Graph
    node_id : hashable

    """
    if node_id in G.nodes:
        new_edges = list(
            itertools.product(
                {_in for (_in, _) in G.in_edges(node_id)} - {node_id},
                {_out for (_, _out) in G.out_edges(node_id)} - {node_id},
            ),
        )
        G.remove_node(node_id)
        G.add_edges_from(new_edges)


@contextlib.contextmanager
def executor(kind: str, max_workers: int, daemon=True) -> typing.Iterator[Executor]:
    """General purpose utility to get an executor with its as_completed handler

    This allows us to easily use other executors as needed.
    """
    if kind == "thread":
        with ThreadPoolExecutor(max_workers=max_workers) as pool_t:
            yield pool_t
    elif kind == "process":
        with ProcessPoolExecutor(max_workers=max_workers) as pool_p:
            yield pool_p
    elif kind in ["dask", "dask-process", "dask-thread"]:
        import dask
        import distributed
        from distributed.cfexecutor import ClientExecutor

        processes = kind == "dask" or kind == "dask-process"

        with dask.config.set({"distributed.worker.daemon": daemon}):
            with distributed.LocalCluster(
                n_workers=max_workers,
                processes=processes,
            ) as cluster:
                with distributed.Client(cluster) as client:
                    yield ClientExecutor(client)
    else:
        raise NotImplementedError("That kind is not implemented")


def dump_graph_json(gx: nx.DiGraph, filename: str = "graph.json") -> None:
    nld = nx.node_link_data(gx)
    links = nld["links"]
    links2 = sorted(links, key=lambda x: f'{x["source"]}{x["target"]}')
    nld["links"] = links2
    lzj = LazyJson(filename)
    with lzj as attrs:
        attrs.update(nld)


def dump_graph(
    gx: nx.DiGraph,
    filename: str = "graph.json",
    tablename: str = "graph",
    region: str = "us-east-2",
) -> None:
    dump_graph_json(gx, filename)


def load_graph(filename: str = "graph.json") -> nx.DiGraph:
    return nx.node_link_graph(copy.deepcopy(LazyJson(filename).data))


# TODO: This type does not support generics yet sadly
# cc https://github.com/python/mypy/issues/3863
if typing.TYPE_CHECKING:

    class JsonFriendly(TypedDict, total=False):
        keys: typing.List[str]
        data: dict
        PR: dict


@typing.overload
def frozen_to_json_friendly(fz: None, pr: Optional[LazyJson] = None) -> None:
    pass


@typing.overload
def frozen_to_json_friendly(fz: Any, pr: Optional[LazyJson] = None) -> "JsonFriendly":
    pass


@typing.no_type_check
def frozen_to_json_friendly(fz, pr: Optional[LazyJson] = None):
    if fz is None:
        return None
    keys = sorted(list(fz.keys()))
    d = {"keys": keys, "data": dict(fz)}
    if pr:
        d["PR"] = pr
    return d


def github_client() -> github3.GitHub:
    with sensitive_env() as env:
        if env.get("GITHUB_TOKEN"):
            return github3.login(token=env["GITHUB_TOKEN"])
        else:
            return github3.login(env["USERNAME"], env["PASSWORD"])


@typing.overload
def as_iterable(x: dict) -> Tuple[dict]:
    ...


@typing.overload
def as_iterable(x: str) -> Tuple[str]:
    ...


@typing.overload
def as_iterable(x: Iterable[T]) -> Iterable[T]:
    ...


@typing.overload
def as_iterable(x: T) -> Tuple[T]:
    ...


@typing.no_type_check
def as_iterable(iterable_or_scalar):
    """Utility for converting an object to an iterable.
    Parameters
    ----------
    iterable_or_scalar : anything
    Returns
    -------
    l : iterable
        If `obj` was None, return the empty tuple.
        If `obj` was not iterable returns a 1-tuple containing `obj`.
        Otherwise return `obj`
    Notes
    -----
    Although both string types and dictionaries are iterable in Python, we are
    treating them as not iterable in this method.  Thus, as_iterable(dict())
    returns (dict, ) and as_iterable(string) returns (string, )

    Examples
    ---------
    >>> as_iterable(1)
    (1,)
    >>> as_iterable([1, 2, 3])
    [1, 2, 3]
    >>> as_iterable("my string")
    ("my string", )
    >>> as_iterable({'a': 1})
    ({'a': 1}, )
    """

    if iterable_or_scalar is None:
        return ()
    elif isinstance(iterable_or_scalar, (str, bytes)):
        return (iterable_or_scalar,)
    elif hasattr(iterable_or_scalar, "__iter__"):
        return iterable_or_scalar
    else:
        return (iterable_or_scalar,)


def _get_source_code(recipe_dir):
    try:
        from conda_build.api import render
        from conda_build.config import Config
        from conda_build.source import provide

        # Use conda build to do all the downloading/extracting bits
        md = render(
            recipe_dir,
            config=Config(**CB_CONFIG),
            finalize=False,
            bypass_env_check=True,
        )
        if not md:
            return None
        md = md[0][0]
        # provide source dir
        return provide(md)
    except (SystemExit, Exception) as e:
        raise RuntimeError("conda build src exception:" + str(e))


def sanitize_string(instr):
    with sensitive_env() as env:
        tokens = [env.get("PASSWORD", None)]
    for token in tokens:
        if token is not None:
            instr = instr.replace(token, "~" * len(token))

    return instr
