import aws_cdk as cdk
from aws_cdk.assertions import Template

from smart_tutor_infra.stacks.config import ConfigStack


def test_file_limits_are_ssm_parameters() -> None:
    template = Template.from_stack(ConfigStack(cdk.App(), "Config"))

    template.has_resource_properties("AWS::SSM::Parameter", {"Name": "/smart-tutor/max-upload-mb", "Value": "50"})
    template.has_resource_properties("AWS::SSM::Parameter", {"Name": "/smart-tutor/max-pages", "Value": "500"})
