import json

from conda_forge_tick.config_schema import CF_TICK_SCHEMA_FILE, BotConfig


def test_config_schema_up_to_date():
    model = BotConfig()

    json_blob_from_model = json.dumps(model.model_json_schema(), indent=2) + "\n"
    assert CF_TICK_SCHEMA_FILE.exists(), (
        "The config schema file does not exist. "
        "Run `python -m conda_forge_tick.config_schema` to generate it."
    )
    json_blob_from_code = CF_TICK_SCHEMA_FILE.read_text(encoding="utf-8")
    assert json.loads(json_blob_from_model) == json.loads(json_blob_from_code), (
        "The config schema file is out of date. "
        "Run `python -m conda_forge_tick.config_schema` to regenerate it."
    )
