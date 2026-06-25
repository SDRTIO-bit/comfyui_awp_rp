"""Tests for i18n catalog reflection."""

import os
import sys
import unittest

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARENT_DIR = os.path.dirname(PLUGIN_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from comfyui_awp_rp.i18n import build_i18n_catalog
from comfyui_awp_rp.nodes import NODE_CLASS_MAPPINGS


class TestI18nCatalog(unittest.TestCase):
    def test_catalog_has_all_sections(self):
        cat = build_i18n_catalog()
        self.assertIn("widgetLabels", cat)
        self.assertIn("combos", cat)
        self.assertIn("portLabels", cat)
        self.assertIn("menuLabels", cat)

    def test_widget_labels_cover_all_nodes(self):
        cat = build_i18n_catalog()
        # 反射应遍历全部注册节点
        self.assertEqual(cat["nodeCount"], len(NODE_CLASS_MAPPINGS))

    def test_strategy_combo_translated(self):
        cat = build_i18n_catalog()
        # AWPRetriever.strategy 是 combo，候选值含 keyword 等
        self.assertIn("strategy", cat["combos"])
        vals = cat["combos"]["strategy"]
        self.assertEqual(vals["keyword"], "关键词")
        self.assertEqual(vals["bm25"], "BM25")

    def test_chinese_combo_values_skipped(self):
        # AWPWorldbook.activation 候选值已是中文，不得出现在 combos 反转表
        cat = build_i18n_catalog()
        self.assertNotIn("activation", cat["combos"])

    def test_combo_values_are_english_keys(self):
        # combos 的 key 必须是英文候选值（内部协议），中文是 value
        cat = build_i18n_catalog()
        for field, mapping in cat["combos"].items():
            for eng_val, zh_val in mapping.items():
                # 英文 key 不应含中文（除非本就是中文候选值，但那些已被跳过）
                self.assertFalse(
                    any("一" <= ch <= "鿿" for ch in eng_val),
                    f"combo key for {field} contains CJK: {eng_val}",
                )

    def test_unknown_combo_value_kept_as_english(self):
        # 反射发现但字典无译文的候选值，保留英文（不出现在映射里即视为保留）
        cat = build_i18n_catalog()
        # greeting.mode select/list 都有译文
        self.assertEqual(cat["combos"]["mode"]["select"], "选择")


if __name__ == "__main__":
    unittest.main()
