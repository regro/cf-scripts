# The cf-graph Data Model

Refer to the [main README](../../README.md) for an explanation of what this is about.

## Directory Structure

The most important parts of the graph repository looks like this:
```
cf-graph-countyfair
├── import_to_pkg_maps
│   └── ...
├── mappings/pypi
│   └── ...
├── node_attrs
│   ├── somepackage.json
│   └── ...
├── pr_info
│   ├── somepackage.json
│   └── ...
├── pr_json
│   ├── 123456789.json
│   └── ...
├── version_pr_info
│   ├── somepackage.json
│   └── ...
├── versions
│   ├── somepackage.json
│   └── ...
├── graph.json
└── ranked_hubs_authorities.json
```

For efficiency reasons, all subdirectories make use of sharded paths. For example, the path
`node_attrs/pytest.json` is actually a sharded path, and the actual path in the repository is
`node_attrs/d/9/a/8/c/pytest.json`. This is done to avoid having too many files in a single directory, allowing
git to efficiently manage the repository.

## File and Directory Descriptions

### `import_to_pkg_maps`
Undocumented.

### `mappings/pypi`
Undocumented.

### `node_attrs`
One file per conda-forge package containing metadata about the package.
Pydantic Model: `NodeAttributes` in [node_attributes.py](node_attributes.py).

### `pr_info`
Undocumented.

### `pr_json`
Undocumented.

### `version_pr_info`
Undocumented.

### `versions`
One file per conda-forge package containing upstream version update information about the package.
For some packages, this file may not exist, indicating absent upstream version update information.

### `graph.json`
The JSON representation of a [networkx](https://networkx.org/) graph. The graph is a directed graph, where the nodes
are package names and the edges are dependencies. The node list of this graph is treated as the set of all packages in
the conda-forge ecosystem. The edges are directed from the dependency package to the dependent package.

The nodes have attributes which reference JSON files in the `node_attrs` directory.

### `ranked_hubs_authorities.json`
Undocumented.
