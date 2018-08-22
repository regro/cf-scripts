import os
from collections import defaultdict

from collections.abc import Set, MutableMapping
import logging
import itertools
import json

import jinja2


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
        return self.data.__iter__

    def __delitem__(self, v):
        self._load()
        del self.data[v]
        self._dump()

    def _load(self):
        if self.data is None:
            with open(self.file_name, "r") as f:
                self.data = json.load(f)

    def _dump(self):
        self._load()
        with open(self.file_name, "w") as f:
            json.dump(self.data, f)

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


def parse_meta_yaml(text):
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
    return parse(content, Config())


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
