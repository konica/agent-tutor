"""The cluster add-on values (deploy/helm/addons/), which every deploy reapplies (#59)."""

from pathlib import Path

import yaml

ADDONS = Path(__file__).parents[2] / "deploy/helm/addons"


def test_load_balancer_controller_keeps_its_webhook_certificate() -> None:
    # Without it every `helm upgrade` makes a new webhook CA, and the app release right after it fails with
    # "x509: certificate signed by unknown authority" until the controller pods reload the new certificate.
    values = yaml.safe_load(
        (ADDONS / "aws-load-balancer-controller.yaml").read_text(encoding="utf-8")
    )
    assert values["keepTLSSecret"] is True
