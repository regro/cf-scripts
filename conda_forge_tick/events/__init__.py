from ..cli import CliContext


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

    Raises
    ------
    RuntimeError
        If the event is not recognized.
    """
    if event == "pr":
        from .pr_events import react_to_pr

        react_to_pr(uid, dry_run=ctx.dry_run)
    elif event == "push":
        from .push_events import react_to_push

        react_to_push(uid, dry_run=ctx.dry_run)
    else:
        raise RuntimeError(f"Event `{event}` w/ uid `{uid}` not recognized!")
