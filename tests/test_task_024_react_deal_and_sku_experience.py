import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"

EXPECTED_SCRIPTS = {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "lint": "oxlint .",
    "test": "vitest run",
    "test:watch": "vitest",
    "preview": "vite preview",
    "check": "npm run lint && npm run test && npm run build",
}

EXPECTED_DEPENDENCIES = {
    "react": "^19.2.8",
    "react-dom": "^19.2.8",
    "react-is": "^19.2.8",
    "react-router": "^8.3.0",
    "recharts": "^3.10.1",
}

EXPECTED_DEV_DEPENDENCIES = {
    "@testing-library/dom": "^10.4.1",
    "@testing-library/jest-dom": "^7.0.0",
    "@testing-library/react": "^16.3.2",
    "@testing-library/user-event": "^14.6.1",
    "@types/node": "^24.13.3",
    "@types/react": "^19.2.17",
    "@types/react-dom": "^19.2.3",
    "@vitejs/plugin-react": "^6.0.4",
    "jsdom": "^30.0.1",
    "oxlint": "^1.76.0",
    "typescript": "~6.0.2",
    "vite": "^8.1.5",
    "vitest": "^4.1.10",
}


def _read_json(path):
    assert path.is_file(), f"TASK_024 implementation must create {path.relative_to(ROOT)}"
    return json.loads(path.read_text())


def test_frontend_foundation_has_the_frozen_vite_typescript_layout():
    required = {
        "frontend/.nvmrc",
        "frontend/package.json",
        "frontend/package-lock.json",
        "frontend/index.html",
        "frontend/tsconfig.json",
        "frontend/tsconfig.app.json",
        "frontend/tsconfig.node.json",
        "frontend/vite.config.ts",
        "frontend/src/main.tsx",
        "frontend/src/App.tsx",
        "frontend/src/api/client.ts",
        "frontend/src/api/types.ts",
        "frontend/src/charts/priceHistory.ts",
        "frontend/src/charts/PriceHistoryChart.tsx",
        "frontend/src/formatting/decimal.ts",
        "frontend/src/formatting/sku.ts",
        "frontend/src/formatting/time.ts",
        "frontend/src/pages/DealFeedPage.tsx",
        "frontend/src/pages/SkuDetailPage.tsx",
        "frontend/src/test/setup.ts",
    }
    missing = sorted(path for path in required if not (ROOT / path).is_file())

    assert missing == [], f"Missing frozen TASK_024 frontend files: {missing}"


def test_package_manager_runtime_and_scripts_are_frozen():
    package = _read_json(FRONTEND / "package.json")

    assert package["name"] == "pricewatchph-frontend"
    assert package["private"] is True
    assert package["type"] == "module"
    assert package["packageManager"] == "npm@11.16.0"
    assert package["engines"] == {
        "node": "24.18.x",
        "npm": "11.16.x",
    }
    assert package["scripts"] == EXPECTED_SCRIPTS
    assert (FRONTEND / ".nvmrc").read_text().strip() == "24.18.0"


def test_frontend_dependency_ranges_are_small_bounded_and_exact():
    package = _read_json(FRONTEND / "package.json")

    assert package["dependencies"] == EXPECTED_DEPENDENCIES
    assert package["devDependencies"] == EXPECTED_DEV_DEPENDENCIES


def test_npm_lockfile_is_authoritative_and_no_other_lockfile_exists():
    lock = _read_json(FRONTEND / "package-lock.json")
    package = _read_json(FRONTEND / "package.json")

    assert lock["lockfileVersion"] == 3
    assert lock["packages"][""]["dependencies"] == package["dependencies"]
    assert lock["packages"][""]["devDependencies"] == package["devDependencies"]
    assert not (FRONTEND / "yarn.lock").exists()
    assert not (FRONTEND / "pnpm-lock.yaml").exists()
    assert not (FRONTEND / "bun.lock").exists()
    assert not (FRONTEND / "bun.lockb").exists()


def test_vite_development_proxy_is_scoped_to_existing_django_boundaries():
    config_path = FRONTEND / "vite.config.ts"
    assert config_path.is_file(), "TASK_024 implementation must create frontend/vite.config.ts"
    config = config_path.read_text()

    assert "strictPort: true" in config
    assert "localhost:8000" in config
    for prefix in ("'/api'", "'/admin'", "'/static'"):
        assert prefix in config
    assert "rewrite:" not in config
    assert "cors:" not in config


def test_generated_frontend_content_has_explicit_repository_ignore_rules():
    ignore_rules = set((ROOT / ".gitignore").read_text().splitlines())

    assert {
        "/frontend/node_modules/",
        "/frontend/dist/",
        "/frontend/coverage/",
        "/frontend/.vite/",
    }.issubset(ignore_rules)


def test_frozen_frontend_acceptance_suite_remains_at_the_vitest_boundary():
    acceptance = (
        FRONTEND
        / "src"
        / "__tests__"
        / "task_024_react_deal_and_sku_experience.test.tsx"
    )

    assert acceptance.is_file()
    assert "from 'vitest'" in acceptance.read_text()
