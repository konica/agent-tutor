"""Monthly cost budget for the account with email alerts (#55 decided the amount and recipients)."""

from collections.abc import Sequence
from typing import Any

import aws_cdk as cdk
from aws_cdk import aws_budgets as budgets
from constructs import Construct


class BudgetsStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        budget_name: str,
        monthly_usd: float,
        alert_emails: Sequence[str],
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        subscribers = [budgets.CfnBudget.SubscriberProperty(subscription_type="EMAIL", address=a) for a in alert_emails]

        def alert(threshold: int, notification_type: str) -> budgets.CfnBudget.NotificationWithSubscribersProperty:
            return budgets.CfnBudget.NotificationWithSubscribersProperty(
                notification=budgets.CfnBudget.NotificationProperty(
                    notification_type=notification_type,
                    comparison_operator="GREATER_THAN",
                    threshold=threshold,
                    threshold_type="PERCENTAGE",
                ),
                subscribers=subscribers,
            )

        budgets.CfnBudget(
            self,
            "MonthlyBudget",
            budget=budgets.CfnBudget.BudgetDataProperty(
                budget_name=budget_name,
                budget_type="COST",
                time_unit="MONTHLY",
                budget_limit=budgets.CfnBudget.SpendProperty(amount=monthly_usd, unit="USD"),
            ),
            notifications_with_subscribers=[alert(80, "ACTUAL"), alert(100, "FORECASTED")],
        )
