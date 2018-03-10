from setuptools import setup

setup(
    name='conda-forge-tick',
    version='0.0.1',
    description='',
    author='Conda-forge-tick Development Team',
    author_email='',
    entry_points = {
        'console_scripts': ['conda-forge-tick=conda_forge_tick.cli:main'],
    },
    url='https://github.com/regro/cf-scripts',
    include_package_data=True,
    packages=['conda_forge_tick'],
)
