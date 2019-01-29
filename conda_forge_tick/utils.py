import os
from collections import defaultdict

from collections.abc import Set, MutableMapping
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed

import contextlib
import logging
import itertools
import json
import re

import jinja2

pin_sep_pat = re.compile(" |>|<|=|\[")


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
                json.dump({}, f)
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
                    self.data = json.load(f)
            except FileNotFoundError:
                print(os.getcwd())
                print(os.listdir('.'))
                raise

    def _dump(self):
        self._load()
        with open(self.file_name, "w") as f:
            json.dump(self.data, f, indent=4)

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
        reqs.update(_parse_requirements(output.get("requirements", {}) or {}, **kw))
    return reqs


def _parse_requirements(req, build=True, host=True, run=True):
    """Flatten a YAML requirements section into a list of names
    """
    if not req:  # handle None as empty
        return set()
    if isinstance(req, list):  # simple list goes to both host and run
        reqlist = req if (host or run) else []
    else:
        build = req.get("build", []) or [] if build else []
        host = req.get("host", []) or [] if host else []
        run = req.get("run", []) or [] if run else []
        reqlist = build + host + run
    return set(
        pin_sep_pat.split(x)[0].lower() for x in reqlist if x is not None
    )


@contextlib.contextmanager
def executor(kind, max_workers):
    """General purpose utility to get an executor with its as_completed handler

    This allows us to easily use other executors as needed.
    """
    if kind == 'thread':
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            yield pool, as_completed
    elif kind == 'process':
        with ProcessPoolExecutor(max_workers=max_workers) as pool:
            yield pool, as_completed
    elif kind == 'dask':
        import distributed
        with distributed.LocalCluster(n_workers=max_workers) as cluster:
            with distributed.Client(cluster) as client:
                yield client, distributed.as_completed
    else:
        raise NotImplementedError('That kind is not implemented')
