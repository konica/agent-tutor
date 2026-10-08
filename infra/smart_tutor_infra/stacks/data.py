"""RDS PostgreSQL 17 + pgvector in the private subnets; the database credentials in Secrets Manager (#57).

One instance holds two databases, `smart_tutor` (app) and `keycloak`, each owned by its own role. CloudFormation cannot
run SQL, so the Helm release creates the roles and databases in a hook Job (deploy/helm/smart-tutor/files/
db-bootstrap.sql) with the master secret. Only pods (the EKS cluster security group) reach the instance.
"""

from typing import Any

import aws_cdk as cdk
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_rds as rds
from aws_cdk import aws_secretsmanager as secretsmanager
from constructs import Construct

POSTGRES_PORT = 5432
# Construct id → (secret name, role and database name). The db-bootstrap Job and the charts read these secrets.
DATABASE_USERS = {
    "App": ("smart-tutor/db/app", "smart_tutor"),
    "Keycloak": ("smart-tutor/db/keycloak", "keycloak"),
}


class DataStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        vpc: ec2.IVpc,
        cluster_security_group_id: str,
        name_prefix: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        security_group = ec2.SecurityGroup(
            self,
            "DatabaseSecurityGroup",
            vpc=vpc,
            description="RDS: PostgreSQL from EKS pods only",
            allow_all_outbound=False,
        )
        security_group.add_ingress_rule(
            ec2.Peer.security_group_id(cluster_security_group_id), ec2.Port.tcp(POSTGRES_PORT), "EKS pods"
        )
        self.instance = rds.DatabaseInstance(
            self,
            "Database",
            instance_identifier=name_prefix,
            engine=rds.DatabaseInstanceEngine.postgres(version=rds.PostgresEngineVersion.VER_17),
            # Not db.t4g.micro: RDS offers it for PostgreSQL 16/17 in no us-east-1 AZ (CREATE_FAILED, 2026-10-08).
            # db.t3.micro has the same 2 vCPU / 1 GiB and is orderable in both VPC AZs.
            instance_type=ec2.InstanceType.of(ec2.InstanceClass.BURSTABLE3, ec2.InstanceSize.MICRO),
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            security_groups=[security_group],
            port=POSTGRES_PORT,
            credentials=rds.Credentials.from_generated_secret("postgres", secret_name="smart-tutor/rds/master"),
            allocated_storage=20,
            max_allocated_storage=100,
            storage_type=rds.StorageType.GP3,
            storage_encrypted=True,
            multi_az=False,
            publicly_accessible=False,
            backup_retention=cdk.Duration.days(7),
            # Teardown (pilot-deploy.md) must work while the pilot is idle; the snapshot keeps the data.
            deletion_protection=False,
            removal_policy=cdk.RemovalPolicy.SNAPSHOT,
        )
        for construct_name, (secret_name, user) in DATABASE_USERS.items():
            secretsmanager.Secret(
                self,
                f"{construct_name}DatabaseSecret",
                secret_name=secret_name,
                description=f"PostgreSQL role and database {user} on {name_prefix}",
                generate_secret_string=secretsmanager.SecretStringGenerator(
                    secret_string_template=self.to_json_string(
                        {
                            "username": user,
                            "dbname": user,
                            "host": self.instance.db_instance_endpoint_address,
                            "port": self.instance.db_instance_endpoint_port,
                        }
                    ),
                    generate_string_key="password",
                    exclude_punctuation=True,  # safe in a JDBC URL and a psql variable
                    password_length=32,
                ),
            )
        cdk.CfnOutput(self, "DatabaseEndpoint", value=self.instance.db_instance_endpoint_address)
