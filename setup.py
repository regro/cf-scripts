from setuptools import setup, find_packages

setup(
    name="conda-forge-tick",
    version="0.0.1",
    description="",
    author="Conda-forge-tick Development Team",
    author_email="",
    scripts=["scripts/conda-forge-tick"],
    url="https://github.com/regro/cf-scripts",
    include_package_data=True,
    packages=find_packages(exclude=['tests', 'scripts', 'doc']),
    package_data={"conda_forge_tick": ["*.xsh"]},
    package_dir={"conda_forge_tick": "conda_forge_tick"},
    zip_safe=False,
)
