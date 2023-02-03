import typer
from time import time

app = typer.Typer()


from contextlib import contextmanager


@contextmanager
def timer():
    start = time()
    try:
        yield
    finally:
        # Code to release resource, e.g.:
        finish = time()
        print(f"Elapsed time: {finish - start:.2f} seconds")


@app.command()
def deploy(dry_run: bool = False):
    with timer():
        from conda_forge_tick.deploy import deploy

        deploy(dry_run=dry_run)


@app.command()
def all_feedstocks():
    with timer():
        from conda_forge_tick.all_feedstocks import main

        main()


@app.command()
def make_graph(debug: bool = False):
    with timer():
        from conda_forge_tick.make_graph import main

        main(debug)


@app.command()
def update_upstream_versions(debug: bool = False):
    with timer():
        from conda_forge_tick.update_upstream_versions import main

        main(debug)


@app.command()
def auto_tick(
    dry_run: bool = False,
    debug: bool = False,
    github_username: str = "",
    github_password: str = "",
    github_token: str = "",
):
    with timer():
        from conda_forge_tick.auto_tick import main

        main(
            dry_run=dry_run,
            debug=debug,
            github_username=github_username,
            github_password=github_password,
            github_token=github_token,
        )


@app.command()
def status_report():
    with timer():
        from conda_forge_tick.status_report import main

        main()


@app.command()
def audit():
    with timer():
        from conda_forge_tick.audit import main

        main()


@app.command()
def update_prs(dry_run: bool = False):
    with timer():
        from conda_forge_tick.update_prs import main

        main(dry_run=dry_run)


@app.command()
def mappings(
    cf_graph: Path = typer.Argument(..., exists=True, help="Path to graph.json file"),
):
    with timer():
        from conda_forge_tick.mappings import main

        main(cf_graph)


if __name__ == "__main__":
    app()
