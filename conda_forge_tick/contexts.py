import copy
from dataclasses import dataclass
from networkx import DiGraph
from .migrators import Migrator

@dataclass
class GithubContext:
    github_username: str
    github_password: str
    circle_build_url: str

@dataclass
class MigratorsContext(GithubContext):
    graph: DiGraph
    smithy_version: str
    pinning_version: str
    quiet = True
    prjson_dir = 'pr_json'
    rever_dir: str = './feedstocks/'


@dataclass
class MigratorContext:
    parent: MigratorsContext
    migrator: Migrator
    _effective_graph: DiGraph = None

    @property
    def github_username(self):
        return self.parent.github_username

    @property
    def effective_graph(self):
        if self._effective_graph is None:
            gx2 = copy.deepcopy(getattr(self.migrator, 'graph', gx))

            # Prune graph to only things that need builds right now
            for node, node_attrs in self.parent.graph.nodes.items():
                attrs = node_attrs['payload']
                if node in gx2 and self.migrator.filter(attrs):
                    gx2.remove_node(node)
            self._effective_graph = gx2
        return self._effective_graph


@dataclass
class FeedstockContext:

    package_name: str
    feedstock_name: str
    attrs: dict
