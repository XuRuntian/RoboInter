import os
import re
import copy

import yaml


SCHEMA_VERSION = "skill_text_v1"
TEMPLATE_SET_VERSION = "skill_templates_v1"
SCENE_TEMPLATE_VERSION = "scene_templates_v1"

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SKILL_TEMPLATE_PATH = os.path.join(ROOT_DIR, "config", "skill_templates.yaml")
DEFAULT_COORDINATION_MODE_PATH = os.path.join(ROOT_DIR, "config", "coordination_modes.yaml")
DEFAULT_SCENE_TEMPLATE_PATH = os.path.join(ROOT_DIR, "config", "scene_templates.yaml")

ACTION_ALLOWED_KEYS = {"subject", "skill", "slots", "text"}
SUBTASK_ALLOWED_KEYS = {"start_frame", "end_frame", "coordination_mode", "actions", "text"}
ROBOT_SETUP_ALLOWED_KEYS = {"left_effector_type", "right_effector_type"}
SCENE_OBJECT_ALLOWED_KEYS = {"name", "role", "support_or_region", "states", "affordance"}
SCENE_LOCATION_ALLOWED_KEYS = {"space", "anchor"}
EPISODE_ALLOWED_KEYS = {
    "episode_id",
    "task_id",
    "dataset_name",
    "video_path",
    "primary_video_path",
    "views",
    "frames",
}
SCENE_ALLOWED_KEYS = {
    "task_type",
    "template_id",
    "text",
    "scene_location",
    "objects",
}
ANNOTATION_ALLOWED_KEYS = {
    "schema_version",
    "template_set_version",
    "episode",
    "robot_setup",
    "video_text",
    "scene",
    "subtasks",
}

EFFECTOR_TYPE_ALLOWED_VALUES = [
    "gripper",
    "dexterous_hand",
    "suction_cup",
    "soft_gripper",
    "tool",
    "none",
    "unknown",
]
EFFECTOR_TYPE_DISPLAY_NAMES = {
    "gripper": "夹爪",
    "dexterous_hand": "灵巧手",
    "suction_cup": "吸盘",
    "soft_gripper": "软体夹爪",
    "tool": "工具",
    "none": "无末端",
    "unknown": "无法判断",
}
DEFAULT_ROBOT_SETUP = {
    "left_effector_type": "unknown",
    "right_effector_type": "unknown",
}
LEGACY_SUBJECT_MAP = {
    "left_gripper": "left_effector",
    "right_gripper": "right_effector",
    "both_grippers": "both_effectors",
}


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
    enum_display_names = skill_config.get("enum_display_names", {})
    if enum_display_names is None:
        skill_config["enum_display_names"] = {}
        enum_display_names = {}
    if not isinstance(enum_display_names, dict):
        raise ValueError(f"skill {skill_id} enum_display_names must be a dict")
    for slot, allowed_values in enum_constraints.items():
        if slot not in required_slot_set:
            raise ValueError(f"skill {skill_id} enum slot {slot} is not in required_slots")
        if not isinstance(allowed_values, list) or not allowed_values:
            raise ValueError(f"skill {skill_id} enum slot {slot} must have non-empty values")
        display_names = enum_display_names.get(slot, {})
        if display_names and not isinstance(display_names, dict):
            raise ValueError(f"skill {skill_id} enum_display_names.{slot} must be a dict")

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
    global_enum_constraints = data.get("enum_constraints", {}) or {}
    global_enum_display_names = data.get("enum_display_names", {}) or {}
    for skill_config in data.get("skills", []):
        merged_enum_constraints = dict(global_enum_constraints)
        merged_enum_constraints.update(skill_config.get("enum_constraints", {}) or {})
        skill_config["enum_constraints"] = merged_enum_constraints

        merged_enum_display_names = dict(global_enum_display_names)
        for slot, display_names in (skill_config.get("enum_display_names", {}) or {}).items():
            slot_display_names = dict(merged_enum_display_names.get(slot, {}) or {})
            slot_display_names.update(display_names or {})
            merged_enum_display_names[slot] = slot_display_names
        skill_config["enum_display_names"] = merged_enum_display_names

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


def load_scene_templates(path=DEFAULT_SCENE_TEMPLATE_PATH):
    data = load_yaml_file(path)
    scene_template_version = data.get("scene_template_version")
    if scene_template_version != SCENE_TEMPLATE_VERSION:
        raise ValueError(
            f"scene_template_version must be {SCENE_TEMPLATE_VERSION}, got {scene_template_version}"
        )

    template_id = data.get("template_id")
    if not template_id:
        raise ValueError("scene_templates.yaml missing template_id")
    template = data.get("template")
    ui_template = data.get("ui_template")
    if not template or not ui_template:
        raise ValueError("scene_templates.yaml missing template/ui_template")

    required_slots = data.get("required_slots")
    if not isinstance(required_slots, list) or not required_slots:
        raise ValueError("scene_templates.yaml required_slots must be a non-empty list")
    required_slot_set = set(required_slots)
    for field_name, field_template in (("template", template), ("ui_template", ui_template)):
        template_slots = set(extract_template_slots(field_template))
        if template_slots != required_slot_set:
            raise ValueError(
                f"scene {field_name} slots {sorted(template_slots)} "
                f"do not match required_slots {sorted(required_slot_set)}"
            )

    enum_constraints = data.get("enum_constraints", {}) or {}
    if not isinstance(enum_constraints, dict):
        raise ValueError("scene enum_constraints must be a dict")
    enum_display_names = data.get("enum_display_names", {}) or {}
    if not isinstance(enum_display_names, dict):
        raise ValueError("scene enum_display_names must be a dict")

    object_roles = data.get("object_roles", []) or []
    role_ids = [role.get("id") for role in object_roles if isinstance(role, dict)]
    if set(role_ids) != {"main", "other"}:
        raise ValueError("scene object_roles must contain main and other")

    return {
        "scene_template_version": scene_template_version,
        "template_id": template_id,
        "template": template,
        "ui_template": ui_template,
        "required_slots": required_slots,
        "slot_display_names": data.get("slot_display_names", {}) or {},
        "enum_constraints": enum_constraints,
        "enum_display_names": enum_display_names,
        "object_roles": object_roles,
    }


def split_text_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [
        item.strip()
        for item in re.split(r"[,，;；\n]+", str(value))
        if item.strip()
    ]


def join_scene_items(items):
    return ", ".join([str(item).strip() for item in items if str(item).strip()])


def scene_render_values(scene):
    scene_location = scene.get("scene_location") or {}
    objects = scene.get("objects") or []
    main_objects = [obj for obj in objects if obj.get("role") == "main"]
    other_objects = [obj for obj in objects if obj.get("role") == "other"]

    support_parts = [
        f"{obj.get('name')} at {obj.get('support_or_region')}"
        for obj in main_objects
        if str(obj.get("name", "")).strip() and str(obj.get("support_or_region", "")).strip()
    ]
    state_parts = []
    for obj in main_objects:
        states = split_text_list(obj.get("states"))
        if str(obj.get("name", "")).strip() and states:
            state_parts.append(f"{obj.get('name')} {join_scene_items(states)}")

    return {
        "space": scene_location.get("space", ""),
        "anchor": scene_location.get("anchor", ""),
        "main_objects": join_scene_items([obj.get("name") for obj in main_objects]),
        "support_or_region": "; ".join(support_parts),
        "object_states": "; ".join(state_parts),
        "other_objects": join_scene_items([obj.get("name") for obj in other_objects]) or "no other objects",
    }


def render_scene_text(scene, scene_template):
    return render_template(scene_template["template"], scene_render_values(scene))


def build_scene_from_values(scene_values, objects, scene_template):
    scene = {
        "task_type": str(scene_values.get("task_type", "")).strip(),
        "template_id": scene_template["template_id"],
        "scene_location": {
            "space": str(scene_values.get("space", "")).strip(),
            "anchor": str(scene_values.get("anchor", "")).strip(),
        },
        "objects": [],
        "text": "",
    }
    for obj in objects:
        normalized_obj = {
            "name": str(obj.get("name", "")).strip(),
            "role": str(obj.get("role", "")).strip(),
            "support_or_region": str(obj.get("support_or_region", "")).strip(),
            "states": split_text_list(obj.get("states")),
            "affordance": split_text_list(obj.get("affordance")),
        }
        if (
            normalized_obj["name"]
            or normalized_obj["support_or_region"]
            or normalized_obj["states"]
            or normalized_obj["affordance"]
        ):
            scene["objects"].append(normalized_obj)
    scene["text"] = render_scene_text(scene, scene_template)
    return scene


def validate_scene_enum(field_name, value, scene_template, prefix):
    allowed_values = scene_template.get("enum_constraints", {}).get(field_name, []) or []
    if allowed_values and value not in allowed_values:
        return f"{prefix} {field_name} 必须属于 {allowed_values}"
    return None


def validate_scene(scene, scene_template=None, prefix="scene"):
    if scene_template is None:
        scene_template = load_scene_templates()
    if not isinstance(scene, dict):
        return f"{prefix} 必须是 dict"

    unknown_keys = set(scene) - SCENE_ALLOWED_KEYS
    if unknown_keys:
        return f"{prefix} 出现未知字段: {sorted(unknown_keys)}"
    missing_keys = SCENE_ALLOWED_KEYS - set(scene)
    if missing_keys:
        return f"{prefix} 缺少字段: {sorted(missing_keys)}"

    if scene.get("template_id") != scene_template["template_id"]:
        return f"{prefix} template_id 必须是 {scene_template['template_id']}"
    scene_location = scene.get("scene_location")
    if not isinstance(scene_location, dict):
        return f"{prefix} scene_location 必须是 dict"
    unknown_location_keys = set(scene_location) - SCENE_LOCATION_ALLOWED_KEYS
    if unknown_location_keys:
        return f"{prefix}.scene_location 出现未知字段: {sorted(unknown_location_keys)}"
    missing_location_keys = SCENE_LOCATION_ALLOWED_KEYS - set(scene_location)
    if missing_location_keys:
        return f"{prefix}.scene_location 缺少字段: {sorted(missing_location_keys)}"
    if not str(scene_location.get("space", "")).strip():
        return f"{prefix}.scene_location space 不能为空"
    if not str(scene_location.get("anchor", "")).strip():
        return f"{prefix}.scene_location anchor 不能为空"

    for enum_field in ("task_type",):
        error = validate_scene_enum(enum_field, scene.get(enum_field, ""), scene_template, prefix)
        if error:
            return error

    objects = scene.get("objects")
    if not isinstance(objects, list) or not objects:
        return f"{prefix} objects 必须非空"

    role_ids = {
        role.get("id")
        for role in scene_template.get("object_roles", [])
        if isinstance(role, dict)
    }
    has_main_object = False
    affordance_enum = scene_template.get("enum_constraints", {}).get("affordance", []) or []
    for obj_idx, obj in enumerate(objects):
        obj_prefix = f"{prefix}.objects[{obj_idx}]"
        if not isinstance(obj, dict):
            return f"{obj_prefix} 必须是 dict"
        unknown_keys = set(obj) - SCENE_OBJECT_ALLOWED_KEYS
        if unknown_keys:
            return f"{obj_prefix} 出现未知字段: {sorted(unknown_keys)}"
        missing_keys = SCENE_OBJECT_ALLOWED_KEYS - set(obj)
        if missing_keys:
            return f"{obj_prefix} 缺少字段: {sorted(missing_keys)}"
        if not str(obj.get("name", "")).strip():
            return f"{obj_prefix} name 不能为空"
        role = obj.get("role")
        if role not in role_ids:
            return f"{obj_prefix} role 必须属于 {sorted(role_ids)}"
        if role == "main":
            has_main_object = True
            if not str(obj.get("support_or_region", "")).strip():
                return f"{obj_prefix} main object 的 support_or_region 不能为空"
        states = obj.get("states")
        if not isinstance(states, list) or not states:
            return f"{obj_prefix} states 必须非空 list"
        if not all(str(state).strip() for state in states):
            return f"{obj_prefix} states 不允许为空"
        affordance = obj.get("affordance")
        if not isinstance(affordance, list):
            return f"{obj_prefix} affordance 必须是 list"
        if affordance_enum:
            invalid_affordance = [
                item for item in affordance
                if str(item) not in [str(value) for value in affordance_enum]
            ]
            if invalid_affordance:
                return f"{obj_prefix} affordance 必须属于 {affordance_enum}: {invalid_affordance}"

    if not has_main_object:
        return f"{prefix} 至少需要一个 role=main 的 object"

    expected_text = render_scene_text(scene, scene_template)
    if scene.get("text") != expected_text:
        return f"{prefix} text 必须等于 scene template 自动渲染结果"
    return None


def get_skill(skill_id, skill_templates):
    if skill_id not in skill_templates:
        raise ValueError(f"unknown skill: {skill_id}")
    return skill_templates[skill_id]


def normalize_subject(subject):
    return LEGACY_SUBJECT_MAP.get(str(subject).strip(), str(subject).strip())


def default_robot_setup():
    return dict(DEFAULT_ROBOT_SETUP)


def infer_robot_setup_from_actions(actions, existing_setup=None):
    robot_setup = default_robot_setup()
    if isinstance(existing_setup, dict):
        for key in ROBOT_SETUP_ALLOWED_KEYS:
            value = str(existing_setup.get(key, "")).strip()
            if value:
                robot_setup[key] = value

    for action in actions:
        if not isinstance(action, dict):
            continue
        subject = str(action.get("subject", "")).strip()
        if subject == "left_gripper":
            robot_setup["left_effector_type"] = "gripper"
        elif subject == "right_gripper":
            robot_setup["right_effector_type"] = "gripper"
        elif subject == "both_grippers":
            robot_setup["left_effector_type"] = "gripper"
            robot_setup["right_effector_type"] = "gripper"

    return robot_setup


def iter_annotation_actions(annotation):
    if not isinstance(annotation, dict):
        return []
    actions = []
    for subtask in annotation.get("subtasks") or []:
        if isinstance(subtask, dict):
            actions.extend([
                action for action in (subtask.get("actions") or [])
                if isinstance(action, dict)
            ])
    return actions


def normalize_legacy_action(action, skill_templates):
    if not isinstance(action, dict):
        return action
    normalized = copy.deepcopy(action)
    normalized["subject"] = normalize_subject(normalized.get("subject", ""))
    if normalized.get("skill") in skill_templates and isinstance(normalized.get("slots"), dict):
        normalized["text"] = render_action_text(normalized, skill_templates[normalized["skill"]])
    return normalized


def normalize_legacy_annotation(annotation, skill_templates=None):
    if not isinstance(annotation, dict):
        return annotation
    if skill_templates is None:
        _, skill_templates = load_skill_templates()

    normalized = copy.deepcopy(annotation)
    scene = normalized.get("scene")
    if isinstance(scene, dict):
        normalized["scene"] = {
            key: value for key, value in scene.items()
            if key not in ("scene_level1", "scene_level2")
        }

    actions_before = iter_annotation_actions(normalized)
    normalized["robot_setup"] = infer_robot_setup_from_actions(
        actions_before,
        normalized.get("robot_setup"),
    )

    for subtask in normalized.get("subtasks") or []:
        if not isinstance(subtask, dict):
            continue
        actions = [
            normalize_legacy_action(action, skill_templates)
            for action in (subtask.get("actions") or [])
        ]
        subtask["actions"] = actions
        subtask["text"] = render_subtask_text(actions)

    return normalized


def render_template(template, values):
    rendered = template
    for slot in extract_template_slots(template):
        rendered = rendered.replace(f"[{slot}]", str(values.get(slot, "")))
    return rendered


def render_action_text(action, skill_config):
    values = dict(action.get("slots") or {})
    values["subject"] = normalize_subject(action.get("subject", ""))
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

    subject = normalize_subject(slot_values.get("subject", ""))
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
        slot_value = action.get("subject") if slot == "subject" else slots.get(slot)
        if str(slot_value) not in [str(value) for value in allowed_values]:
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

    is_none_subtask = actions[0].get("skill") == "none"
    if is_none_subtask and len(actions) != 1:
        return f"{prefix} none skill 只允许单 action"

    primary_subject = actions[0].get("subject")
    allowed_primary_subjects = coordination_modes[coordination_mode].get("allowed_primary_subjects")
    if not is_none_subtask and allowed_primary_subjects and primary_subject not in allowed_primary_subjects:
        return (
            f"{prefix} coordination_mode={coordination_mode} "
            f"不允许 primary subject={primary_subject}"
        )

    if not is_none_subtask and coordination_mode == "both_same_skill_same_object":
        error = validate_both_same_skill_same_object(actions, prefix)
        if error:
            return error

    expected_text = render_subtask_text(actions)
    if subtask.get("text") != expected_text:
        return f"{prefix} text 必须等于 actions[].text 自动拼接结果"

    return None


def validate_both_same_skill_same_object(actions, prefix):
    subjects = [action.get("subject") for action in actions]
    if len(actions) == 1:
        if subjects[0] not in ("both_effectors", "both_arms"):
            return (
                f"{prefix} both_same_skill_same_object 单 action 时 "
                "subject 必须是 both_effectors 或 both_arms"
            )
        return None

    if len(actions) != 2:
        return f"{prefix} both_same_skill_same_object 只允许 1 个 both action 或 2 个左右 action"

    subject_set = set(subjects)
    valid_subject_pairs = [
        {"left_effector", "right_effector"},
        {"left_arm", "right_arm"},
    ]
    if subject_set not in valid_subject_pairs:
        return (
            f"{prefix} both_same_skill_same_object 双 action 时 "
            "subject 必须是 left_effector+right_effector 或 left_arm+right_arm"
        )

    if actions[0].get("skill") != actions[1].get("skill"):
        return f"{prefix} both_same_skill_same_object 双 action 的 skill 必须相同"
    return None


def validate_robot_setup(robot_setup, prefix="robot_setup"):
    if not isinstance(robot_setup, dict):
        return f"{prefix} 必须是 dict"

    unknown_keys = set(robot_setup) - ROBOT_SETUP_ALLOWED_KEYS
    if unknown_keys:
        return f"{prefix} 出现未知字段: {sorted(unknown_keys)}"
    missing_keys = ROBOT_SETUP_ALLOWED_KEYS - set(robot_setup)
    if missing_keys:
        return f"{prefix} 缺少字段: {sorted(missing_keys)}"

    for field_name in sorted(ROBOT_SETUP_ALLOWED_KEYS):
        value = str(robot_setup.get(field_name, "")).strip()
        if value not in EFFECTOR_TYPE_ALLOWED_VALUES:
            return f"{prefix}.{field_name} 必须属于 {EFFECTOR_TYPE_ALLOWED_VALUES}"
    return None


def validate_episode(episode, prefix="episode"):
    if not isinstance(episode, dict):
        return f"{prefix} 必须是 dict"

    unknown_keys = set(episode) - EPISODE_ALLOWED_KEYS
    if unknown_keys:
        return f"{prefix} 出现未知字段: {sorted(unknown_keys)}"
    missing_keys = EPISODE_ALLOWED_KEYS - set(episode)
    if missing_keys:
        return f"{prefix} 缺少字段: {sorted(missing_keys)}"

    for field_name in ("episode_id", "task_id", "video_path", "primary_video_path"):
        if not str(episode.get(field_name, "")).strip():
            return f"{prefix} {field_name} 不能为空"

    dataset_name = episode.get("dataset_name")
    if dataset_name is None or not isinstance(dataset_name, str):
        return f"{prefix} dataset_name 必须是字符串"

    try:
        frames = int(episode.get("frames"))
    except (TypeError, ValueError):
        return f"{prefix} frames 必须是正整数"
    if frames <= 0:
        return f"{prefix} frames 必须是正整数"

    views = episode.get("views")
    if not isinstance(views, dict):
        return f"{prefix} views 必须是 dict"
    for view_name, view_path in views.items():
        if not str(view_name).strip():
            return f"{prefix} views 不允许空 view name"
        if not str(view_path).strip():
            return f"{prefix} views[{view_name}] 路径不能为空"

    return None


def validate_annotation(annotation, skill_templates=None, coordination_modes=None, scene_template=None):
    if skill_templates is None:
        _, skill_templates = load_skill_templates()
    if coordination_modes is None:
        coordination_modes = load_coordination_modes()
    if scene_template is None:
        scene_template = load_scene_templates()

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
    episode_error = validate_episode(annotation.get("episode"))
    if episode_error:
        return episode_error
    robot_setup_error = validate_robot_setup(annotation.get("robot_setup"))
    if robot_setup_error:
        return robot_setup_error
    if not str(annotation.get("video_text", "")).strip():
        return "video_text 不能为空"
    scene_error = validate_scene(annotation.get("scene"), scene_template)
    if scene_error:
        return scene_error

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
