from ..cli import CliContext
from .pr_events import react_to_pr


def react_to_event(ctx: CliContext, event: str, uid: str) -> None:
    """React to an event.

    Parameters
    ----------
    ctx : CliContext
        The CLI context object with the debug and dry_run attributes.
    event : str
        The event to react to. One of "pr" or "push".
    uid : str
        The unique identifier of the event. It is the PR id for PR events or
        the feedstock name for push events.
    """
    if event == "pr":
        react_to_pr(uid, dry_run=ctx.dry_run)
    else:
        raise RuntimeError(f"Event `{event}` w/ uid `{uid}` not recognized!")
