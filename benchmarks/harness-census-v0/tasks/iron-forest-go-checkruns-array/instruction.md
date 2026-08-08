# Repair check-run JSON handling

Repair the pinned Iron Forest repository at the named source path.

`gh api .../check-runs` returns a JSON object whose `check_runs` value is an array. Keep the existing lifecycle behavior. Ensure roll-up parsing handles two completed records and an empty array. Ensure failed-check reporting retains each failed name and conclusion, and returns an empty result for an empty array without a JSON error.

Edit only `prs.go`. Do not add dependencies, network calls, credentials, tests, or generated files. The grader runs after your session and checks behavior and scope.
