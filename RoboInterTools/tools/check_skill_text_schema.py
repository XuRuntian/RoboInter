import copy
import os
import sys


COMMON_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "common")
if COMMON_DIR not in sys.path:
    sys.path.insert(0, COMMON_DIR)

from skill_schema import (
    SCHEMA_VERSION,
    TEMPLATE_SET_VERSION,
    build_scene_from_values,
    build_action_from_slot_values,
    extract_template_slots,
    load_coordination_modes,
    load_scene_templates,
    load_skill_templates,
    normalize_legacy_annotation,
    render_scene_text,
    render_subtask_text,
    validate_annotation,
    validate_scene,
)


TEMPLATE_VERSION, SKILLS = load_skill_templates()
COORDINATION_MODES = load_coordination_modes()
SCENE_TEMPLATE = load_scene_templates()


def pass_case(name):
    print(f"PASS {name}")


def assert_ok(name, annotation):
    error = validate_annotation(annotation, SKILLS, COORDINATION_MODES)
    if error:
        raise AssertionError(f"{name} should pass, got: {error}")
    pass_case(name)


def assert_fail(name, annotation):
    error = validate_annotation(annotation, SKILLS, COORDINATION_MODES)
    if not error:
        raise AssertionError(f"{name} should fail")
    print(f"PASS {name}: {error}")


def action(skill_id, values):
    return build_action_from_slot_values(skill_id, values, SKILLS)


def pull_values():
    return {
        "subject": "right_effector",
        "interaction_target": "drawer",
        "pull_anchor": "drawer handle",
        "source_anchor": "closed position",
        "destination_anchor": "open position",
        "changed_object": "drawer",
        "state_change": "opened",
    }


def both_pull_values():
    values = pull_values()
    values["subject"] = "both_effectors"
    return values


def pick_values():
    return {
        "subject": "left_effector",
        "manipulated_object": "cup",
        "source_anchor": "table",
        "grasp_anchor": "cup body",
        "grasp_method": "pinch",
    }


def right_pick_values():
    values = pick_values()
    values["subject"] = "right_effector"
    return values


def fold_values(subject, folded_part_anchor, state_change):
    return {
        "subject": subject,
        "manipulated_object": "shirt",
        "folded_part_anchor": folded_part_anchor,
        "fold_line_anchor": "sleeve seam",
        "fold_target_anchor": "shirt center",
        "changed_object": "shirt",
        "state_change": state_change,
    }


def place_values():
    return {
        "subject": "right_effector",
        "manipulated_object": "book",
        "placement_relation": "on",
        "destination_anchor": "table",
    }


def twist_values():
    return {
        "subject": "right_effector",
        "interaction_target": "bottle cap",
        "twist_anchor": "cap",
        "rotation_direction": "clockwise",
        "changed_object": "bottle",
        "state_change": "opened",
    }


def none_values():
    return {
        "subject": "both_arms",
    }


def subtask(start, end, coordination_mode, actions):
    return {
        "start_frame": start,
        "end_frame": end,
        "coordination_mode": coordination_mode,
        "text": render_subtask_text(actions),
        "actions": actions,
    }


def scene():
    return build_scene_from_values(
        {
            "task_type": "deformable_object_arrangement",
            "space": "bedroom",
            "anchor": "bed",
        },
        [
            {
                "name": "blue towel",
                "role": "main",
                "support_or_region": "tray",
                "states": ["unfolded"],
                "affordance": ["foldable", "graspable"],
            },
            {
                "name": "tray",
                "role": "main",
                "support_or_region": "table surface",
                "states": ["empty"],
                "affordance": ["receivable", "support_surface"],
            },
            {
                "name": "robot arm",
                "role": "other",
                "support_or_region": "",
                "states": ["visible"],
                "affordance": [],
            },
        ],
        SCENE_TEMPLATE,
    )


def annotation(subtasks):
    return {
        "schema_version": SCHEMA_VERSION,
        "template_set_version": TEMPLATE_SET_VERSION,
        "episode": {
            "episode_id": "chunk-000_episode_000003",
            "task_id": "chunk-000_episode_000003",
            "dataset_name": "Agilex_Cobot_Magic_fold_towel_blue_tray",
            "video_path": "/data/videos/cam_head_rgb/episode_000003.mp4",
            "primary_video_path": "/data/videos/cam_head_rgb/episode_000003.mp4",
            "views": {
                "cam_head_rgb": "/data/videos/cam_head_rgb/episode_000003.mp4",
                "cam_left_wrist_rgb": "/data/videos/cam_left_wrist_rgb/episode_000003.mp4",
            },
            "frames": 21,
        },
        "robot_setup": {
            "left_effector_type": "dexterous_hand",
            "right_effector_type": "dexterous_hand",
        },
        "video_text": "机器人完成抽屉和杯子的操作",
        "scene": scene(),
        "subtasks": subtasks,
    }


def main():
    if TEMPLATE_VERSION != TEMPLATE_SET_VERSION:
        raise AssertionError("skill_templates.yaml version mismatch")
    pass_case("skill_templates.yaml 能加载")

    if len(COORDINATION_MODES) != 6:
        raise AssertionError("coordination_modes.yaml should contain 6 modes")
    pass_case("coordination_modes.yaml 能加载")

    if SCENE_TEMPLATE["template_id"] != "scene_basic_v1":
        raise AssertionError("scene_templates.yaml template_id mismatch")
    if set(extract_template_slots(SCENE_TEMPLATE["template"])) != set(SCENE_TEMPLATE["required_slots"]):
        raise AssertionError("scene template slots mismatch required_slots")
    if "scene_level1" in SCENE_TEMPLATE["enum_constraints"]:
        raise AssertionError("scene_level1 enum should be removed")
    if "scene_level2" in SCENE_TEMPLATE["enum_constraints"]:
        raise AssertionError("scene_level2 enum should be removed")
    if "surface_cleaning" not in SCENE_TEMPLATE["enum_constraints"]["task_type"]:
        raise AssertionError("task_type enum missing surface_cleaning")
    expected_affordance = [
        "graspable",
        "pushable",
        "pullable",
        "pressable",
        "rotatable",
        "pourable",
        "receivable",
        "cuttable",
        "support_surface",
        "slidable",
        "insertable",
        "insert_slot",
        "foldable",
        "deformable",
        "shakeable",
        "strikeable",
        "throwable",
        "tool_usable",
        "hangable",
        "openable",
        "closable",
        "wipeable",
        "scrubbable",
    ]
    if SCENE_TEMPLATE["enum_constraints"]["affordance"] != expected_affordance:
        raise AssertionError("affordance enum mismatch")
    if SCENE_TEMPLATE["enum_display_names"]["task_type"]["surface_cleaning"] != "表面清洁":
        raise AssertionError("task_type display name mismatch")
    if SCENE_TEMPLATE["enum_display_names"]["affordance"]["receivable"] != "可接收液体/颗粒/物体":
        raise AssertionError("affordance display name mismatch")
    pass_case("scene_templates.yaml 能加载且 slots 一致")

    for skill_id, skill in SKILLS.items():
        if set(extract_template_slots(skill["template"])) != set(skill["required_slots"]):
            raise AssertionError(f"{skill_id} template slots mismatch required_slots")
    pass_case("每个 skill 的 template slots 和 required_slots 一致")

    if extract_template_slots(SKILLS["pull"]["template"]) != SKILLS["pull"]["required_slots"]:
        raise AssertionError("pull slots mismatch")
    pass_case("pull 的 UI slot 列表正确")

    if "left_effector" not in SKILLS["pull"]["enum_constraints"]["subject"]:
        raise AssertionError("subject enum missing left_effector")
    if SKILLS["pull"]["enum_display_names"]["subject"]["left_effector"] != "左末端":
        raise AssertionError("subject enum display name mismatch")
    if SKILLS["place"]["enum_display_names"]["placement_relation"]["on"] != "在...上":
        raise AssertionError("placement_relation display name mismatch")
    if SKILLS["twist"]["enum_display_names"]["rotation_direction"]["clockwise"] != "顺时针":
        raise AssertionError("rotation_direction display name mismatch")
    pass_case("subject/placement/twist 枚举中文显示名能加载")

    if SKILLS["none"]["display_name"] != "无任务相关操作":
        raise AssertionError("none display name mismatch")
    if SKILLS["none"]["required_slots"] != ["subject"]:
        raise AssertionError("none required slots mismatch")
    pass_case("none skill 能加载")

    base_scene = scene()
    expected_scene_text = (
        "In bedroom at bed, blue towel, tray are located at blue towel at tray; "
        "tray at table surface, blue towel unfolded; tray empty, "
        "robot arm are visible."
    )
    if base_scene["text"] != expected_scene_text:
        raise AssertionError(base_scene["text"])
    if validate_scene(base_scene, SCENE_TEMPLATE):
        raise AssertionError(validate_scene(base_scene, SCENE_TEMPLATE))
    pass_case("scene.text 从 object 结构自动生成英文")

    base_pull = action("pull", pull_values())
    base_pick = action("pick", pick_values())
    expected_pull_text = (
        "right_effector pull drawer at drawer handle from closed position "
        "to/toward open position, causing drawer to opened"
    )
    if base_pull["text"] != expected_pull_text:
        raise AssertionError(base_pull["text"])
    pass_case("action.text 自动生成正确")

    legacy_annotation = copy.deepcopy(annotation([subtask(0, 10, "primary_with_support", [base_pull])]))
    legacy_annotation.pop("robot_setup")
    legacy_action = legacy_annotation["subtasks"][0]["actions"][0]
    legacy_action["subject"] = "right_gripper"
    legacy_action["text"] = legacy_action["text"].replace("right_effector", "right_gripper")
    legacy_annotation["subtasks"][0]["text"] = legacy_action["text"]
    normalized_legacy = normalize_legacy_annotation(legacy_annotation, SKILLS)
    if normalized_legacy["robot_setup"]["right_effector_type"] != "gripper":
        raise AssertionError("legacy right_gripper should infer right_effector_type=gripper")
    if normalized_legacy["subtasks"][0]["actions"][0]["subject"] != "right_effector":
        raise AssertionError("legacy right_gripper should normalize to right_effector")
    if validate_annotation(normalized_legacy, SKILLS, COORDINATION_MODES):
        raise AssertionError(validate_annotation(normalized_legacy, SKILLS, COORDINATION_MODES))
    pass_case("legacy gripper subject 可迁移为 effector + robot_setup")

    none_action = action("none", none_values())
    expected_none_text = "both_arms performs no task-relevant manipulation"
    if none_action["text"] != expected_none_text:
        raise AssertionError(none_action["text"])
    pass_case("none action.text 自动生成正确")

    two_action_text = render_subtask_text([base_pull, base_pick])
    if "; meanwhile " not in two_action_text:
        raise AssertionError(two_action_text)
    pass_case("subtask.text 自动生成正确")

    assert_ok(
        "single_hand 下单 action 可以保存",
        annotation([subtask(0, 10, "single_hand", [base_pull])]),
    )
    both_pull = action("pull", both_pull_values())
    assert_ok(
        "both_effectors 允许 both_same_skill_same_object",
        annotation([subtask(0, 10, "both_same_skill_same_object", [both_pull])]),
    )
    left_fold = action("fold", fold_values("left_effector", "left sleeve", "left sleeve folded"))
    right_fold = action("fold", fold_values("right_effector", "right sleeve", "right sleeve folded"))
    assert_ok(
        "left_effector+right_effector 允许 both_same_skill_same_object",
        annotation([subtask(0, 10, "both_same_skill_same_object", [left_fold, right_fold])]),
    )
    assert_fail(
        "both_effectors 不允许 single_hand",
        annotation([subtask(0, 10, "single_hand", [both_pull])]),
    )
    assert_fail(
        "单侧 effector 单 action 不允许 both_same_skill_same_object",
        annotation([subtask(0, 10, "both_same_skill_same_object", [base_pull])]),
    )
    assert_fail(
        "both_same_skill_same_object 双 action 的 skill 必须相同",
        annotation([subtask(0, 10, "both_same_skill_same_object", [left_fold, action("pick", right_pick_values())])]),
    )
    assert_ok(
        "parallel_different_skills 下两个 action 可以保存",
        annotation([subtask(0, 10, "parallel_different_skills", [base_pull, base_pick])]),
    )
    assert_ok(
        "primary_with_support 下单 action 可以保存",
        annotation([subtask(0, 10, "primary_with_support", [base_pull])]),
    )
    assert_ok(
        "none 可作为末尾无任务相关操作片段保存",
        annotation([
            subtask(0, 10, "primary_with_support", [base_pull]),
            subtask(11, 20, "single_hand", [none_action]),
        ]),
    )
    assert_fail(
        "none 不允许同时包含辅助 action",
        annotation([subtask(0, 10, "parallel_different_skills", [none_action, base_pick])]),
    )

    place_action = action("place", place_values())
    assert_ok(
        "place.placement_relation 枚举校验有效",
        annotation([subtask(0, 10, "primary_with_support", [place_action])]),
    )
    twist_action = action("twist", twist_values())
    assert_ok(
        "twist.rotation_direction 枚举校验有效",
        annotation([subtask(0, 10, "primary_with_support", [twist_action])]),
    )

    bad = copy.deepcopy(annotation([subtask(0, 10, "primary_with_support", [base_pull])]))
    bad.pop("episode")
    assert_fail("缺 episode 报错", bad)

    bad = copy.deepcopy(annotation([subtask(0, 10, "primary_with_support", [base_pull])]))
    bad.pop("robot_setup")
    assert_fail("缺 robot_setup 报错", bad)

    bad = copy.deepcopy(annotation([subtask(0, 10, "primary_with_support", [base_pull])]))
    bad["robot_setup"]["left_effector_type"] = "human_hand"
    assert_fail("robot_setup effector_type 非法时报错", bad)

    bad = copy.deepcopy(annotation([subtask(0, 10, "primary_with_support", [base_pull])]))
    bad["episode"]["frames"] = 0
    assert_fail("episode.frames 非正数时报错", bad)

    bad = copy.deepcopy(annotation([subtask(0, 10, "primary_with_support", [base_pull])]))
    bad.pop("scene")
    assert_fail("缺 scene 报错", bad)

    bad = copy.deepcopy(annotation([subtask(0, 10, "primary_with_support", [base_pull])]))
    bad["scene"]["scene_level1"] = "Household"
    assert_fail("scene_level1 冗余字段报错", bad)

    bad = copy.deepcopy(annotation([subtask(0, 10, "primary_with_support", [base_pull])]))
    bad["scene"]["text"] = "中文场景文本"
    assert_fail("scene.text 非模板英文渲染时报错", bad)

    bad = copy.deepcopy(annotation([subtask(0, 10, "primary_with_support", [base_pull])]))
    bad["scene"]["scene_location"]["anchor"] = ""
    bad["scene"]["text"] = "In bedroom at , blue towel, tray are located at blue towel at tray; tray at table surface, blue towel unfolded; tray empty, robot arm are visible."
    assert_fail("scene_location.anchor 为空时报错", bad)

    bad = copy.deepcopy(annotation([subtask(0, 10, "primary_with_support", [base_pull])]))
    bad["scene"]["objects"][0]["affordance"] = "foldable"
    assert_fail("objects.affordance 不是 list 时报错", bad)

    bad = copy.deepcopy(annotation([subtask(0, 10, "primary_with_support", [base_pull])]))
    del bad["subtasks"][0]["actions"][0]["slots"]["destination_anchor"]
    assert_fail("缺 required slot 报错", bad)

    bad = copy.deepcopy(annotation([subtask(0, 10, "primary_with_support", [base_pull])]))
    bad["subtasks"][0]["actions"][0]["slots"]["extra_slot"] = "x"
    assert_fail("多余 slot 报错", bad)

    bad = copy.deepcopy(annotation([subtask(0, 10, "primary_with_support", [place_action])]))
    bad["subtasks"][0]["actions"][0]["slots"]["placement_relation"] = "inside"
    assert_fail("place.placement_relation 非法时报错", bad)

    bad = copy.deepcopy(annotation([subtask(0, 10, "primary_with_support", [base_pull])]))
    bad["subtasks"][0]["actions"][0]["subject"] = "human"
    bad["subtasks"][0]["actions"][0]["text"] = bad["subtasks"][0]["actions"][0]["text"].replace("right_effector", "human")
    bad["subtasks"][0]["text"] = bad["subtasks"][0]["actions"][0]["text"]
    assert_fail("subject 非法时报错", bad)

    bad = copy.deepcopy(annotation([subtask(0, 10, "primary_with_support", [twist_action])]))
    bad["subtasks"][0]["actions"][0]["slots"]["rotation_direction"] = "left"
    assert_fail("twist.rotation_direction 非法时报错", bad)

    bad = copy.deepcopy(annotation([subtask(0, 10, "primary_with_support", [base_pull])]))
    bad["subtasks"][0]["event_frame"] = 5
    assert_fail("出现 event_frame 报错", bad)

    bad = copy.deepcopy(annotation([subtask(0, 10, "primary_with_support", [base_pull])]))
    bad["subtasks"][0]["actions"][0]["contact_frame"] = 5
    assert_fail("出现 contact_frame 报错", bad)

    bad = copy.deepcopy(annotation([subtask(0, 10, "primary_with_support", [base_pull])]))
    bad["subtasks"][0]["description"] = "old"
    assert_fail("出现 description 报错", bad)

    bad = copy.deepcopy(annotation([subtask(0, 10, "primary_with_support", [base_pull])]))
    bad["subtasks"][0]["actions"][0]["template"] = "old"
    assert_fail("出现 template 报错", bad)

    bad = copy.deepcopy(annotation([subtask(0, 10, "primary_with_support", [base_pull])]))
    bad["subtasks"][0]["skill"] = "pull"
    assert_fail("subtask.skill 出现时报错", bad)

    bad = copy.deepcopy(annotation([subtask(0, 10, "bad_mode", [base_pull])]))
    assert_fail("coordination_mode 非法时报错", bad)

    bad = copy.deepcopy(annotation([subtask(0, 10, "primary_with_support", [base_pull])]))
    bad["subtasks"][0]["actions"][0]["skill"] = "bad_skill"
    assert_fail("action.skill 非法时报错", bad)

    assert_fail(
        "start_frame/end_frame 不连续时报错",
        annotation([
            subtask(0, 10, "primary_with_support", [base_pull]),
            subtask(12, 20, "primary_with_support", [base_pick]),
        ]),
    )


if __name__ == "__main__":
    main()
