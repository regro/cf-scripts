import click

@click.group()
def cli():
    pass

@cli.command()
def sync():
    click.echo('Syncing')


if __name__ == '__main__':
    cli()
