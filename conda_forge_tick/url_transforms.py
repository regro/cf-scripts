import os
import re
from itertools import permutations

EXTS = [".tar.gz", ".zip", ".tar", ".tar.bz2", ".tar.xz", ".tgz"]
PYPI_URLS = ["https://pypi.io", "https://files.pythonhosted.org"]


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
    for old_d, new_d in permutations(PYPI_URLS, 2):
        yield url.replace(old_d, new_d, 1)


def _pypi_name_munger(url):
    bn = os.path.basename(url)
    dn = os.path.dirname(url)
    dist_bn = os.path.basename(os.path.dirname(url))
    is_sdist = url.endswith(".tar.gz")
    is_pypi = any(url.startswith(pypi) for pypi in PYPI_URLS)
    has_version = re.search(r"\{\{\s*version", bn)
    has_name = re.search(r"\{\{\s*name", bn)

    # try the original URL first, as a fallback (probably can't be removed?)
    yield url

    if is_pypi and has_version and not has_name:
        yield os.path.join(dn, "{{ name }}-{{ version }}.tar.gz")

    if not (is_sdist and is_pypi and has_version):
        return

    # try static PEP625 name with PEP345 distribution name (_ not -)
    patterns = [
        # fully normalized
        r"[\.\-]+",
        # older, partial normalization
        r"[\-]+",
    ]

    for pattern in patterns:
        for dist_bn_case in {dist_bn, dist_bn.lower()}:
            yield os.path.join(
                dn, "%s-{{ version }}.tar.gz" % re.sub(pattern, "_", dist_bn_case)
            )


def _pypi_munger(url):
    names = [
        [
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
        ],
        [
            "{{ name }}",
            (
                "{{ name.replace('-', '_') }}",
                '{{ name.replace("-", "_") }}',
                "{{ name.replace('-','_') }}",
                '{{ name.replace("-","_") }}',
                "{{ name|replace('-', '_') }}",
                '{{ name|replace("-", "_") }}',
                "{{ name|replace('-','_') }}",
                '{{ name|replace("-","_") }}',
            ),
        ],
    ]
    if "/pypi." in url or "/files.pythonhosted.org" in url:
        burl, eurl = url.rsplit("/", 1)
        for _names in names:
            for vhave, vrep in permutations(_names, 2):
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
    yielded = set()

    for new_url in _gen_new_urls(
        url,
        [
            _ext_munger,
            _v_munger,
            _jinja2_munger_factory("name"),
            _jinja2_munger_factory("version"),
            _jinja2_munger_factory("name[0]"),
            _pypi_munger,
            _pypi_domain_munger,
            _pypi_name_munger,
            _github_munger,
        ],
    ):
        if new_url not in yielded:
            yield new_url
            yielded.add(new_url)
