import jinja2
from conda_build.metadata import parse
from conda_build.config import Config
import os
from collections import defaultdict


class NullUndefined(jinja2.Undefined):
    def __unicode__(self):
        return self._undefined_name

    def __getattr__(self, name):
        return '{}.{}'.format(self, name)

    def __getitem__(self, name):
        return '{}["{}"]'.format(self, name)


def rendered_meta_yaml(text):
    """
    :param str text: The raw text in conda-forge feedstock meta.yaml file
    :return: `str` -- the raw text rendered with Jinja variables
    """
    env = jinja2.Environment(undefined=NullUndefined)
    content = env.from_string(text).render(
                            os=os,
                            environ=defaultdict(str),
                            compiler=lambda x: x + '_compiler_stub',
                            pin_subpackage=lambda *args, **kwargs: 'subpackage_stub',
                            pin_compatible=lambda *args, **kwargs: 'compatible_pin_stub',
                            cdt=lambda *args, **kwargs: 'cdt_stub',)
    return content

def parsed_meta_yaml(text):
    """
    :param str text: The raw text in conda-forge feedstock meta.yaml file
    :return: `dict|None` -- parsed YAML dict if successful, None if not
    """
    try:
        content = rendered_meta_yaml(text)
        return parse(content, Config())
    except:
        return {}
