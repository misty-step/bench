# Repair pagination origin validation

Repair the pinned Estate repository at the named source path.

Validate every DigitalOcean pagination `next` link before requesting it. Accept relative API paths and absolute links with the exact same scheme, host, and effective port as the configured API base. Reject cross-origin and scheme-relative attacker links before any request.

Edit only `src/collect/digitalocean.rs`. Do not add dependencies, network calls, credentials, tests, or generated files. The grader runs after your session and checks behavior and scope.
