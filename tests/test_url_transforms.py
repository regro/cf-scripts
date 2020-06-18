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


def test_url_transform_pypi():
    urls = set(list(gen_transformed_urls("https://pypi.io/{{ name }}/{{ name }}-barf")))
    assert urls == {
        "https://pypi.io/{{ name }}/{{ name }}-barf",
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
                "https://pypi.io/{{ name }}/{{ name.replace('_', '-') }}-{{ version }}.tgz",
            ),
        ),
    )
    assert urls == {
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
