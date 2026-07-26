# Phase F1a — AWS S3 and EC2 Instance Profile Setup

## What this phase creates

This guide creates:

- one private S3 bucket in `us-east-2`;
- all four S3 Block Public Access settings;
- S3-managed server-side encryption (`SSE-S3`, `AES256`);
- object versioning;
- cleanup of incomplete multipart uploads after seven days;
- one EC2-trusted IAM role with prefix-scoped least privilege;
- one instance profile containing that role.

It does **not**:

- change Caddy, DNS, the Elastic IP, security-group rules, or Docker ports;
- place long-lived AWS access keys in `.env`;
- upload the 15 learner documents;
- add the application-level S3 adapter;
- ingest documents or create embeddings.

Application adapter work is Phase F1b and should be reviewed against the
post-Phase-B repository to avoid creating a duplicate storage abstraction.

## Fixed production context

- AWS region: `us-east-2`
- Proposed bucket: `finquest-knowledge-prod-881490130721-us-east-2`
- Locate the production EC2 instance in `us-east-2` by both:
  - public IPv4: `3.147.1.121`
  - private IPv4: `172.31.47.37`
- Before changing IAM, record and verify the instance's current:
  - instance ID;
  - Name tag;
  - instance state;
  - attached IAM role or instance profile.
- Existing public domains and Caddy routing remain unchanged.

Do not rely on an instance ID copied from an earlier infrastructure session.
The addresses above must match the same running instance before F1a continues.

## Create the CloudFormation stack

1. Sign in to AWS and switch to **US East (Ohio) — us-east-2**.
2. Open **CloudFormation**.
3. Choose **Create stack → With new resources (standard)**.
4. Under template source choose **Upload a template file**.
5. Upload:

   `infrastructure/aws/finquest-storage.yaml`

6. Choose **Next**.
7. Stack name:

   `finquest-production-storage`

8. Keep the proposed bucket name unless AWS reports that it is unavailable.
9. Environment: `production`.
10. Multipart cleanup: `7`.
11. Continue through stack options.
12. On the review page acknowledge creation of named IAM resources.
13. Choose **Submit**.
14. Wait for `CREATE_COMPLETE`.
15. Open **Outputs** and record every output.

If bucket creation reports a global-name collision, stop. Do not silently add
a random suffix. Record the exact error and approve a deterministic suffix
before updating both the stack parameter and later application configuration.

## Attach the instance profile to the running EC2 instance

1. Open **EC2 > Instances** in `us-east-2`.
2. Locate the instance whose public IPv4 is `3.147.1.121`.
3. Confirm that the same instance has private IPv4 `172.31.47.37`.
4. Confirm its Name tag and record its current instance ID.
5. Check the current value in the **IAM role** column.
6. If an unrelated IAM role is already attached, stop and record its name.
   Do not replace it until its existing permissions and consumers are understood.
7. After the CloudFormation stack reaches `CREATE_COMPLETE`, choose
   **Actions > Security > Modify IAM role**.
8. Select the instance profile output:

   `finquest-production-ec2-storage-profile`

9. Choose **Update IAM role**.
10. Re-open the instance details and confirm the expected profile is attached.

Only one IAM role can be associated with the instance at a time. Replacing an
existing profile can remove permissions currently used by applications,
agents, deployment tooling, or monitoring.

## Do not change production `.env` yet

`docs/f1-env-block.txt` contains the future variables. Add them only after F1b
implements and tests application settings and an S3 adapter.

Never place these on EC2:

- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`

The SDK should use the temporary credentials delivered by the EC2 Instance
Profile.

## Console verification after stack creation

Confirm:

- S3 bucket region is `us-east-2`;
- versioning is **Enabled**;
- default encryption is **SSE-S3**;
- Block Public Access shows all four settings enabled;
- Object Ownership is **Bucket owner enforced**;
- lifecycle includes aborting incomplete multipart uploads after seven days;
- bucket policy denies non-TLS requests;
- IAM role trust principal is `ec2.amazonaws.com`;
- allowed S3 actions are limited to this bucket and the three prefixes;
- instance profile contains exactly the FinQuest storage role.

The `s3:*` in the bucket policy is a **Deny** for insecure transport. The role's
Allow policy contains no wildcard S3 permission.

## Verification after F1b

After the repository has a reviewed AWS SDK dependency and adapter, verify from
the API or knowledge-worker container:

1. Credentials resolve through the Instance Profile without access keys.
2. `GetBucketLocation` succeeds.
3. Listing succeeds only for allowed prefixes.
4. Put and get a disposable object under a dedicated test prefix.
5. Access to an unrelated bucket or unapproved prefix is denied.
6. Logs do not print credentials, presigned URLs, or secret headers.

Do not use learner documents for the first write test.

## Rollback

1. In EC2, change the instance's IAM role to **No IAM Role** or the previously
   recorded role.
2. Delete the CloudFormation stack.
3. The S3 bucket uses `DeletionPolicy: Retain`, so deleting the stack
   intentionally preserves data.
4. Delete the retained bucket only after a separate explicit retention
   decision and confirmation that it is empty or backed up.
