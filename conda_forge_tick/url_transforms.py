from itertools import permutations

EXTS = [".tar.gz", ".zip", ".tar", ".tar.bz2", ".tar.xz", ".tgz"]


def _ext_munger(url):
    for old_ext, new_ext in permutations(EXTS, 2):
        if url.endswith(old_ext):
            yield url[: -len(old_ext)] + new_ext


def _jinja2_munger_factory(field):
    def _jinja_munger(url):
        # the '<' are from ruamel.yaml.jinja2
        # if the variable is '{{version}}'
        # it comes out in the url as '<{version}}' after
        # parsing so we allow for that too
        for spc in ["", " "]:
            fs = field + spc
            curr = "<{%s}}" % fs
            not_curr = "<<{%s}}" % fs
            new = "{{ %s }}" % field
            if curr in url and not_curr not in url:
                yield url.replace(curr, new)

        for spc in ["", " "]:
            fs = field + spc
            curr = "<<{%s}}" % fs
            new = "{{ %s }}" % field
            if curr in url:
                yield url.replace(curr, new)

        for spc in ["", " "]:
            fs = field + spc
            curr = "{{%s}}" % fs
            new = "{{ %s }}" % field
            if curr in url:
                yield url.replace(curr, new)

    return _jinja_munger


def _v_munger(url):
    for vhave, vrep in permutations(["v{{ v", "{{ v"]):
        if vhave in url and (vrep in vhave or vrep not in url):
            yield url.replace(vhave, vrep)


def _pypi_domain_munger(url):
    if url.startswith("https://pypi.io"):
        yield "https://files.pythonhosted.org" + url[len("https://pypi.io") :]


def _pypi_munger(url):
    names = [
        "{{ name }}",
        (
            "{{ name.replace('_', '-') }}",
            '{{ name.replace("_", "-") }}',
            "{{ name.replace('_','-') }}",
            '{{ name.replace("_","-") }}',
            "{{ name|replace('_', '-') }}",
            '{{ name|replace("_", "-") }}',
            "{{ name|replace('_','-') }}",
            '{{ name|replace("_","-") }}',
        ),
    ]
    if "/pypi." in url:
        burl, eurl = url.rsplit("/", 1)
        for vhave, vrep in permutations(names, 2):
            if isinstance(vhave, tuple):
                for _v in vhave:
                    if _v in eurl:
                        yield burl + "/" + eurl.replace(_v, vrep)
            elif vhave in eurl:
                assert isinstance(vrep, tuple)
                yield burl + "/" + eurl.replace(vhave, vrep[0])


def _github_munger(url):
    names = ["/releases/download/v{{ version }}/", "/archive/"]
    if "github.com" in url:
        burl, eurl = url.rsplit("/", 1)
        burl = burl + "/"
        for ghave, grep in permutations(names, 2):
            if ghave in url:
                if ghave == "/archive/":
                    yield burl.replace(ghave, grep) + "{{ name }}-" + eurl
                else:
                    yield (burl.replace(ghave, grep) + eurl.replace("{{ name }}-", ""))


def _gen_new_urls(url, mungers):
    if len(mungers) > 0:
        # ignore last one
        yield from _gen_new_urls(url, mungers[:-1])

        # use it and continue
        for new_url in mungers[-1](url):
            yield from _gen_new_urls(new_url, mungers[:-1])
    else:
        yield url


def gen_transformed_urls(url):
    """Generate transformed urls for common variants.

    Parameters
    ----------
    url : str
        The URL to transform.
    """
    yield from _gen_new_urls(
        url,
        [
            _ext_munger,
            _v_munger,
            _jinja2_munger_factory("name"),
            _jinja2_munger_factory("version"),
            _jinja2_munger_factory("name[0]"),
            _pypi_munger,
            _pypi_domain_munger,
            _github_munger,
        ],
    )
