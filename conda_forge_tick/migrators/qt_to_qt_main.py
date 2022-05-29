from conda_forge_tick.migrators.core import Replacement


class QtQtMainMigrator(Replacement):
    migrator_version = 0

    def __init__(self, pr_limit: int = 0):
        rationale = (
            "We have split qt into two packages for ease of compilation. "
            "If you require qt-webengine, you should add it to your dependencies"
        )
        super.__init__(
            old_pkg="qt",
            new_pkg="qt-main",
            rationale=rationale,
            pr_limit=pr_limit,
        )
