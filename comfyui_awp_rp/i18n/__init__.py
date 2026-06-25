"""i18n catalog: reflect node definitions into a display-layer translation map.

Returns a dict consumed by the JS frontend via the /awp/i18n endpoint.
The catalog ONLY affects display (widget labels, combo shown values,
input port labels). Internal identifiers stay English.
"""

from .labels_zh import WIDGET_LABELS, COMBO_VALUES, MENU_LABELS


def _is_combo_value_list(spec):
    """A combo field is (list_of_strings, opts) with a non-empty list."""
    return (
        isinstance(spec, (list, tuple))
        and len(spec) >= 2
        and isinstance(spec[0], list)
        and len(spec[0]) > 0
        and all(isinstance(v, str) for v in spec[0])
    )


def _values_already_chinese(values):
    """If any candidate value already contains CJK, the node stores Chinese
    internally (e.g. AWPWorldbook.activation). We must NOT reverse-translate
    it — skip the whole combo to protect the data contract."""
    return any(_has_cjk(v) for v in values)


def _has_cjk(text):
    return any("一" <= ch <= "鿿" for ch in text)


def build_i18n_catalog():
    """Reflect NODE_CLASS_MAPPINGS and merge with the zh dictionary.

    Returns:
        {
            "nodeCount": int,
            "widgetLabels": {field_name: zh},   # for widget.label
            "portLabels":   {field_name: zh},   # for input.label (same source)
            "combos": {field_name: {eng_value: zh_value}},  # only fields whose
                       # candidate values are all English AND have a dict entry
            "menuLabels": {eng: zh},
        }
    """
    from comfyui_awp_rp.nodes import NODE_CLASS_MAPPINGS

    # Collect candidate combo values per field name across ALL nodes (union).
    # Also record whether any node's values are already Chinese.
    field_combo_values = {}      # field -> set of english candidate values
    chinese_combo_fields = set() # fields to skip entirely

    node_count = 0
    for node_type, cls in NODE_CLASS_MAPPINGS.items():
        node_count += 1
        try:
            input_types = cls.INPUT_TYPES()
        except Exception:
            # A node that can't be reflected at import time is skipped, not fatal.
            continue
        for section in ("required", "optional"):
            section_def = input_types.get(section, {}) or {}
            for field_name, spec in section_def.items():
                if not _is_combo_value_list(spec):
                    continue
                values = spec[0]
                if _values_already_chinese(values):
                    chinese_combo_fields.add(field_name)
                    continue
                field_combo_values.setdefault(field_name, set()).update(values)

    # Build combo translation map: for each field, map english value -> zh.
    combos = {}
    for field, value_set in field_combo_values.items():
        if field in chinese_combo_fields:
            continue
        trans_dict = COMBO_VALUES.get(field, {})
        mapping = {}
        for eng_val in sorted(value_set):
            zh = trans_dict.get(eng_val)
            if zh is not None:
                mapping[eng_val] = zh
        # Only include the field if at least one value has a translation;
        # otherwise leave it English (no entry -> JS keeps original).
        if mapping:
            combos[field] = mapping

    return {
        "nodeCount": node_count,
        "widgetLabels": dict(WIDGET_LABELS),
        "portLabels": dict(WIDGET_LABELS),
        "combos": combos,
        "menuLabels": dict(MENU_LABELS),
    }
