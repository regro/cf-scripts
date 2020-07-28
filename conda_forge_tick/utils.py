import datetime
import typing
import copy
from collections.abc import Callable
from collections import defaultdict
import contextlib
import itertools
import json
import logging
import os
import re
from typing import Any, Tuple, Iterable, Union, Optional, IO
from collections.abc import MutableMapping, Set
from concurrent.futures import (
    ProcessPoolExecutor,
    ThreadPoolExecutor,
    Executor,
)
import subprocess

import github3
import jinja2
import boto3

import networkx as nx

if typing.TYPE_CHECKING:
    from mypy_extensions import TypedDict
    from .migrators_types import PackageName, RequirementsTypedDict
    from conda_forge_tick.migrators_types import MetaYamlTypedDict

T = typing.TypeVar("T")
TD = typing.TypeVar("TD", bound=dict, covariant=True)

pin_sep_pat = re.compile(r" |>|<|=|\[")

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


def eval_cmd(cmd, **kwargs):
    """run a command capturing stdout

    stderr is printed for debugging
    any kwargs are added to the env
    """
    env = copy.deepcopy(os.environ)
    timeout = kwargs.pop("timeout", None)
    env.update(kwargs)
    c = subprocess.run(
        cmd, shell=True, stdout=subprocess.PIPE, env=env, timeout=timeout,
    )
    if c.returncode != 0:
        print(c.stdout.decode("utf-8"), flush=True)
        raise subprocess.CalledProcessError(
            "Command '%s' failed with return code %s!" % (cmd, c.returncode)
        )

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


class LazyJson(MutableMapping):
    """Lazy load a dict from a json file and save it when updated"""

    def __init__(self, file_name: str):
        self.file_name = file_name
        # If the file doesn't exist create an empty file
        if not os.path.exists(self.file_name):
            os.makedirs(os.path.split(self.file_name)[0], exist_ok=True)
            with open(self.file_name, "w") as f:
                dump({}, f)
        self.data: Optional[dict] = None

    def __len__(self) -> int:
        self._load()
        assert self.data is not None
        return len(self.data)

    def __iter__(self) -> typing.Iterator[Any]:
        self._load()
        assert self.data is not None
        yield from self.data

    def __delitem__(self, v: Any) -> None:
        self._load()
        assert self.data is not None
        del self.data[v]
        self._dump()

    def _load(self) -> None:
        if self.data is None:
            try:
                with open(self.file_name, "r") as f:
                    self.data = load(f)
            except FileNotFoundError:
                print(os.getcwd())
                print(os.listdir("."))
                raise

    def _dump(self) -> None:
        self._load()
        with open(self.file_name, "w") as f:
            dump(self.data, f)

    def __getitem__(self, item: Any) -> Any:
        self._load()
        assert self.data is not None
        return self.data[item]

    def __setitem__(self, key: Any, value: Any) -> None:
        self._load()
        assert self.data is not None
        self.data[key] = value
        self._dump()

    def __getstate__(self) -> dict:
        state = self.__dict__.copy()
        state["data"] = None
        return state

    def __enter__(self) -> "LazyJson":
        return self

    def __exit__(self, *args: Any) -> Any:
        self._dump()


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

    env = jinja2.Environment(undefined=NullUndefined)
    if for_pinning:
        content = env.from_string(text).render(**kwargs, **CB_CONFIG_PINNING)
    else:
        content = env.from_string(text).render(**kwargs, **CB_CONFIG)
    return content


def parse_meta_yaml(text: str, for_pinning=False, **kwargs: Any) -> "MetaYamlTypedDict":
    """Parse the meta.yaml.

    Parameters
    ----------
    text : str
        The raw text in conda-forge feedstock meta.yaml file

    Returns
    -------
    dict :
        The parsed YAML dict. If parsing fails, returns an empty dict.

    """
    from conda_build.config import Config
    from conda_build.metadata import parse

    if for_pinning:
        content = render_meta_yaml(text, for_pinning=for_pinning)
    else:
        content = render_meta_yaml(text)
    return parse(content, Config(**kwargs))


def setup_logger(logger: logging.Logger, level: Optional[str] = "INFO") -> None:
    """Basic configuration for logging

    """
    logger.setLevel(level.upper())
    ch = logging.StreamHandler()
    ch.setLevel(level.upper())
    ch.setFormatter(
        logging.Formatter("%(asctime)-15s %(levelname)-8s %(name)s || %(message)s"),
    )
    logger.addHandler(ch)


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


def get_requirements(
    meta_yaml: "MetaYamlTypedDict",
    outputs: bool = True,
    build: bool = True,
    host: bool = True,
    run: bool = True,
) -> "Set[PackageName]":
    """Get the list of recipe requirements from a meta.yaml dict

    Parameters
    ----------
    meta_yaml: `dict`
        a parsed meta YAML dict
    outputs : `bool`
        if `True` (default) return top-level requirements _and_ all
        requirements in `outputs`, otherwise just return top-level
        requirememts.
    build, host, run : `bool`
        include (`True`) or not (`False`) requirements from these sections

    Returns
    -------
    reqs : `set`
        the set of recipe requirements
    """
    kw = dict(build=build, host=host, run=run)
    reqs = _parse_requirements(meta_yaml.get("requirements", {}), **kw)
    outputs_ = meta_yaml.get("outputs", []) or [] if outputs else []
    for output in outputs_:
        for req in _parse_requirements(output.get("requirements", {}) or {}, **kw):
            reqs.add(req)
    return reqs


def _parse_requirements(
    req: Union[None, typing.List[str], "RequirementsTypedDict"],
    build: bool = True,
    host: bool = True,
    run: bool = True,
) -> typing.MutableSet["PackageName"]:
    """Flatten a YAML requirements section into a list of names
    """
    if not req:  # handle None as empty
        return set()
    if isinstance(req, list):  # simple list goes to both host and run
        reqlist = req if (host or run) else []
    else:
        _build = list(as_iterable(req.get("build", []) or [] if build else []))
        _host = list(as_iterable(req.get("host", []) or [] if host else []))
        _run = list(as_iterable(req.get("run", []) or [] if run else []))
        reqlist = _build + _host + _run

    packages = (pin_sep_pat.split(x)[0].lower() for x in reqlist if x is not None)
    return {typing.cast("PackageName", pkg) for pkg in packages}


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
                n_workers=max_workers, processes=processes,
            ) as cluster:
                with distributed.Client(cluster) as client:
                    yield ClientExecutor(client)
    else:
        raise NotImplementedError("That kind is not implemented")


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
        separators=separators,
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
        separators=separators,
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
    fp: IO[str], object_hook: "Callable[[dict], Any]" = object_hook, **kwargs: Any,
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


def dump_graph_dynamo(
    gx: nx.DiGraph, tablename: str = "graph", region: str = "us-east-2",
) -> None:
    print(f"DynamoDB dump to {tablename} in {region}")
    ddb = boto3.resource("dynamodb", region_name=region)
    table = ddb.Table(tablename)
    with table.batch_writer() as batch:
        for node in gx.nodes:
            if not node:
                continue
            preds = [n for n in gx.predecessors(node) if n]
            preds.sort()
            item = {"node_id": node}
            if preds:
                item["predecessors"] = preds
            batch.put_item(Item=item)


def dump_graph(
    gx: nx.DiGraph,
    filename: str = "graph.json",
    tablename: str = "graph",
    region: str = "us-east-2",
) -> None:
    dump_graph_json(gx, filename)
    # dump_graph_dynamo(gx, tablename, region)


def load_graph(filename: str = "graph.json") -> nx.DiGraph:
    with open(filename, "r") as f:
        nld = load(f)
    return nx.node_link_graph(nld)


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
    if os.environ.get("GITHUB_TOKEN"):
        return github3.login(token=os.environ["GITHUB_TOKEN"])
    else:
        return github3.login(os.environ["USERNAME"], os.environ["PASSWORD"])


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


def extract_requirements(meta_yaml):
    strong_exports = False
    requirements_dict = defaultdict(set)
    for block in [meta_yaml] + meta_yaml.get("outputs", []) or []:
        req: "RequirementsTypedDict" = block.get("requirements", {}) or {}
        if isinstance(req, list):
            requirements_dict["run"].update(set(req))
            continue
        for section in ["build", "host", "run"]:
            requirements_dict[section].update(
                list(as_iterable(req.get(section, []) or [])),
            )
        test: "TestTypedDict" = block.get("test", {})
        requirements_dict["test"].update(test.get("requirements", []) or [])
        requirements_dict["test"].update(test.get("requires", []) or [])
        run_exports = (block.get("build", {}) or {}).get("run_exports", {})
        if isinstance(run_exports, dict) and run_exports.get("strong"):
            strong_exports = True
    for k in list(requirements_dict.keys()):
        requirements_dict[k] = {v for v in requirements_dict[k] if v}
    req_no_pins = {
        k: {pin_sep_pat.split(x)[0].lower() for x in v}
        for k, v in dict(requirements_dict).items()
    }
    return dict(requirements_dict), req_no_pins, strong_exports
