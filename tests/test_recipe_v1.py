from pathlib import Path

from flaky import flaky

from test_migrators import run_test_migration

from conda_forge_tick.migrators import (
    CombineV1ConditionsMigrator,
    Version,
)


YAML_PATH = Path(__file__).parent / "test_v1_yaml"

combine_conditions_migrator = Version(
    set(),
    piggy_back_migrations=[CombineV1ConditionsMigrator()],
)


@flaky
def test_combine_v1_conditions(tmp_path):
    run_test_migration(
        m=combine_conditions_migrator,
        inp=YAML_PATH.joinpath("version_pytorch.yaml").read_text(),
        output=YAML_PATH.joinpath("version_pytorch_correct.yaml").read_text(),
        prb="Dependencies have been updated if changed",
        kwargs={"new_version": "2.6.0"},
        mr_out={
            "migrator_name": Version.name,
            "migrator_version": Version.migrator_version,
            "version": "2.6.0",
        },
        tmp_path=tmp_path,
        recipe_version=1,
    )
