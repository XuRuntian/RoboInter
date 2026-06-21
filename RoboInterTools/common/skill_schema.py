import os
import re

import yaml


SCHEMA_VERSION = "skill_text_v1"
TEMPLATE_SET_VERSION = "skill_templates_v1"

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SKILL_TEMPLATE_PATH = os.path.join(ROOT_DIR, "config", "skill_templates.yaml")
DEFAULT_COORDINATION_MODE_PATH = os.path.join(ROOT_DIR, "config", "coordination_modes.yaml")

ACTION_ALLOWED_KEYS = {"subject", "skill", "slots", "text"}
SUBTASK_ALLOWED_KEYS = {"start_frame", "end_frame", "coordination_mode", "actions", "text"}
ANNOTATION_ALLOWED_KEYS = {"schema_version", "template_set_version", "video_text", "subtasks"}


def load_yaml_file(path):
    with open(path, "r") as f:
        return yaml.safe_load(f) or {}


def extract_template_slots(template):
    return re.findall(r"\[([^\]]+)\]", template or "")


def validate_skill_config(skill_config):
    skill_id = skill_config.get("id")
    if not skill_id:
        raise ValueError("skill config missing id")
    template = skill_config.get("template")
    if not template:
        raise ValueError(f"skill {skill_id} missing template")
    required_slots = skill_config.get("required_slots")
    if not isinstance(required_slots, list) or not required_slots:
        raise ValueError(f"skill {skill_id} required_slots must be a non-empty list")

    template_slots = set(extract_template_slots(template))
    required_slot_set = set(required_slots)
    if template_slots != required_slot_set:
        raise ValueError(
            f"skill {skill_id} template slots {sorted(template_slots)} "
            f"do not match required_slots {sorted(required_slot_set)}"
        )
    ui_template = skill_config.get("ui_template")
    if ui_template:
        ui_template_slots = set(extract_template_slots(ui_template))
        if ui_template_slots != required_slot_set:
            raise ValueError(
                f"skill {skill_id} ui_template slots {sorted(ui_template_slots)} "
                f"do not match required_slots {sorted(required_slot_set)}"
            )

    enum_constraints = skill_config.get("enum_constraints", {})
    if enum_constraints is None:
        skill_config["enum_constraints"] = {}
        enum_constraints = {}
    if not isinstance(enum_constraints, dict):
        raise ValueError(f"skill {skill_id} enum_constraints must be a dict")
    for slot, allowed_values in enum_constraints.items():
        if slot not in required_slot_set:
            raise ValueError(f"skill {skill_id} enum slot {slot} is not in required_slots")
        if not isinstance(allowed_values, list) or not allowed_values:
            raise ValueError(f"skill {skill_id} enum slot {slot} must have non-empty values")

    return True


def load_skill_templates(path=DEFAULT_SKILL_TEMPLATE_PATH):
    data = load_yaml_file(path)
    template_set_version = data.get("template_set_version")
    if template_set_version != TEMPLATE_SET_VERSION:
        raise ValueError(
            f"template_set_version must be {TEMPLATE_SET_VERSION}, got {template_set_version}"
        )

    skills = {}
    global_slot_display_names = data.get("slot_display_names", {}) or {}
    for skill_config in data.get("skills", []):
        validate_skill_config(skill_config)
        slot_display_names = dict(global_slot_display_names)
        slot_display_names.update(skill_config.get("slot_display_names", {}) or {})
        skill_config["slot_display_names"] = slot_display_names
        skill_id = skill_config["id"]
        if skill_id in skills:
            raise ValueError(f"duplicate skill id: {skill_id}")
        skills[skill_id] = skill_config
    if not skills:
        raise ValueError("skill_templates.yaml has no skills")
    return template_set_version, skills


def load_coordination_modes(path=DEFAULT_COORDINATION_MODE_PATH):
    data = load_yaml_file(path)
    modes = {}
    for mode in data.get("coordination_modes", []):
        mode_id = mode.get("id")
        if not mode_id:
            raise ValueError("coordination mode missing id")
        if mode_id in modes:
            raise ValueError(f"duplicate coordination_mode id: {mode_id}")
        modes[mode_id] = mode
    if not modes:
        raise ValueError("coordination_modes.yaml has no modes")
    return modes


def get_skill(skill_id, skill_templates):
    if skill_id not in skill_templates:
        raise ValueError(f"unknown skill: {skill_id}")
    return skill_templates[skill_id]


def render_template(template, values):
    rendered = template
    for slot in extract_template_slots(template):
        rendered = rendered.replace(f"[{slot}]", str(values.get(slot, "")))
    return rendered


def render_action_text(action, skill_config):
    values = dict(action.get("slots") or {})
    values["subject"] = action.get("subject", "")
    return render_template(skill_config["template"], values)


def render_subtask_text(actions):
    action_texts = [action.get("text", "") for action in actions]
    if len(action_texts) <= 1:
        return action_texts[0] if action_texts else ""
    return "; meanwhile ".join(action_texts)


def build_action_from_slot_values(skill_id, slot_values, skill_templates, allow_empty=False):
    skill_config = get_skill(skill_id, skill_templates)
    missing_slots = [
        slot for slot in skill_config["required_slots"]
        if not str(slot_values.get(slot, "")).strip()
    ]
    if missing_slots and not allow_empty:
        raise ValueError(f"缺少必填 slot: {missing_slots[0]}")

    subject = str(slot_values.get("subject", "")).strip()
    slots = {}
    for slot in skill_config["required_slots"]:
        if slot == "subject":
            continue
        slots[slot] = str(slot_values.get(slot, "")).strip()

    action = {
        "subject": subject,
        "skill": skill_id,
        "slots": slots,
        "text": "",
    }
    action["text"] = render_action_text(action, skill_config)
    return action


def validate_action(action, skill_templates, prefix="action"):
    if not isinstance(action, dict):
        return f"{prefix} 必须是 dict"

    unknown_keys = set(action) - ACTION_ALLOWED_KEYS
    if unknown_keys:
        return f"{prefix} 出现未知字段: {sorted(unknown_keys)}"
    missing_keys = ACTION_ALLOWED_KEYS - set(action)
    if missing_keys:
        return f"{prefix} 缺少字段: {sorted(missing_keys)}"

    if not str(action.get("subject", "")).strip():
        return f"{prefix} 缺少 subject"
    skill_id = action.get("skill")
    if skill_id not in skill_templates:
        return f"{prefix} skill 不在 skill_templates.yaml 中: {skill_id}"

    slots = action.get("slots")
    if not isinstance(slots, dict):
        return f"{prefix} slots 必须是 dict"
    if "subject" in slots:
        return f"{prefix} slots 不允许包含 subject"

    skill_config = skill_templates[skill_id]
    required_slot_keys = {slot for slot in skill_config["required_slots"] if slot != "subject"}
    actual_slot_keys = set(slots)
    if actual_slot_keys != required_slot_keys:
        missing = sorted(required_slot_keys - actual_slot_keys)
        extra = sorted(actual_slot_keys - required_slot_keys)
        if missing:
            return f"{prefix} 缺少必填 slot: {missing}"
        return f"{prefix} 出现多余 slot: {extra}"

    for slot in required_slot_keys:
        if not str(slots.get(slot, "")).strip():
            return f"{prefix} slot 不能为空: {slot}"

    for slot, allowed_values in skill_config.get("enum_constraints", {}).items():
        if str(slots.get(slot)) not in [str(value) for value in allowed_values]:
            return f"{prefix} 的 {slot} 必须属于 {allowed_values}"

    expected_text = render_action_text(action, skill_config)
    if action.get("text") != expected_text:
        return f"{prefix} text 必须等于模板渲染结果"

    return None


def validate_subtask(subtask, skill_templates, coordination_modes, prefix="subtask"):
    if not isinstance(subtask, dict):
        return f"{prefix} 必须是 dict"

    unknown_keys = set(subtask) - SUBTASK_ALLOWED_KEYS
    if unknown_keys:
        return f"{prefix} 出现未知字段: {sorted(unknown_keys)}"
    missing_keys = SUBTASK_ALLOWED_KEYS - set(subtask)
    if missing_keys:
        return f"{prefix} 缺少字段: {sorted(missing_keys)}"

    try:
        start_frame = int(subtask["start_frame"])
        end_frame = int(subtask["end_frame"])
    except (TypeError, ValueError):
        return f"{prefix} start_frame/end_frame 必须是整数"
    if start_frame > end_frame:
        return f"{prefix} start_frame 必须小于等于 end_frame"

    coordination_mode = subtask.get("coordination_mode")
    if coordination_mode not in coordination_modes:
        return f"{prefix} coordination_mode 不在 coordination_modes.yaml 中: {coordination_mode}"

    actions = subtask.get("actions")
    if not isinstance(actions, list) or not actions:
        return f"{prefix} actions 必须非空"

    for action_idx, action in enumerate(actions):
        error = validate_action(action, skill_templates, f"{prefix}.actions[{action_idx}]")
        if error:
            return error

    expected_text = render_subtask_text(actions)
    if subtask.get("text") != expected_text:
        return f"{prefix} text 必须等于 actions[].text 自动拼接结果"

    return None


def validate_annotation(annotation, skill_templates=None, coordination_modes=None):
    if skill_templates is None:
        _, skill_templates = load_skill_templates()
    if coordination_modes is None:
        coordination_modes = load_coordination_modes()

    if not isinstance(annotation, dict):
        return "annotation 必须是 dict"

    unknown_keys = set(annotation) - ANNOTATION_ALLOWED_KEYS
    if unknown_keys:
        return f"顶层出现未知字段: {sorted(unknown_keys)}"
    missing_keys = ANNOTATION_ALLOWED_KEYS - set(annotation)
    if missing_keys:
        return f"顶层缺少字段: {sorted(missing_keys)}"

    if annotation.get("schema_version") != SCHEMA_VERSION:
        return f"schema_version 必须是 {SCHEMA_VERSION}"
    if annotation.get("template_set_version") != TEMPLATE_SET_VERSION:
        return f"template_set_version 必须是 {TEMPLATE_SET_VERSION}"
    if not str(annotation.get("video_text", "")).strip():
        return "video_text 不能为空"

    subtasks = annotation.get("subtasks")
    if not isinstance(subtasks, list) or not subtasks:
        return "subtasks 必须非空"

    try:
        sorted_subtasks = sorted(subtasks, key=lambda item: int(item["start_frame"]))
    except (KeyError, TypeError, ValueError):
        return "subtasks start_frame 格式错误"

    expected_start = None
    for subtask_idx, subtask in enumerate(sorted_subtasks):
        error = validate_subtask(
            subtask, skill_templates, coordination_modes, f"subtasks[{subtask_idx}]"
        )
        if error:
            return error

        start_frame = int(subtask["start_frame"])
        end_frame = int(subtask["end_frame"])
        if expected_start is not None and start_frame != expected_start:
            return (
                f"subtasks 不连续：上一段结束后应从第{expected_start + 1}帧开始，"
                f"但下一段从第{start_frame + 1}帧开始"
            )
        expected_start = end_frame + 1

    return None
