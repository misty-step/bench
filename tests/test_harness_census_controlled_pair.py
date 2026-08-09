from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from harness_census_common import (
    CAMPAIGN_ID,
    CONTROLLED_EFFORT,
    CONTROLLED_MODEL,
    TaskRecord,
    campaign_matrix,
    cohort_identity,
    digest,
    row_identity,
    validate_controlled_pair,
)
from harness_census_staging import build_cells, immutable_stage_cells, probe_controlled_argv_surfaces
from run_harness_census import campaign_stage, validate_resume_campaign_binding, validate_resume_controlled_pair

TASK_IDS = sorted((
    "estate-pagination-origin",
    "iron-forest-go-checkruns-array",
    "sploot-hydration-device-lane",
))


class ResumeCampaignBindingTests(unittest.TestCase):
    def test_resume_rejects_stage_digest_and_campaign_id_mutations(self) -> None:
        stage = {"stage": "frozen"}
        campaign = {"stage_manifest_digest": digest(stage), "campaign_id": CAMPAIGN_ID}
        for key, value in (("stage_manifest_digest", "0" * 64), ("campaign_id", "tampered")):
            mutated = dict(campaign)
            mutated[key] = value
            with self.subTest(key=key), self.assertRaisesRegex(SystemExit, "does not bind"):
                validate_resume_campaign_binding(stage, mutated)

    def test_resume_rejects_a_different_controlled_pair(self) -> None:
        staged_pair = validate_controlled_pair("openrouter/deepseek/deepseek-v4-flash-0731", "high")
        campaign = {
            "controlled_model": staged_pair.model_requested,
            "controlled_route": staged_pair.provider_route_resolved,
            "controlled_effort": staged_pair.effort_requested,
        }
        validate_resume_controlled_pair(campaign, staged_pair)
        with self.assertRaisesRegex(SystemExit, "controlled pair differs"):
            validate_resume_controlled_pair(campaign, validate_controlled_pair(CONTROLLED_MODEL, CONTROLLED_EFFORT))


class ControlledRouteTests(unittest.TestCase):
    def test_deepseek_high_pair_populates_controlled_matrix(self) -> None:
        pair = validate_controlled_pair("openrouter/deepseek/deepseek-v4-flash-0731", "high")
        matrix = campaign_matrix(pair)
        controlled = [row for row in matrix if row["composition"] != "native_default"]
        self.assertEqual(len(matrix), 9)
        self.assertEqual(len(controlled), 6)
        self.assertTrue(all(row["model_requested"] == pair.model_requested and row["effort_requested"] == pair.effort_requested for row in controlled))
        self.assertNotEqual(row_identity(pair.model_requested, pair.effort_requested, "omp", "controlled_raw"), row_identity(CONTROLLED_MODEL, CONTROLLED_EFFORT, "omp", "controlled_raw"))
        self.assertNotEqual(cohort_identity(pair.model_requested, pair.effort_requested, pair.provider_route_resolved, pair.effort_requested), cohort_identity(CONTROLLED_MODEL, CONTROLLED_EFFORT, CONTROLLED_MODEL, CONTROLLED_EFFORT))

    def test_controlled_alias_resolves_openrouter_route(self) -> None:
        pair = validate_controlled_pair("openrouter/zai/glm-5.2", "high")
        self.assertEqual(pair.model_requested, "openrouter/zai/glm-5.2")
        self.assertEqual(pair.provider_route_resolved, "openrouter/z-ai/glm-5.2")
        self.assertEqual(pair.effort_requested, "high")

    def test_controlled_probe_splits_resolved_route_for_adapters(self) -> None:
        pair = validate_controlled_pair("openrouter/zai/glm-5.2", "high")
        calls: list[tuple[str, str, str, str]] = []
        flags = {
            "prime": ("--no-context-files", "--no-extensions", "--no-prompt-templates", "--no-skills", "--no-themes"),
            "omp": ("--no-extensions", "--no-rules", "--no-skills"),
            "pi": ("--no-context-files", "--no-extensions", "--no-prompt-templates", "--no-skills", "--no-themes"),
        }
        tools = {"prime": "ipython", "omp": "read,edit,write", "pi": "read,edit,write"}

        def parse_model(route: str) -> tuple[str, str]:
            self.assertEqual(route, pair.provider_route_resolved)
            return tuple(route.split("/", 1))

        def build_argv(name: str, *, provider: str, model: str, thinking: str, **_kwargs: object) -> list[str]:
            calls.append((name, provider, model, thinking))
            return [name, *flags[name], "--tools", tools[name]]

        contract = type("AdapterContract", (), {"build_argv": staticmethod(build_argv), "parse_openrouter_model": staticmethod(parse_model)})
        with tempfile.TemporaryDirectory(prefix="controlled-probe-") as directory:
            root = Path(directory)
            (root / "adapter_common.py").write_text("# adapter contract\n", encoding="utf-8")
            (root / "prime_kernel_wrapper.sh").write_text("env -i bwrap --unshare-net\n", encoding="utf-8")
            with patch("harness_census_staging.importlib.import_module", return_value=contract):
                probe_controlled_argv_surfaces(root, pair)
        self.assertEqual(calls, [(name, "openrouter", "z-ai/glm-5.2", "high") for name in ("prime", "omp", "pi")])

    def test_alias_staging_separates_requested_and_resolved_identity(self) -> None:
        pair = validate_controlled_pair("openrouter/zai/glm-5.2", "high")

        def staged_record(index: int, task_id: str) -> TaskRecord:
            token = f"{index:064x}"
            return TaskRecord(
                task_id=task_id,
                source_cluster="cluster",
                task_digest=token,
                comparison_task_digest=token,
                grader_digest=token,
                reference_hunk_map_digest=token,
                dockerfile_digest=token,
                gateway_digest=token,
                gateway_dockerfile_digest=token,
                compose_digest=token,
                task_dir=f"tasks/{task_id}",
                immutable_paths=(),
                network_mode="public",
                context_manifest_digest=token,
                context_pack_digest=token,
                skill_digest=token,
                context_digest=token,
                skill_count=0,
            )

        records = {task_id: staged_record(index, task_id) for index, task_id in enumerate(TASK_IDS, 1)}

        def stage_task_stub(_cell_dir: Path, task: str, *_args: object) -> TaskRecord:
            return records[task]

        task_values = {task_id: task_id for task_id in TASK_IDS}
        with tempfile.TemporaryDirectory(prefix="controlled-pair-stage-") as directory, patch("harness_census_staging.validate_gateway_contract"), patch("harness_census_staging.load_tasks", return_value=task_values), patch("harness_census_staging.copy_adapters", return_value="d" * 64), patch("harness_census_staging.harness_package_info", return_value={"digest": "e" * 64, "prime_digest": "f" * 64}), patch("harness_census_staging.stage_task", side_effect=stage_task_stub):
            cells = build_cells(Path(directory), {"controlled_raw": "raw\n"}, {}, Path(directory), Path(directory), None, pair)
            cell = next(cell for cell in cells if cell.cell_id == "prime-controlled_raw")
            config = json.loads(cell.spec_path.read_text(encoding="utf-8"))["runner"]["corpus"]["config"]
            summary = immutable_stage_cells(cells)[cell.cell_id]["summary"]
            self.assertEqual(cell.model_requested, pair.model_requested)
            self.assertEqual(cell.provider_route_resolved, pair.provider_route_resolved)
            self.assertEqual(cell.row_id, row_identity(pair.model_requested, pair.effort_requested, "prime", "controlled_raw"))
            self.assertEqual(cell.cohort_id, cohort_identity(pair.model_requested, pair.effort_requested, pair.provider_route_resolved, pair.effort_requested))
            self.assertEqual(config["model"], pair.provider_route_resolved)
            self.assertEqual(summary["model_requested"], pair.model_requested)
            self.assertEqual(summary["provider_route_resolved"], pair.provider_route_resolved)
            stage = campaign_stage(cells, {}, {"digest": "e" * 64}, {"commit": None, "binary_digest": None}, "0" * 40, {}, "f" * 64)
            stage_summary = stage["cells"][cell.cell_id]["summary"]
            self.assertEqual(stage_summary["model_requested"], pair.model_requested)
            self.assertEqual(stage_summary["provider_route_resolved"], pair.provider_route_resolved)
            self.assertEqual(stage["decision_policy"]["controlled_route_identity"], pair.provider_route_resolved)
            mismatched = tuple(replace(item, provider_route_resolved="openrouter/other") if item.cell_id == "omp-controlled_raw" else item for item in cells)
            with self.assertRaisesRegex(SystemExit, "do not share one controlled pair"):
                campaign_stage(mismatched, {}, {"digest": "e" * 64}, {"commit": None, "binary_digest": None}, "0" * 40, {}, "f" * 64)

    def test_invalid_controlled_effort_is_rejected(self) -> None:
        with self.assertRaisesRegex(SystemExit, "not supported"):
            validate_controlled_pair("openrouter/deepseek/deepseek-v4-flash-0731", "medium")

    def test_non_openrouter_route_is_rejected(self) -> None:
        with self.assertRaisesRegex(SystemExit, "OpenRouter"):
            validate_controlled_pair("openai-codex/gpt-5.6-luna", "high")


if __name__ == "__main__":
    unittest.main()
