"""Frozen acceptance tests for the BENCH_001 benchmark contract.

These tests freeze owner-approved methodology and safety boundaries. They do
not assert unmeasured benchmark results or require a benchmark implementation.
"""

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = REPO_ROOT / "tasks" / "BENCH_001_PORTFOLIO_BENCHMARK_CONTRACT.md"
AUTHORITATIVE_RELEASE_SHA = "ab0646e9fcb4c3c5d1f567a46848a3a98dbda9a5"


def _contract() -> str:
    return CONTRACT_PATH.read_text(encoding="utf-8")


def _section(contract: str, heading: str) -> str:
    match = re.search(
        rf"^## (?:\d+\. )?{re.escape(heading)}\s*$\n(.*?)(?=^## |\Z)",
        contract,
        re.MULTILINE | re.DOTALL,
    )
    assert match is not None, f"missing contract section: {heading}"
    return match.group(1)


def test_contract_exists_and_freezes_authoritative_identity():
    contract = _contract()

    assert contract.startswith("# BENCH_001")
    assert AUTHORITATIVE_RELEASE_SHA in contract
    assert "BENCH_001 contract version: `1.0.0`" in contract
    assert "benchmark/portfolio-evaluation" in contract


def test_contract_freezes_scales_and_reproducibility_manifest():
    contract = _contract()
    scales = _section(contract, "Scale contract")
    manifest = _section(contract, "Result manifest contract")

    for scale in ("10,000", "100,000", "500,000", "1,000,000"):
        assert scale in scales
    assert "attempted scale point" in scales
    assert "at least three" in scales
    assert "median" in scales and "range" in scales
    assert "failed repetitions" in scales

    required_manifest_fields = (
        "release_sha",
        "contract_version",
        "implementation_sha",
        "generator_version",
        "master_seed",
        "observation_count",
        "catalogue_sha256",
        "catalogue_sku_count",
        "catalogue_category_distribution",
        "difficulty_distribution",
        "manila_as_of_day",
        "python_version",
        "postgresql_version",
        "postgresql_image",
        "docker_version",
        "compose_version",
        "machine_cpu",
        "machine_memory",
        "operating_system",
        "repetition",
    )
    for field in required_manifest_fields:
        assert f"`{field}`" in manifest


def test_contract_separates_synthetic_catalogue_labels_and_external_data():
    contract = _contract()
    catalogue = _section(contract, "Catalogue and label-isolation contract")

    assert "benchmark-only catalogue fixture" in catalogue
    assert "production catalogue" in catalogue
    assert "public or external data" in catalogue
    assert "SHA-256" in catalogue
    assert "outside production resolver input" in catalogue
    assert "must not be inserted into `SkuAlias`" in catalogue
    for forbidden_input in ("payload", "URL", "external ID", "seller"):
        assert forbidden_input in catalogue


def test_contract_freezes_catalogue_composition_and_owner_review_gate():
    catalogue = _section(_contract(), "Catalogue and label-isolation contract")

    assert "120 fictional benchmark SKUs" in catalogue
    expected_categories = {
        "GPU": "30",
        "CPU": "25",
        "RAM": "20",
        "Motherboard (`mobo`)": "20",
        "Monitor": "15",
        "Peripheral": "10",
    }
    for category, count in expected_categories.items():
        assert f"| {category} | {count} |" in catalogue
    assert "BENCH_002 may create the exact fixture" in catalogue
    assert "owner review before any measured portfolio benchmark run" in catalogue
    assert "unreviewed fixture" in catalogue
    assert "new fixture version and SHA-256" in catalogue
    assert "No Kaggle, public, or external catalogue content" in catalogue


def test_contract_freezes_pipeline_timing_boundaries_and_claim_language():
    contract = _contract()
    timing = _section(contract, "Pipeline timing contract")
    language = _section(contract, "Portfolio claim language")

    for stage in (
        "generation",
        "benchmark_raw_load",
        "resolve_listings",
        "price_listings",
        "API workload",
        "backup",
        "restore",
        "verification",
    ):
        assert stage in timing
    assert "resolve_listings + price_listings" in timing
    assert "production ingestion throughput" in timing
    assert "manual_capture" in timing

    assert "synthetic marketplace-style listing observations" in language
    assert "controlled labelled synthetic benchmark" in language
    assert "production accuracy" in language
    assert "real-world resolution accuracy" in language
    assert "supports 1M users" in language


def test_contract_freezes_resolution_sets_metrics_and_denominators():
    contract = _contract()
    resolution = _section(contract, "Resolution quality contract")

    assert "E =" in resolution and "A, B, and C" in resolution
    assert "D =" in resolution and "intentionally ambiguous" in resolution
    for metric in (
        "resolution_coverage",
        "resolution_precision",
        "correct_abstention_rate",
        "unnecessary_abstention_rate",
        "unsafe_forced_resolution_rate",
        "review_required_rate",
    ):
        assert metric in resolution
    assert "all automatic resolutions" in resolution
    assert "N/A" in resolution
    assert "per-class A/B/C/D" in resolution
    assert "F1" in resolution


def test_contract_freezes_balanced_difficulty_and_semantic_audit_gate():
    contract = _contract()
    difficulty = _section(contract, "Difficulty contract")
    audit = _section(contract, "Difficulty semantic audit gate")

    for class_name in ("A", "B", "C", "D"):
        assert f"{class_name} = 25%" in difficulty
    assert "balanced evaluation distribution" in difficulty
    assert "diagnostic comparability" in difficulty
    assert "not claimed to represent real marketplace prevalence" in difficulty
    assert "prefix stability" in difficulty

    assert "100 generated titles" in audit
    for class_name in ("A", "B", "C", "D"):
        assert f"25 from {class_name}" in audit
    assert "generator-label validity" in audit
    assert "not resolver correctness" in audit
    assert "correct the generator or difficulty rules" in audit
    assert "increment `generator_version`" in audit
    assert "must not begin" in audit


def test_contract_freezes_generator_identity_repetition_and_sellers():
    generation = _section(_contract(), "Deterministic generation contract")

    assert '`generator_version = "1.0.0"`' in generation
    assert "`master_seed = 20260829`" in generation
    assert "90% unique listing identities" in generation
    assert "10% repeated snapshots" in generation
    assert "4,096" in generation and "seller" in generation
    assert "distinct fetched instants" in generation
    assert "source/external ID/fetched instant" in generation
    assert "reserved for adversarial tests" in generation
    assert "not claimed to describe real marketplace behavior" in generation


def test_contract_freezes_fresh_scale_run_sequence():
    scale_run = _section(_contract(), "Scale-run sequence")

    expected_steps = (
        "fresh benchmark PostgreSQL project and database",
        "frozen benchmark catalogue",
        "deterministic dataset prefix",
        "pre-processing counts and database sizes",
        "`resolve_listings`",
        "`price_listings`",
        "quality metrics externally",
        "API workload",
        "`pg_backup.sh`",
        "scaled verified restore",
        "final counts and database sizes",
        "small result manifest",
        "proven benchmark-specific resources",
    )
    for step in expected_steps:
        assert step in scale_run


def test_contract_freezes_backup_restore_safety_boundary():
    contract = _contract()
    safety = _section(contract, "Backup and restore safety contract")

    assert "`pg_backup.sh` remains unchanged" in safety
    assert "benchmark-only scaled restore runner" in safety
    assert "fail closed" in safety
    assert "uncertain cleanup" in safety
    assert "TASK_035" in safety
    for forbidden_cleanup in (
        "docker compose down -v",
        "wildcard volume deletion",
        "docker system prune",
        "broad label cleanup",
    ):
        assert forbidden_cleanup in safety
    assert "frozen tests" in safety
    assert "full streamed deterministic content verification" in safety
    assert "every application table" in safety
    assert "deterministic ordering" in safety
    assert "canonical serialization" in safety
    assert "empty application table" in safety
    assert "captured before backup" in safety


def test_contract_freezes_adversarial_case_reporting_schema():
    adversarial = _section(_contract(), "Adversarial and integrity contract")

    for field in (
        "case ID",
        "input category",
        "accepted, rejected, or reviewed",
        "row-count delta",
        "enforcement layer",
        "exception, constraint, or trigger",
        "pricing state",
    ):
        assert field in adversarial
    assert "qualitative and structural" in adversarial
    assert "rejection percentage" in adversarial


def test_contract_explicitly_prohibits_benchmark_gaming():
    gaming = _section(_contract(), "Prohibited benchmark gaming")

    prohibitions = (
        "evaluation titles as aliases",
        "expected SKU",
        "only easy exact aliases",
        "class proportions",
        "tuning resolver behavior",
        "constraints or triggers",
        "bypassing production commands",
        "best repetition",
        "failed scale points",
        "production ingestion",
        "tiny TASK_037 restore",
        "real-world production results",
    )
    for prohibition in prohibitions:
        assert prohibition in gaming


def test_contract_freezes_api_headline_matrix():
    api = _section(_contract(), "API workload contract")

    assert "100 warmup requests" in api
    assert "2,000 measured requests at concurrency 1" in api
    assert "2,000 measured requests at concurrency 8" in api
    assert "excluded from latency statistics" in api
    assert "Session establishment is outside measured" in api
    assert "Connection reuse" in api
    assert "Concurrency 32 is not part of the initial headline" in api
    assert "saturation experiment" in api


def test_contract_freezes_scale_timeouts_and_resource_preflight():
    contract = _contract()
    scales = _section(contract, "Scale contract")
    preflight = _section(contract, "Resource preflight contract")

    expected_timeouts = {
        "10,000": "15 minutes",
        "100,000": "45 minutes",
        "500,000": "2 hours",
        "1,000,000": "4 hours",
    }
    for scale, timeout in expected_timeouts.items():
        assert f"| {scale} | {timeout} |" in scales
    assert "`timed_out`" in scales
    assert "must remain visible" in scales
    assert "must not be modified" in scales

    expected_disk = {
        "10,000": "8 GiB",
        "100,000": "12 GiB",
        "500,000": "20 GiB",
        "1,000,000": "30 GiB",
    }
    for scale, floor in expected_disk.items():
        assert f"| {scale} | {floor} |" in preflight
    assert "4 GiB" in preflight and "Docker runtime" in preflight
    assert "safety floors" in preflight
    assert "`not_attempted`" in preflight
    assert "failed preflight requirement" in preflight
    assert "must not be lowered" in preflight
    assert "isolated and auditable" in preflight


def test_contract_freezes_result_retention_policy():
    retention = _section(_contract(), "Result retention contract")

    committed = (
        "small machine-readable result manifests",
        "aggregate CSV or JSON summaries",
        "final Markdown benchmark report",
        "small generated charts",
    )
    ignored = (
        "generated datasets",
        "label sidecars",
        "PostgreSQL dumps",
        "checksum sidecars",
        "databases and volumes",
        "raw API request logs",
        "verbose temporary benchmark logs",
    )
    for artifact in committed + ignored:
        assert artifact in retention
    assert "exact-resource or exact-file cleanup" in retention
    assert "must not be committed" in retention


def test_contract_does_not_assert_unmeasured_outcomes():
    contract = _contract()

    forbidden_claim_patterns = (
        r"1,000,000 observations (?:succeeded|completed successfully)",
        r"resolution precision (?:is|of) \d",
        r"resolution coverage (?:is|of) \d",
        r"API p95 (?:is|of) \d",
        r"observations/second (?:is|of) \d",
    )
    for pattern in forbidden_claim_patterns:
        assert re.search(pattern, contract, re.IGNORECASE) is None


def test_bench_001_changes_only_contract_artifacts():
    contract = _contract()

    assert "Allowed BENCH_001 changed paths" in contract
    assert "`tasks/BENCH_001_PORTFOLIO_BENCHMARK_CONTRACT.md`" in contract
    assert "`tests/test_bench_001_portfolio_benchmark_contract.py`" in contract
    assert "No production runtime file may change" in contract
