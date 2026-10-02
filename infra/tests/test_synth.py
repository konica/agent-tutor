import aws_cdk as cdk

from smart_tutor_infra.app_stacks import build_app


def test_all_stacks_synthesize_in_us_east_1() -> None:
    app = cdk.App()

    stacks = build_app(app)
    assembly = app.synth()

    assert len(stacks) == 7
    assert {s.region for s in stacks} == {"us-east-1"}
    assert len(assembly.stacks) == 7
