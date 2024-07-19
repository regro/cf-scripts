import os

import pytest

from conda_forge_tick.url_transforms import gen_transformed_urls


def test_url_transform_jinja():
    urls = set(list(gen_transformed_urls("{{version}}")))
    assert urls == {"v{{ version }}", "{{ version }}", "{{version}}"}

    urls = set(list(gen_transformed_urls("<{version}}")))
    assert urls == {"v{{ version }}", "{{ version }}", "<{version}}"}

    urls = set(list(gen_transformed_urls("<<{version}}")))
    assert urls == {"v{{ version }}", "{{ version }}", "<<{version}}"}


def test_url_transform_jinja_mixed():
    urls = set(list(gen_transformed_urls("{{version}}/{{name }}")))
    assert urls == {
        "v{{ version }}/{{ name }}",
        "v{{ version }}/{{name }}",
        "{{ version }}/{{ name }}",
        "{{ version }}/{{name }}",
        "{{version}}/{{name }}",
        "{{version}}/{{ name }}",
    }

    urls = set(list(gen_transformed_urls("{{version}}/<{name}}")))
    assert urls == {
        "v{{ version }}/{{ name }}",
        "v{{ version }}/<{name}}",
        "{{ version }}/{{ name }}",
        "{{ version }}/<{name}}",
        "{{version}}/<{name}}",
        "{{version}}/{{ name }}",
    }


def test_url_transform_version():
    urls = set(list(gen_transformed_urls("{{ version }}")))
    assert urls == {"v{{ version }}", "{{ version }}"}


def test_url_transform_exts():
    urls = set(list(gen_transformed_urls("blah.tar.gz")))
    assert urls == {
        "blah.tar.gz",
        "blah.tgz",
        "blah.tar",
        "blah.tar.bz2",
        "blah.zip",
        "blah.tar.xz",
    }


def test_rul_transforms_pypi_name():
    urls = set(
        list(
            gen_transformed_urls(
                "https://pypi.io/packages/source/{{ name[0] }}/{{ name }}"
                "/dash_extensions-{{ version }}.tar.gz",
            ),
        ),
    )
    assert any("{{ name }}-{{ version }}" in os.path.basename(url) for url in urls)


def test_url_transform_pypi():
    urls = set(list(gen_transformed_urls("https://pypi.io/{{ name }}/{{ name }}-barf")))
    assert urls == {
        "https://files.pythonhosted.org/{{ name }}/{{ name }}-barf",
        "https://files.pythonhosted.org/{{ name }}/{{ name.replace('-', '_') }}-barf",
        "https://files.pythonhosted.org/{{ name }}/{{ name.replace('_', '-') }}-barf",
        "https://pypi.io/{{ name }}/{{ name }}-barf",
        "https://pypi.io/{{ name }}/{{ name.replace('-', '_') }}-barf",
        "https://pypi.io/{{ name }}/{{ name.replace('_', '-') }}-barf",
    }

    urls = set(
        list(
            gen_transformed_urls(
                "https://pypi.io/{{ name }}/{{ name.replace('_', '-') }}-barf",
            ),
        ),
    )
    assert urls == {
        "https://files.pythonhosted.org/{{ name }}/{{ name }}-barf",
        "https://files.pythonhosted.org/{{ name }}/{{ name.replace('_', '-') }}-barf",
        "https://pypi.io/{{ name }}/{{ name }}-barf",
        "https://pypi.io/{{ name }}/{{ name.replace('_', '-') }}-barf",
    }

    urls = set(
        list(
            gen_transformed_urls(
                "https://pypi.io/{{ name }}/{{ name.replace('_','-') }}-barf",
            ),
        ),
    )
    assert urls == {
        "https://files.pythonhosted.org/{{ name }}/{{ name }}-barf",
        "https://files.pythonhosted.org/{{ name }}/{{ name.replace('_','-') }}-barf",
        "https://pypi.io/{{ name }}/{{ name }}-barf",
        "https://pypi.io/{{ name }}/{{ name.replace('_','-') }}-barf",
    }

    urls = set(
        list(
            gen_transformed_urls(
                "https://pypi.io/{{ name }}/{{ name|replace('_','-') }}-barf",
            ),
        ),
    )
    assert urls == {
        "https://files.pythonhosted.org/{{ name }}/{{ name }}-barf",
        "https://files.pythonhosted.org/{{ name }}/{{ name|replace('_','-') }}-barf",
        "https://pypi.io/{{ name }}/{{ name }}-barf",
        "https://pypi.io/{{ name }}/{{ name|replace('_','-') }}-barf",
    }

    urls = set(
        list(
            gen_transformed_urls(
                'https://pypi.io/{{ name }}/{{ name.replace("_", "-") }}-barf',
            ),
        ),
    )
    assert urls == {
        "https://files.pythonhosted.org/{{ name }}/{{ name }}-barf",
        'https://files.pythonhosted.org/{{ name }}/{{ name.replace("_", "-") }}-barf',
        "https://pypi.io/{{ name }}/{{ name }}-barf",
        'https://pypi.io/{{ name }}/{{ name.replace("_", "-") }}-barf',
    }


def test_url_transform_github():
    urls = set(
        list(
            gen_transformed_urls(
                "https://github.com/releases/download/"
                "v{{ version }}/{{ name }}/{{ name }}-{{ version }}",
            ),
        ),
    )
    assert urls == {
        "https://github.com/releases/download/v{{ version }}/"
        "{{ name }}/{{ name }}-{{ version }}",
        "https://github.com/releases/download/{{ version }}/"
        "{{ name }}/{{ name }}-{{ version }}",
        "https://github.com/archive/{{ name }}/v{{ version }}",
        "https://github.com/archive/{{ name }}/{{ version }}",
    }
    pass


def test_url_transform_complicated():
    urls = set(list(gen_transformed_urls("blah-{{ version }}.tar.gz")))
    assert urls == {
        "blah-{{ version }}.tar.gz",
        "blah-{{ version }}.tgz",
        "blah-{{ version }}.tar",
        "blah-{{ version }}.tar.bz2",
        "blah-{{ version }}.zip",
        "blah-{{ version }}.tar.xz",
        "blah-v{{ version }}.tar.gz",
        "blah-v{{ version }}.tgz",
        "blah-v{{ version }}.tar",
        "blah-v{{ version }}.tar.bz2",
        "blah-v{{ version }}.zip",
        "blah-v{{ version }}.tar.xz",
    }


def test_url_transform_complicated_pypi():
    urls = set(
        list(
            gen_transformed_urls(
                "https://pypi.io/{{ name }}/"
                "{{ name.replace('_', '-') }}-{{ version }}.tgz",
            ),
        ),
    )
    assert urls == {
        "https://files.pythonhosted.org/{{ name }}"
        "/{{ name.replace('_', '-') }}-{{ version }}.tgz",
        "https://files.pythonhosted.org/{{ name }}"
        "/{{ name.replace('_', '-') }}-{{ version }}.tar.gz",
        "https://files.pythonhosted.org/{{ name }}"
        "/{{ name.replace('_', '-') }}-{{ version }}.zip",
        "https://files.pythonhosted.org/{{ name }}"
        "/{{ name.replace('_', '-') }}-{{ version }}.tar",
        "https://files.pythonhosted.org/{{ name }}"
        "/{{ name.replace('_', '-') }}-{{ version }}.tar.bz2",
        "https://files.pythonhosted.org/{{ name }}"
        "/{{ name.replace('_', '-') }}-{{ version }}.tar.xz",
        "https://files.pythonhosted.org/{{ name }}"
        "/{{ name.replace('_', '-') }}-v{{ version }}.tgz",
        "https://files.pythonhosted.org/{{ name }}"
        "/{{ name.replace('_', '-') }}-v{{ version }}.tar.gz",
        "https://files.pythonhosted.org/{{ name }}"
        "/{{ name.replace('_', '-') }}-v{{ version }}.zip",
        "https://files.pythonhosted.org/{{ name }}"
        "/{{ name.replace('_', '-') }}-v{{ version }}.tar",
        "https://files.pythonhosted.org/{{ name }}"
        "/{{ name.replace('_', '-') }}-v{{ version }}.tar.bz2",
        "https://files.pythonhosted.org/{{ name }}"
        "/{{ name.replace('_', '-') }}-v{{ version }}.tar.xz",
        "https://files.pythonhosted.org/{{ name }}/{{ name }}-{{ version }}.tgz",
        "https://files.pythonhosted.org/{{ name }}/{{ name }}-{{ version }}.tar.gz",
        "https://files.pythonhosted.org/{{ name }}/{{ name }}-{{ version }}.zip",
        "https://files.pythonhosted.org/{{ name }}/{{ name }}-{{ version }}.tar",
        "https://files.pythonhosted.org/{{ name }}/{{ name }}-{{ version }}.tar.bz2",
        "https://files.pythonhosted.org/{{ name }}/{{ name }}-{{ version }}.tar.xz",
        "https://files.pythonhosted.org/{{ name }}/{{ name }}-v{{ version }}.tgz",
        "https://files.pythonhosted.org/{{ name }}/{{ name }}-v{{ version }}.tar.gz",
        "https://files.pythonhosted.org/{{ name }}/{{ name }}-v{{ version }}.zip",
        "https://files.pythonhosted.org/{{ name }}/{{ name }}-v{{ version }}.tar",
        "https://files.pythonhosted.org/{{ name }}/{{ name }}-v{{ version }}.tar.bz2",
        "https://files.pythonhosted.org/{{ name }}/{{ name }}-v{{ version }}.tar.xz",
        "https://pypi.io/{{ name }}/{{ name.replace('_', '-') }}-{{ version }}.tgz",
        "https://pypi.io/{{ name }}/{{ name.replace('_', '-') }}-{{ version }}.tar.gz",
        "https://pypi.io/{{ name }}/{{ name.replace('_', '-') }}-{{ version }}.zip",
        "https://pypi.io/{{ name }}/{{ name.replace('_', '-') }}-{{ version }}.tar",
        "https://pypi.io/{{ name }}/{{ name.replace('_', '-') }}-{{ version }}.tar.bz2",
        "https://pypi.io/{{ name }}/{{ name.replace('_', '-') }}-{{ version }}.tar.xz",
        "https://pypi.io/{{ name }}/{{ name.replace('_', '-') }}-v{{ version }}.tgz",
        "https://pypi.io/{{ name }}/{{ name.replace('_', '-') }}-v{{ version }}.tar.gz",
        "https://pypi.io/{{ name }}/{{ name.replace('_', '-') }}-v{{ version }}.zip",
        "https://pypi.io/{{ name }}/{{ name.replace('_', '-') }}-v{{ version }}.tar",
        "https://pypi.io/{{ name }}/{{ name.replace('_', '-') }}-v{{ version }}.tar.bz2",  # noqa
        "https://pypi.io/{{ name }}/{{ name.replace('_', '-') }}-v{{ version }}.tar.xz",
        "https://pypi.io/{{ name }}/{{ name }}-{{ version }}.tgz",
        "https://pypi.io/{{ name }}/{{ name }}-{{ version }}.tar.gz",
        "https://pypi.io/{{ name }}/{{ name }}-{{ version }}.zip",
        "https://pypi.io/{{ name }}/{{ name }}-{{ version }}.tar",
        "https://pypi.io/{{ name }}/{{ name }}-{{ version }}.tar.bz2",
        "https://pypi.io/{{ name }}/{{ name }}-{{ version }}.tar.xz",
        "https://pypi.io/{{ name }}/{{ name }}-v{{ version }}.tgz",
        "https://pypi.io/{{ name }}/{{ name }}-v{{ version }}.tar.gz",
        "https://pypi.io/{{ name }}/{{ name }}-v{{ version }}.zip",
        "https://pypi.io/{{ name }}/{{ name }}-v{{ version }}.tar",
        "https://pypi.io/{{ name }}/{{ name }}-v{{ version }}.tar.bz2",
        "https://pypi.io/{{ name }}/{{ name }}-v{{ version }}.tar.xz",
    }


def test_url_transform_complicated_github():
    urls = set(
        list(
            gen_transformed_urls(
                "https://github.com/archive/{{ name }}/v{{ version }}.tgz",
            ),
        ),
    )
    assert urls == {
        "https://github.com/archive/{{ name }}/v{{ version }}.tgz",
        "https://github.com/archive/{{ name }}/v{{ version }}.tar.gz",
        "https://github.com/archive/{{ name }}/v{{ version }}.zip",
        "https://github.com/archive/{{ name }}/v{{ version }}.tar",
        "https://github.com/archive/{{ name }}/v{{ version }}.tar.bz2",
        "https://github.com/archive/{{ name }}/v{{ version }}.tar.xz",
        "https://github.com/archive/{{ name }}/{{ version }}.tgz",
        "https://github.com/archive/{{ name }}/{{ version }}.tar.gz",
        "https://github.com/archive/{{ name }}/{{ version }}.zip",
        "https://github.com/archive/{{ name }}/{{ version }}.tar",
        "https://github.com/archive/{{ name }}/{{ version }}.tar.bz2",
        "https://github.com/archive/{{ name }}/{{ version }}.tar.xz",
        "https://github.com/releases/download/v{{ version }}/{{ name }}/{{ name }}-v{{ version }}.tgz",  # noqa
        "https://github.com/releases/download/v{{ version }}/{{ name }}/{{ name }}-v{{ version }}.tar.gz",  # noqa
        "https://github.com/releases/download/v{{ version }}/{{ name }}/{{ name }}-v{{ version }}.zip",  # noqa
        "https://github.com/releases/download/v{{ version }}/{{ name }}/{{ name }}-v{{ version }}.tar",  # noqa
        "https://github.com/releases/download/v{{ version }}/{{ name }}/{{ name }}-v{{ version }}.tar.bz2",  # noqa
        "https://github.com/releases/download/v{{ version }}/{{ name }}/{{ name }}-v{{ version }}.tar.xz",  # noqa
        "https://github.com/releases/download/{{ version }}/{{ name }}/{{ name }}-{{ version }}.tgz",  # noqa
        "https://github.com/releases/download/{{ version }}/{{ name }}/{{ name }}-{{ version }}.tar.gz",  # noqa
        "https://github.com/releases/download/{{ version }}/{{ name }}/{{ name }}-{{ version }}.zip",  # noqa
        "https://github.com/releases/download/{{ version }}/{{ name }}/{{ name }}-{{ version }}.tar",  # noqa
        "https://github.com/releases/download/{{ version }}/{{ name }}/{{ name }}-{{ version }}.tar.bz2",  # noqa
        "https://github.com/releases/download/{{ version }}/{{ name }}/{{ name }}-{{ version }}.tar.xz",  # noqa
    }


TRANSFORM_URLS = {
    # a la https://github.com/conda-forge/packageurl-python-feedstock/pull/22
    """
https://pypi.io/packages/source/p/packageurl-python/packageurl-python-{{ version }}.tar.gz
""".strip(): r"""
https://files.pythonhosted.org/packages/source/p/packageurl-python/packageurl_python-{{ version }}.tar
https://files.pythonhosted.org/packages/source/p/packageurl-python/packageurl_python-{{ version }}.tar.bz2
https://files.pythonhosted.org/packages/source/p/packageurl-python/packageurl_python-{{ version }}.tar.gz
https://files.pythonhosted.org/packages/source/p/packageurl-python/packageurl_python-{{ version }}.tar.xz
https://files.pythonhosted.org/packages/source/p/packageurl-python/packageurl_python-{{ version }}.tgz
https://files.pythonhosted.org/packages/source/p/packageurl-python/packageurl_python-{{ version }}.zip
https://files.pythonhosted.org/packages/source/p/packageurl-python/packageurl_python-v{{ version }}.tar
https://files.pythonhosted.org/packages/source/p/packageurl-python/packageurl_python-v{{ version }}.tar.bz2
https://files.pythonhosted.org/packages/source/p/packageurl-python/packageurl_python-v{{ version }}.tar.gz
https://files.pythonhosted.org/packages/source/p/packageurl-python/packageurl_python-v{{ version }}.tar.xz
https://files.pythonhosted.org/packages/source/p/packageurl-python/packageurl_python-v{{ version }}.tgz
https://files.pythonhosted.org/packages/source/p/packageurl-python/packageurl_python-v{{ version }}.zip
https://files.pythonhosted.org/packages/source/p/packageurl-python/packageurl-python-{{ version }}.tar
https://files.pythonhosted.org/packages/source/p/packageurl-python/packageurl-python-{{ version }}.tar.bz2
https://files.pythonhosted.org/packages/source/p/packageurl-python/packageurl-python-{{ version }}.tar.gz
https://files.pythonhosted.org/packages/source/p/packageurl-python/packageurl-python-{{ version }}.tar.xz
https://files.pythonhosted.org/packages/source/p/packageurl-python/packageurl-python-{{ version }}.tgz
https://files.pythonhosted.org/packages/source/p/packageurl-python/packageurl-python-{{ version }}.zip
https://files.pythonhosted.org/packages/source/p/packageurl-python/packageurl-python-v{{ version }}.tar
https://files.pythonhosted.org/packages/source/p/packageurl-python/packageurl-python-v{{ version }}.tar.bz2
https://files.pythonhosted.org/packages/source/p/packageurl-python/packageurl-python-v{{ version }}.tar.gz
https://files.pythonhosted.org/packages/source/p/packageurl-python/packageurl-python-v{{ version }}.tar.xz
https://files.pythonhosted.org/packages/source/p/packageurl-python/packageurl-python-v{{ version }}.tgz
https://files.pythonhosted.org/packages/source/p/packageurl-python/packageurl-python-v{{ version }}.zip
https://pypi.io/packages/source/p/packageurl-python/packageurl_python-{{ version }}.tar
https://pypi.io/packages/source/p/packageurl-python/packageurl_python-{{ version }}.tar.bz2
https://pypi.io/packages/source/p/packageurl-python/packageurl_python-{{ version }}.tar.gz
https://pypi.io/packages/source/p/packageurl-python/packageurl_python-{{ version }}.tar.xz
https://pypi.io/packages/source/p/packageurl-python/packageurl_python-{{ version }}.tgz
https://pypi.io/packages/source/p/packageurl-python/packageurl_python-{{ version }}.zip
https://pypi.io/packages/source/p/packageurl-python/packageurl_python-v{{ version }}.tar
https://pypi.io/packages/source/p/packageurl-python/packageurl_python-v{{ version }}.tar.bz2
https://pypi.io/packages/source/p/packageurl-python/packageurl_python-v{{ version }}.tar.gz
https://pypi.io/packages/source/p/packageurl-python/packageurl_python-v{{ version }}.tar.xz
https://pypi.io/packages/source/p/packageurl-python/packageurl_python-v{{ version }}.tgz
https://pypi.io/packages/source/p/packageurl-python/packageurl_python-v{{ version }}.zip
https://pypi.io/packages/source/p/packageurl-python/packageurl-python-{{ version }}.tar
https://pypi.io/packages/source/p/packageurl-python/packageurl-python-{{ version }}.tar.bz2
https://pypi.io/packages/source/p/packageurl-python/packageurl-python-{{ version }}.tar.gz
https://pypi.io/packages/source/p/packageurl-python/packageurl-python-{{ version }}.tar.xz
https://pypi.io/packages/source/p/packageurl-python/packageurl-python-{{ version }}.tgz
https://pypi.io/packages/source/p/packageurl-python/packageurl-python-{{ version }}.zip
https://pypi.io/packages/source/p/packageurl-python/packageurl-python-v{{ version }}.tar
https://pypi.io/packages/source/p/packageurl-python/packageurl-python-v{{ version }}.tar.bz2
https://pypi.io/packages/source/p/packageurl-python/packageurl-python-v{{ version }}.tar.gz
https://pypi.io/packages/source/p/packageurl-python/packageurl-python-v{{ version }}.tar.xz
https://pypi.io/packages/source/p/packageurl-python/packageurl-python-v{{ version }}.tgz
https://pypi.io/packages/source/p/packageurl-python/packageurl-python-v{{ version }}.zip
https://files.pythonhosted.org/packages/source/p/packageurl-python/{{ name }}-{{ version }}.tar
https://files.pythonhosted.org/packages/source/p/packageurl-python/{{ name }}-{{ version }}.tar.bz2
https://files.pythonhosted.org/packages/source/p/packageurl-python/{{ name }}-{{ version }}.tar.gz
https://files.pythonhosted.org/packages/source/p/packageurl-python/{{ name }}-{{ version }}.tar.xz
https://files.pythonhosted.org/packages/source/p/packageurl-python/{{ name }}-{{ version }}.tgz
https://files.pythonhosted.org/packages/source/p/packageurl-python/{{ name }}-{{ version }}.zip
https://files.pythonhosted.org/packages/source/p/packageurl-python/{{ name }}-v{{ version }}.tar
https://files.pythonhosted.org/packages/source/p/packageurl-python/{{ name }}-v{{ version }}.tar.bz2
https://files.pythonhosted.org/packages/source/p/packageurl-python/{{ name }}-v{{ version }}.tar.gz
https://files.pythonhosted.org/packages/source/p/packageurl-python/{{ name }}-v{{ version }}.tar.xz
https://files.pythonhosted.org/packages/source/p/packageurl-python/{{ name }}-v{{ version }}.tgz
https://files.pythonhosted.org/packages/source/p/packageurl-python/{{ name }}-v{{ version }}.zip
https://files.pythonhosted.org/packages/source/p/packageurl-python/{{ name.replace('_', '-') }}-{{ version }}.tar
https://files.pythonhosted.org/packages/source/p/packageurl-python/{{ name.replace('_', '-') }}-{{ version }}.tar.bz2
https://files.pythonhosted.org/packages/source/p/packageurl-python/{{ name.replace('_', '-') }}-{{ version }}.tar.gz
https://files.pythonhosted.org/packages/source/p/packageurl-python/{{ name.replace('_', '-') }}-{{ version }}.tar.xz
https://files.pythonhosted.org/packages/source/p/packageurl-python/{{ name.replace('_', '-') }}-{{ version }}.tgz
https://files.pythonhosted.org/packages/source/p/packageurl-python/{{ name.replace('_', '-') }}-{{ version }}.zip
https://files.pythonhosted.org/packages/source/p/packageurl-python/{{ name.replace('_', '-') }}-v{{ version }}.tar
https://files.pythonhosted.org/packages/source/p/packageurl-python/{{ name.replace('_', '-') }}-v{{ version }}.tar.bz2
https://files.pythonhosted.org/packages/source/p/packageurl-python/{{ name.replace('_', '-') }}-v{{ version }}.tar.gz
https://files.pythonhosted.org/packages/source/p/packageurl-python/{{ name.replace('_', '-') }}-v{{ version }}.tar.xz
https://files.pythonhosted.org/packages/source/p/packageurl-python/{{ name.replace('_', '-') }}-v{{ version }}.tgz
https://files.pythonhosted.org/packages/source/p/packageurl-python/{{ name.replace('_', '-') }}-v{{ version }}.zip
https://files.pythonhosted.org/packages/source/p/packageurl-python/{{ name.replace('-', '_') }}-{{ version }}.tar
https://files.pythonhosted.org/packages/source/p/packageurl-python/{{ name.replace('-', '_') }}-{{ version }}.tar.bz2
https://files.pythonhosted.org/packages/source/p/packageurl-python/{{ name.replace('-', '_') }}-{{ version }}.tar.gz
https://files.pythonhosted.org/packages/source/p/packageurl-python/{{ name.replace('-', '_') }}-{{ version }}.tar.xz
https://files.pythonhosted.org/packages/source/p/packageurl-python/{{ name.replace('-', '_') }}-{{ version }}.tgz
https://files.pythonhosted.org/packages/source/p/packageurl-python/{{ name.replace('-', '_') }}-{{ version }}.zip
https://files.pythonhosted.org/packages/source/p/packageurl-python/{{ name.replace('-', '_') }}-v{{ version }}.tar
https://files.pythonhosted.org/packages/source/p/packageurl-python/{{ name.replace('-', '_') }}-v{{ version }}.tar.bz2
https://files.pythonhosted.org/packages/source/p/packageurl-python/{{ name.replace('-', '_') }}-v{{ version }}.tar.gz
https://files.pythonhosted.org/packages/source/p/packageurl-python/{{ name.replace('-', '_') }}-v{{ version }}.tar.xz
https://files.pythonhosted.org/packages/source/p/packageurl-python/{{ name.replace('-', '_') }}-v{{ version }}.tgz
https://files.pythonhosted.org/packages/source/p/packageurl-python/{{ name.replace('-', '_') }}-v{{ version }}.zip
https://pypi.io/packages/source/p/packageurl-python/{{ name }}-{{ version }}.tar
https://pypi.io/packages/source/p/packageurl-python/{{ name }}-{{ version }}.tar.bz2
https://pypi.io/packages/source/p/packageurl-python/{{ name }}-{{ version }}.tar.gz
https://pypi.io/packages/source/p/packageurl-python/{{ name }}-{{ version }}.tar.xz
https://pypi.io/packages/source/p/packageurl-python/{{ name }}-{{ version }}.tgz
https://pypi.io/packages/source/p/packageurl-python/{{ name }}-{{ version }}.zip
https://pypi.io/packages/source/p/packageurl-python/{{ name }}-v{{ version }}.tar
https://pypi.io/packages/source/p/packageurl-python/{{ name }}-v{{ version }}.tar.bz2
https://pypi.io/packages/source/p/packageurl-python/{{ name }}-v{{ version }}.tar.gz
https://pypi.io/packages/source/p/packageurl-python/{{ name }}-v{{ version }}.tar.xz
https://pypi.io/packages/source/p/packageurl-python/{{ name }}-v{{ version }}.tgz
https://pypi.io/packages/source/p/packageurl-python/{{ name }}-v{{ version }}.zip
https://pypi.io/packages/source/p/packageurl-python/{{ name.replace('_', '-') }}-{{ version }}.tar
https://pypi.io/packages/source/p/packageurl-python/{{ name.replace('_', '-') }}-{{ version }}.tar.bz2
https://pypi.io/packages/source/p/packageurl-python/{{ name.replace('_', '-') }}-{{ version }}.tar.gz
https://pypi.io/packages/source/p/packageurl-python/{{ name.replace('_', '-') }}-{{ version }}.tar.xz
https://pypi.io/packages/source/p/packageurl-python/{{ name.replace('_', '-') }}-{{ version }}.tgz
https://pypi.io/packages/source/p/packageurl-python/{{ name.replace('_', '-') }}-{{ version }}.zip
https://pypi.io/packages/source/p/packageurl-python/{{ name.replace('_', '-') }}-v{{ version }}.tar
https://pypi.io/packages/source/p/packageurl-python/{{ name.replace('_', '-') }}-v{{ version }}.tar.bz2
https://pypi.io/packages/source/p/packageurl-python/{{ name.replace('_', '-') }}-v{{ version }}.tar.gz
https://pypi.io/packages/source/p/packageurl-python/{{ name.replace('_', '-') }}-v{{ version }}.tar.xz
https://pypi.io/packages/source/p/packageurl-python/{{ name.replace('_', '-') }}-v{{ version }}.tgz
https://pypi.io/packages/source/p/packageurl-python/{{ name.replace('_', '-') }}-v{{ version }}.zip
https://pypi.io/packages/source/p/packageurl-python/{{ name.replace('-', '_') }}-{{ version }}.tar
https://pypi.io/packages/source/p/packageurl-python/{{ name.replace('-', '_') }}-{{ version }}.tar.bz2
https://pypi.io/packages/source/p/packageurl-python/{{ name.replace('-', '_') }}-{{ version }}.tar.gz
https://pypi.io/packages/source/p/packageurl-python/{{ name.replace('-', '_') }}-{{ version }}.tar.xz
https://pypi.io/packages/source/p/packageurl-python/{{ name.replace('-', '_') }}-{{ version }}.tgz
https://pypi.io/packages/source/p/packageurl-python/{{ name.replace('-', '_') }}-{{ version }}.zip
https://pypi.io/packages/source/p/packageurl-python/{{ name.replace('-', '_') }}-v{{ version }}.tar
https://pypi.io/packages/source/p/packageurl-python/{{ name.replace('-', '_') }}-v{{ version }}.tar.bz2
https://pypi.io/packages/source/p/packageurl-python/{{ name.replace('-', '_') }}-v{{ version }}.tar.gz
https://pypi.io/packages/source/p/packageurl-python/{{ name.replace('-', '_') }}-v{{ version }}.tar.xz
https://pypi.io/packages/source/p/packageurl-python/{{ name.replace('-', '_') }}-v{{ version }}.tgz
https://pypi.io/packages/source/p/packageurl-python/{{ name.replace('-', '_') }}-v{{ version }}.zip
""",
    """
https://pypi.io/packages/source/p/worst-case/Worst.-Case-{{ version }}.tar.gz
""".strip(): r"""
https://files.pythonhosted.org/packages/source/p/worst-case/worst_case-{{ version }}.tar
https://files.pythonhosted.org/packages/source/p/worst-case/worst_case-{{ version }}.tar.bz2
https://files.pythonhosted.org/packages/source/p/worst-case/worst_case-{{ version }}.tar.gz
https://files.pythonhosted.org/packages/source/p/worst-case/worst_case-{{ version }}.tar.xz
https://files.pythonhosted.org/packages/source/p/worst-case/worst_case-{{ version }}.tgz
https://files.pythonhosted.org/packages/source/p/worst-case/worst_case-{{ version }}.zip
https://files.pythonhosted.org/packages/source/p/worst-case/worst_case-v{{ version }}.tar
https://files.pythonhosted.org/packages/source/p/worst-case/worst_case-v{{ version }}.tar.bz2
https://files.pythonhosted.org/packages/source/p/worst-case/worst_case-v{{ version }}.tar.gz
https://files.pythonhosted.org/packages/source/p/worst-case/worst_case-v{{ version }}.tar.xz
https://files.pythonhosted.org/packages/source/p/worst-case/worst_case-v{{ version }}.tgz
https://files.pythonhosted.org/packages/source/p/worst-case/worst_case-v{{ version }}.zip
https://files.pythonhosted.org/packages/source/p/worst-case/Worst.-Case-{{ version }}.tar
https://files.pythonhosted.org/packages/source/p/worst-case/Worst.-Case-{{ version }}.tar.bz2
https://files.pythonhosted.org/packages/source/p/worst-case/Worst.-Case-{{ version }}.tar.gz
https://files.pythonhosted.org/packages/source/p/worst-case/Worst.-Case-{{ version }}.tar.xz
https://files.pythonhosted.org/packages/source/p/worst-case/Worst.-Case-{{ version }}.tgz
https://files.pythonhosted.org/packages/source/p/worst-case/Worst.-Case-{{ version }}.zip
https://files.pythonhosted.org/packages/source/p/worst-case/Worst.-Case-v{{ version }}.tar
https://files.pythonhosted.org/packages/source/p/worst-case/Worst.-Case-v{{ version }}.tar.bz2
https://files.pythonhosted.org/packages/source/p/worst-case/Worst.-Case-v{{ version }}.tar.gz
https://files.pythonhosted.org/packages/source/p/worst-case/Worst.-Case-v{{ version }}.tar.xz
https://files.pythonhosted.org/packages/source/p/worst-case/Worst.-Case-v{{ version }}.tgz
https://files.pythonhosted.org/packages/source/p/worst-case/Worst.-Case-v{{ version }}.zip
https://pypi.io/packages/source/p/worst-case/worst_case-{{ version }}.tar
https://pypi.io/packages/source/p/worst-case/worst_case-{{ version }}.tar.bz2
https://pypi.io/packages/source/p/worst-case/worst_case-{{ version }}.tar.gz
https://pypi.io/packages/source/p/worst-case/worst_case-{{ version }}.tar.xz
https://pypi.io/packages/source/p/worst-case/worst_case-{{ version }}.tgz
https://pypi.io/packages/source/p/worst-case/worst_case-{{ version }}.zip
https://pypi.io/packages/source/p/worst-case/worst_case-v{{ version }}.tar
https://pypi.io/packages/source/p/worst-case/worst_case-v{{ version }}.tar.bz2
https://pypi.io/packages/source/p/worst-case/worst_case-v{{ version }}.tar.gz
https://pypi.io/packages/source/p/worst-case/worst_case-v{{ version }}.tar.xz
https://pypi.io/packages/source/p/worst-case/worst_case-v{{ version }}.tgz
https://pypi.io/packages/source/p/worst-case/worst_case-v{{ version }}.zip
https://pypi.io/packages/source/p/worst-case/Worst.-Case-{{ version }}.tar
https://pypi.io/packages/source/p/worst-case/Worst.-Case-{{ version }}.tar.bz2
https://pypi.io/packages/source/p/worst-case/Worst.-Case-{{ version }}.tar.gz
https://pypi.io/packages/source/p/worst-case/Worst.-Case-{{ version }}.tar.xz
https://pypi.io/packages/source/p/worst-case/Worst.-Case-{{ version }}.tgz
https://pypi.io/packages/source/p/worst-case/Worst.-Case-{{ version }}.zip
https://pypi.io/packages/source/p/worst-case/Worst.-Case-v{{ version }}.tar
https://pypi.io/packages/source/p/worst-case/Worst.-Case-v{{ version }}.tar.bz2
https://pypi.io/packages/source/p/worst-case/Worst.-Case-v{{ version }}.tar.gz
https://pypi.io/packages/source/p/worst-case/Worst.-Case-v{{ version }}.tar.xz
https://pypi.io/packages/source/p/worst-case/Worst.-Case-v{{ version }}.tgz
https://pypi.io/packages/source/p/worst-case/Worst.-Case-v{{ version }}.zip
https://files.pythonhosted.org/packages/source/p/worst-case/{{ name }}-{{ version }}.tar.bz2
https://files.pythonhosted.org/packages/source/p/worst-case/{{ name }}-{{ version }}.tar.gz
https://files.pythonhosted.org/packages/source/p/worst-case/{{ name }}-{{ version }}.tar.xz
https://files.pythonhosted.org/packages/source/p/worst-case/{{ name }}-{{ version }}.tar
https://files.pythonhosted.org/packages/source/p/worst-case/{{ name }}-{{ version }}.tgz
https://files.pythonhosted.org/packages/source/p/worst-case/{{ name }}-{{ version }}.zip
https://files.pythonhosted.org/packages/source/p/worst-case/{{ name }}-v{{ version }}.tar.bz2
https://files.pythonhosted.org/packages/source/p/worst-case/{{ name }}-v{{ version }}.tar.gz
https://files.pythonhosted.org/packages/source/p/worst-case/{{ name }}-v{{ version }}.tar.xz
https://files.pythonhosted.org/packages/source/p/worst-case/{{ name }}-v{{ version }}.tar
https://files.pythonhosted.org/packages/source/p/worst-case/{{ name }}-v{{ version }}.tgz
https://files.pythonhosted.org/packages/source/p/worst-case/{{ name }}-v{{ version }}.zip
https://pypi.io/packages/source/p/worst-case/{{ name }}-{{ version }}.tar.bz2
https://pypi.io/packages/source/p/worst-case/{{ name }}-{{ version }}.tar.gz
https://pypi.io/packages/source/p/worst-case/{{ name }}-{{ version }}.tar.xz
https://pypi.io/packages/source/p/worst-case/{{ name }}-{{ version }}.tar
https://pypi.io/packages/source/p/worst-case/{{ name }}-{{ version }}.tgz
https://pypi.io/packages/source/p/worst-case/{{ name }}-{{ version }}.zip
https://pypi.io/packages/source/p/worst-case/{{ name }}-v{{ version }}.tar.bz2
https://pypi.io/packages/source/p/worst-case/{{ name }}-v{{ version }}.tar.gz
https://pypi.io/packages/source/p/worst-case/{{ name }}-v{{ version }}.tar.xz
https://pypi.io/packages/source/p/worst-case/{{ name }}-v{{ version }}.tar
https://pypi.io/packages/source/p/worst-case/{{ name }}-v{{ version }}.tgz
https://pypi.io/packages/source/p/worst-case/{{ name }}-v{{ version }}.zip
https://files.pythonhosted.org/packages/source/p/worst-case/{{ name.replace('_', '-') }}-{{ version }}.tar.bz2
https://files.pythonhosted.org/packages/source/p/worst-case/{{ name.replace('_', '-') }}-{{ version }}.tar.gz
https://files.pythonhosted.org/packages/source/p/worst-case/{{ name.replace('_', '-') }}-{{ version }}.tar.xz
https://files.pythonhosted.org/packages/source/p/worst-case/{{ name.replace('_', '-') }}-{{ version }}.tar
https://files.pythonhosted.org/packages/source/p/worst-case/{{ name.replace('_', '-') }}-{{ version }}.tgz
https://files.pythonhosted.org/packages/source/p/worst-case/{{ name.replace('_', '-') }}-{{ version }}.zip
https://files.pythonhosted.org/packages/source/p/worst-case/{{ name.replace('_', '-') }}-v{{ version }}.tar.bz2
https://files.pythonhosted.org/packages/source/p/worst-case/{{ name.replace('_', '-') }}-v{{ version }}.tar.gz
https://files.pythonhosted.org/packages/source/p/worst-case/{{ name.replace('_', '-') }}-v{{ version }}.tar.xz
https://files.pythonhosted.org/packages/source/p/worst-case/{{ name.replace('_', '-') }}-v{{ version }}.tar
https://files.pythonhosted.org/packages/source/p/worst-case/{{ name.replace('_', '-') }}-v{{ version }}.tgz
https://files.pythonhosted.org/packages/source/p/worst-case/{{ name.replace('_', '-') }}-v{{ version }}.zip
https://files.pythonhosted.org/packages/source/p/worst-case/{{ name.replace('-', '_') }}-{{ version }}.tar.bz2
https://files.pythonhosted.org/packages/source/p/worst-case/{{ name.replace('-', '_') }}-{{ version }}.tar.gz
https://files.pythonhosted.org/packages/source/p/worst-case/{{ name.replace('-', '_') }}-{{ version }}.tar.xz
https://files.pythonhosted.org/packages/source/p/worst-case/{{ name.replace('-', '_') }}-{{ version }}.tar
https://files.pythonhosted.org/packages/source/p/worst-case/{{ name.replace('-', '_') }}-{{ version }}.tgz
https://files.pythonhosted.org/packages/source/p/worst-case/{{ name.replace('-', '_') }}-{{ version }}.zip
https://files.pythonhosted.org/packages/source/p/worst-case/{{ name.replace('-', '_') }}-v{{ version }}.tar.bz2
https://files.pythonhosted.org/packages/source/p/worst-case/{{ name.replace('-', '_') }}-v{{ version }}.tar.gz
https://files.pythonhosted.org/packages/source/p/worst-case/{{ name.replace('-', '_') }}-v{{ version }}.tar.xz
https://files.pythonhosted.org/packages/source/p/worst-case/{{ name.replace('-', '_') }}-v{{ version }}.tar
https://files.pythonhosted.org/packages/source/p/worst-case/{{ name.replace('-', '_') }}-v{{ version }}.tgz
https://files.pythonhosted.org/packages/source/p/worst-case/{{ name.replace('-', '_') }}-v{{ version }}.zip
https://pypi.io/packages/source/p/worst-case/{{ name.replace('_', '-') }}-{{ version }}.tar.bz2
https://pypi.io/packages/source/p/worst-case/{{ name.replace('_', '-') }}-{{ version }}.tar.gz
https://pypi.io/packages/source/p/worst-case/{{ name.replace('_', '-') }}-{{ version }}.tar.xz
https://pypi.io/packages/source/p/worst-case/{{ name.replace('_', '-') }}-{{ version }}.tar
https://pypi.io/packages/source/p/worst-case/{{ name.replace('_', '-') }}-{{ version }}.tgz
https://pypi.io/packages/source/p/worst-case/{{ name.replace('_', '-') }}-{{ version }}.zip
https://pypi.io/packages/source/p/worst-case/{{ name.replace('_', '-') }}-v{{ version }}.tar.bz2
https://pypi.io/packages/source/p/worst-case/{{ name.replace('_', '-') }}-v{{ version }}.tar.gz
https://pypi.io/packages/source/p/worst-case/{{ name.replace('_', '-') }}-v{{ version }}.tar.xz
https://pypi.io/packages/source/p/worst-case/{{ name.replace('_', '-') }}-v{{ version }}.tar
https://pypi.io/packages/source/p/worst-case/{{ name.replace('_', '-') }}-v{{ version }}.tgz
https://pypi.io/packages/source/p/worst-case/{{ name.replace('_', '-') }}-v{{ version }}.zip
https://pypi.io/packages/source/p/worst-case/{{ name.replace('-', '_') }}-{{ version }}.tar.bz2
https://pypi.io/packages/source/p/worst-case/{{ name.replace('-', '_') }}-{{ version }}.tar.gz
https://pypi.io/packages/source/p/worst-case/{{ name.replace('-', '_') }}-{{ version }}.tar.xz
https://pypi.io/packages/source/p/worst-case/{{ name.replace('-', '_') }}-{{ version }}.tar
https://pypi.io/packages/source/p/worst-case/{{ name.replace('-', '_') }}-{{ version }}.tgz
https://pypi.io/packages/source/p/worst-case/{{ name.replace('-', '_') }}-{{ version }}.zip
https://pypi.io/packages/source/p/worst-case/{{ name.replace('-', '_') }}-v{{ version }}.tar.bz2
https://pypi.io/packages/source/p/worst-case/{{ name.replace('-', '_') }}-v{{ version }}.tar.gz
https://pypi.io/packages/source/p/worst-case/{{ name.replace('-', '_') }}-v{{ version }}.tar.xz
https://pypi.io/packages/source/p/worst-case/{{ name.replace('-', '_') }}-v{{ version }}.tar
https://pypi.io/packages/source/p/worst-case/{{ name.replace('-', '_') }}-v{{ version }}.tgz
https://pypi.io/packages/source/p/worst-case/{{ name.replace('-', '_') }}-v{{ version }}.zip
""",
}


@pytest.mark.parametrize("url", TRANSFORM_URLS)
def test_url_transform(url):
    urls = {*gen_transformed_urls(url.strip())}
    expected = {line.strip() for line in TRANSFORM_URLS[url].strip().splitlines()}
    assert urls == expected
