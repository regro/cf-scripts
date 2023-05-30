import datetime
import traceback
import typing
import pprint
import warnings
from collections.abc import Callable
from collections import defaultdict
import contextlib
import itertools
import hashlib
import rapidjson as json
import logging
import tempfile
import io
import os
from typing import Any, Tuple, Iterable, Union, Optional, IO, Set
from collections.abc import MutableMapping
import github3
import jinja2
import ruamel.yaml

import networkx as nx

from . import sensitive_env

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

            for key in cfg_as_dict:
                try:
                    if cfg_as_dict[key].startswith("/"):
                        cfg_as_dict[key] = key
                except Exception:
                    pass

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


def get_sharded_path(file_path, n_dirs=5):
    """computed a sharded location for the LazyJson file."""
    top_dir, file_name = os.path.split(file_path)

    if len(top_dir) == 0:
        top_dir = "lazy_json"

    hx = hashlib.sha1(file_name.encode("utf-8")).hexdigest()[0:n_dirs]

    pth_parts = [top_dir] + [hx[i] for i in range(n_dirs)] + [file_name]

    return os.path.join(*pth_parts)


class LazyJson(MutableMapping):
    """Lazy load a dict from a json file and save it when updated"""

    def __init__(self, file_name: str):
        self.file_name = file_name
        self.sharded_path = get_sharded_path(file_name)
        # If the file doesn't exist create an empty file
        if not os.path.exists(self.sharded_path):
            os.makedirs(os.path.split(self.sharded_path)[0], exist_ok=True)
            with open(self.sharded_path, "w") as f:
                dump({}, f)
        self._data: Optional[dict] = None
        self._in_context = False

    @property
    def data(self):
        self._load()
        return self._data

    def clear(self):
        assert self._in_context
        self._load()
        self._data.clear()
        self._dump()

    def __len__(self) -> int:
        self._load()
        assert self._data is not None
        return len(self._data)

    def __iter__(self) -> typing.Iterator[Any]:
        self._load()
        assert self._data is not None
        yield from self._data

    def __delitem__(self, v: Any) -> None:
        assert self._in_context
        self._load()
        assert self._data is not None
        del self._data[v]
        self._dump()

    def _load(self) -> None:
        if self._data is None:
            try:
                with open(self.sharded_path) as f:
                    self._data = load(f)
            except FileNotFoundError:
                print(os.getcwd())
                print(os.listdir("."))
                raise

    def _dump(self, purge=False) -> None:
        self._load()
        with open(self.sharded_path, "w") as f:
            dump(self._data, f)
        if purge:
            # this evicts the josn from memory and trades i/o for mem
            # the bot uses too much mem if we don't do this
            self._data = None

    def __getitem__(self, item: Any) -> Any:
        self._load()
        assert self._data is not None
        return self._data[item]

    def __setitem__(self, key: Any, value: Any) -> None:
        assert self._in_context
        self._load()
        assert self._data is not None
        self._data[key] = value
        self._dump()

    def __getstate__(self) -> dict:
        state = self.__dict__.copy()
        state["_data"] = None
        return state

    def __enter__(self) -> "LazyJson":
        self._in_context = True
        return self

    def __exit__(self, *args: Any) -> Any:
        self._in_context = False
        self._dump(purge=True)


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


def default(obj: Any) -> Any:
    """For custom object serialization."""
    if isinstance(obj, LazyJson):
        return {"__lazy_json__": obj.file_name}
    elif isinstance(obj, Set):
        return {"__set__": True, "elements": sorted(obj)}
    raise TypeError(repr(obj) + " is not JSON serializable")


def object_hook(dct: dict) -> Union[LazyJson, Set, dict]:
    """For custom object deserialization."""
    if "__lazy_json__" in dct:
        return LazyJson(dct["__lazy_json__"])
    elif "__set__" in dct:
        return set(dct["elements"])
    return dct


def dumps(
    obj: Any,
    sort_keys: bool = True,
    separators: Any = (",", ":"),
    default: "Callable[[Any], Any]" = default,
    **kwargs: Any,
) -> str:
    """Returns a JSON string from a Python object."""
    return json.dumps(
        obj,
        sort_keys=sort_keys,
        # separators=separators,
        default=default,
        indent=1,
        **kwargs,
    )


def dump(
    obj: Any,
    fp: IO[str],
    sort_keys: bool = True,
    separators: Any = (",", ":"),
    default: "Callable[[Any], Any]" = default,
    **kwargs: Any,
) -> None:
    """Returns a JSON string from a Python object."""
    return json.dump(
        obj,
        fp,
        sort_keys=sort_keys,
        # separators=separators,
        default=default,
        indent=1,
        **kwargs,
    )


def loads(
    s: str, object_hook: "Callable[[dict], Any]" = object_hook, **kwargs: Any
) -> dict:
    """Loads a string as JSON, with appropriate object hooks"""
    return json.loads(s, object_hook=object_hook, **kwargs)


def load(
    fp: IO[str],
    object_hook: "Callable[[dict], Any]" = object_hook,
    **kwargs: Any,
) -> dict:
    """Loads a file object as JSON, with appropriate object hooks."""
    return json.load(fp, object_hook=object_hook, **kwargs)


def dump_graph_json(gx: nx.DiGraph, filename: str = "graph.json") -> None:
    nld = nx.node_link_data(gx)
    links = nld["links"]
    links2 = sorted(links, key=lambda x: f'{x["source"]}{x["target"]}')
    nld["links"] = links2
    with open(filename, "w") as f:
        dump(nld, f)


def dump_graph(
    gx: nx.DiGraph,
    filename: str = "graph.json",
    tablename: str = "graph",
    region: str = "us-east-2",
) -> None:
    dump_graph_json(gx, filename)


def load_graph(filename: str = "graph.json", reset_bad=False) -> nx.DiGraph:
    with open(filename) as f:
        nld = load(f)
    gx = nx.node_link_graph(nld)

    if reset_bad:
        for node in gx.nodes:
            with gx.nodes[node]["payload"] as attrs:
                attrs["parsing_error"] = False
                with attrs["pr_info"] as pri:
                    pri["bad"] = False

    return gx


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
