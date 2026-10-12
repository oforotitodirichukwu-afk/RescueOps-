# ADR-0001: Emulate AWS locally with Moto

**Status:** Accepted

## Context
The platform is designed around AWS-managed services (DynamoDB, SQS, S3), but it has to run with no cloud account and no cost, so anyone can clone it and run it.

LocalStack was the obvious choice. Since release 2026.03.0 it requires an account auth token to start, which adds friction for reviewers and CI.

## Decision
Use [Moto](https://github.com/getmoto/moto) (Apache-2.0):
- **Moto server** (`motoserver/moto` container) provides AWS endpoints for docker-compose and the kind cluster.
- **Moto's in-process `mock_aws`** backs the test suite.

Applications use the standard `AWS_ENDPOINT_URL` environment variable that boto3 supports natively, so application code has no emulator-specific branches.

## Consequences
- Zero cost, no sign-up, and the same behaviour on a laptop and in CI.
- Terraform uses the official `hashicorp/aws` provider with endpoint overrides. Pointing it at real AWS means deleting those overrides.
- Moto's fidelity is high for the APIs used here, but it doesn't enforce IAM or service quotas. Those would need validating in a real account before production.
