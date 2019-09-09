import os
from collections import defaultdict

from collections.abc import Set, MutableMapping
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, \
    as_completed

import contextlib
import logging
import itertools
import json
import re

import github3
import jinja2
import networkx as nx

pin_sep_pat = re.compile(" |>|<|=|\[")

from collections import Mapping, Set, Sequence

# dual python 2/3 compatability, inspired by the "six" library
string_types = (str, bytes)
iteritems = lambda mapping: mapping.items()


class UniversalSet(Set):
    """The universal set, or identity of the set intersection operation."""

    def __and__(self, other):
        return other

    def __rand__(self, other):
        return other

    def __contains__(self, item):
        return True

    def __iter__(self):
        return self

    def __next__(self):
        raise StopIteration

    def __len__(self):
        return float("inf")


class NullUndefined(jinja2.Undefined):
    def __unicode__(self):
        return self._undefined_name

    def __getattr__(self, name):
        return "{}.{}".format(self, name)

    def __getitem__(self, name):
        return '{}["{}"]'.format(self, name)


class LazyJson(MutableMapping):
    """Lazy load a dict from a json file and save it when updated"""

    def __init__(self, file_name):
        self.file_name = file_name
        # If the file doesn't exist create an empty file
        if not os.path.exists(self.file_name):
            os.makedirs(os.path.split(self.file_name)[0], exist_ok=True)
            with open(self.file_name, "w") as f:
                dump({}, f)
        self.data = None

    def __len__(self) -> int:
        self._load()
        return len(self.data)

    def __iter__(self):
        self._load()
        yield from self.data

    def __delitem__(self, v):
        self._load()
        del self.data[v]
        self._dump()

    def _load(self):
        if self.data is None:
            try:
                with open(self.file_name, "r") as f:
                    self.data = load(f)
            except FileNotFoundError:
                print(os.getcwd())
                print(os.listdir("."))
                raise

    def _dump(self):
        self._load()
        with open(self.file_name, "w") as f:
            dump(self.data, f)

    def __getitem__(self, item):
        self._load()
        return self.data[item]

    def __setitem__(self, key, value):
        self._load()
        self.data[key] = value
        self._dump()

    def __getstate__(self):
        state = self.__dict__.copy()
        state["data"] = None
        return state

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._dump()


def render_meta_yaml(text):
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
    content = env.from_string(text).render(
        os=os,
        environ=defaultdict(str),
        compiler=lambda x: x + "_compiler_stub",
        pin_subpackage=lambda *args, **kwargs: "subpackage_stub",
        pin_compatible=lambda *args, **kwargs: "compatible_pin_stub",
        cdt=lambda *args, **kwargs: "cdt_stub",
        cran_mirror="https://cran.r-project.org",
    )
    return content


def parse_meta_yaml(text, **kwargs):
    """Parse the meta.yaml.

    Parameters
    ----------
    text : str
        The raw text in conda-forge feedstock meta.yaml file

    Returns
    -------
    dict :
        The parsed YAML dict. If parseing fails, returns an empty dict.

    """
    from conda_build.config import Config
    from conda_build.metadata import parse

    content = render_meta_yaml(text)
    return parse(content, Config(**kwargs))


def setup_logger(logger):
    """Basic configuration for logging

    """

    logging.basicConfig(
        level=logging.ERROR,
        format="%(asctime)-15s %(levelname)-8s %(name)s || %(message)s",
    )
    logger.setLevel(logging.INFO)


def pluck(G, node_id):
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
            )
        )
        G.remove_node(node_id)
        G.add_edges_from(new_edges)


def get_requirements(meta_yaml, outputs=True, build=True, host=True, run=True):
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
    outputs = meta_yaml.get("outputs", []) or [] if outputs else []
    for output in outputs:
        reqs.update(
            _parse_requirements(output.get("requirements", {}) or {}, **kw))
    return reqs


def _parse_requirements(req, build=True, host=True, run=True):
    """Flatten a YAML requirements section into a list of names
    """
    if not req:  # handle None as empty
        return set()
    if isinstance(req, list):  # simple list goes to both host and run
        reqlist = req if (host or run) else []
    else:
        build = list(as_iterable(req.get("build", []) or [] if build else []))
        host = list(as_iterable(req.get("host", []) or [] if host else []))
        run = list(as_iterable(req.get("run", []) or [] if run else []))
        reqlist = build + host + run
    return set(
        pin_sep_pat.split(x)[0].lower() for x in reqlist if x is not None)


@contextlib.contextmanager
def executor(kind, max_workers):
    """General purpose utility to get an executor with its as_completed handler

    This allows us to easily use other executors as needed.
    """
    if kind == "thread":
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            yield pool, as_completed
    elif kind == "process":
        with ProcessPoolExecutor(max_workers=max_workers) as pool:
            yield pool, as_completed
    elif kind == "dask":
        import distributed

        with distributed.LocalCluster(n_workers=max_workers) as cluster:
            with distributed.Client(cluster) as client:
                yield client, distributed.as_completed
    else:
        raise NotImplementedError("That kind is not implemented")


def default(obj):
    """For custom object serialization."""
    if isinstance(obj, LazyJson):
        return {"__lazy_json__": obj.file_name}
    elif isinstance(obj, Set):
        return {"__set__": True, "elements": sorted(obj)}
    raise TypeError(repr(obj) + " is not JSON serializable")


def object_hook(dct):
    """For custom object deserialization."""
    if "__lazy_json__" in dct:
        return LazyJson(dct["__lazy_json__"])
    elif "__set__" in dct:
        return set(dct["elements"])
    return dct


def dumps(obj, sort_keys=True, separators=(",", ":"), default=default,
          **kwargs):
    """Returns a JSON string from a Python object."""
    return json.dumps(
        obj,
        sort_keys=sort_keys,
        separators=separators,
        default=default,
        indent=1,
        **kwargs,
    )


def dump(obj, fp, sort_keys=True, separators=(",", ":"), default=default,
         **kwargs):
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


def loads(s, object_hook=object_hook, **kwargs):
    """Loads a string as JSON, with approriate object hooks"""
    return json.loads(s, object_hook=object_hook, **kwargs)


def load(fp, object_hook=object_hook, **kwargs):
    """Loads a file object as JSON, with appropriate object hooks."""
    return json.load(fp, object_hook=object_hook, **kwargs)


def dump_graph(gx, filename="graph.json"):
    nld = nx.node_link_data(gx)
    links = nld["links"]
    links2 = sorted(links, key=lambda x: f'{x["source"]}{x["target"]}')
    nld["links"] = links2
    with open(filename, "w") as f:
        dump(nld, f)


def load_graph(filename="graph.json"):
    with open(filename, "r") as f:
        nld = load(f)
    return nx.node_link_graph(nld)


def frozen_to_json_friendly(fz: dict, PR: LazyJson = None):
    if fz is None:
        return None
    keys = sorted(list(fz.keys()))
    d = {"keys": keys, "data": dict(fz)}
    if PR:
        d["PR"] = PR
    return d


def github_client():
    if os.environ.get('GITHUB_TOKEN'):
        return github3.login(token=os.environ['GITHUB_TOKEN'])
    else:
        return github3.login(os.environ["USERNAME"], os.environ["PASSWORD"])


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
   Although both string types and dictionaries are iterable in Python, we are treating them as not iterable in this
   method.  Thus, as_iterable(dict()) returns (dict, ) and as_iterable(string) returns (string, )
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
        return iterable_or_scalar,
    elif hasattr(iterable_or_scalar, "__iter__"):
        return iterable_or_scalar
    else:
        return iterable_or_scalar,
