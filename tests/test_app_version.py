from __future__ import annotations

import ast
import unittest
from pathlib import Path


class AppVersionTests(unittest.TestCase):
    def test_current_version_is_v_1_4_0(self):
        config_path = Path(__file__).resolve().parents[1] / "config.py"
        config_tree = ast.parse(config_path.read_text(encoding="utf-8"))
        versions = {
            target.id: node.value.value
            for node in config_tree.body
            if isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance((target := node.targets[0]), ast.Name)
            and target.id == "APP_VERSION"
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        }

        self.assertEqual(versions.get("APP_VERSION"), "v-1.4.0")

    def test_version_is_first_work_panel_item(self):
        app_source = (Path(__file__).resolve().parents[1] / "app.py").read_text(
            encoding="utf-8"
        )
        version_marker = (
            'st.sidebar.caption(f"Версія програми: **{config.APP_VERSION}**")'
        )

        self.assertIn(version_marker, app_source)
        self.assertLess(
            app_source.index(version_marker),
            app_source.index("ui_theme.render_sidebar_auto_refresh()"),
        )


if __name__ == "__main__":
    unittest.main()
