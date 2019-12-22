import copy
from dataclasses import dataclass
from networkx import DiGraph
import typing
import threading


if typing.TYPE_CHECKING:
    from .migrators import Migrator


@dataclass
class GithubContext:
    github_username: str
    github_password: str
    circle_build_url: str
    github_token: typing.Optional[str] = ''
    dry_run: bool = True
    _tl: threading.local = threading.local()

    def gh(self):
        if getattr(self._tl, "gh") is None:
            import github3

            if self.github_token:
                gh = github3.login(token=self.github_token)
            else:
                gh = github3.login(self.github_username, self.github_password)
            setattr(self._tl, "gh", gh)
        return self._tl.gh


@dataclass
class MigratorsContext(GithubContext):
    graph: DiGraph = None
    smithy_version: str = ''
    pinning_version: str = ''
    prjson_dir = "pr_json"
    rever_dir: str = "./feedstocks/"
    quiet = True


@dataclass
class MigratorContext:
    parent: MigratorsContext
    migrator: "Migrator"
    _effective_graph: DiGraph = None

    @property
    def github_username(self):
        return self.parent.github_username

    @property
    def effective_graph(self):
        if self._effective_graph is None:
            gx2 = copy.deepcopy(getattr(self.migrator, "graph", self.parent.graph))

            # Prune graph to only things that need builds right now
            for node, node_attrs in self.parent.graph.nodes.items():
                attrs = node_attrs["payload"]
                if node in gx2 and self.migrator.filter(attrs):
                    gx2.remove_node(node)
            self._effective_graph = gx2
        return self._effective_graph


@dataclass
class FeedstockContext:

    package_name: str
    feedstock_name: str
    attrs: dict
