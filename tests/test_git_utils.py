from conda_forge_tick.git_utils import trim_pr_josn_keys


def test_trim_pr_json_keys():

    pr_json = {
        "ETag": "blah",
        "Last-Modified": "flah",
        "id": 435,
        "random": "string",
        "head": {"reff": "foo"},
        "base": {"repo": {"namee": "None", "name": "foo"}},
    }

    pr_json = trim_pr_josn_keys(pr_json)
    assert "random" not in pr_json
    assert pr_json["head"] == {}
    assert pr_json["base"]["repo"] == {"name": "foo"}
    assert pr_json["id"] == 435


def test_trim_pr_json_keys_src():

    src_pr_json = {
        "ETag": "blah",
        "Last-Modified": "flah",
        "id": 435,
        "random": "string",
        "head": {"reff": "foo"},
        "base": {"repo": {"namee": "None", "name": "foo"}},
    }

    pr_json = trim_pr_josn_keys({"r": None}, src_pr_json=src_pr_json)
    assert "random" not in pr_json
    assert pr_json["head"] == {}
    assert pr_json["base"]["repo"] == {"name": "foo"}
    assert pr_json["id"] == 435
    assert "r" not in pr_json
