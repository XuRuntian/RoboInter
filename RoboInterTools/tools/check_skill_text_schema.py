import copy
import os
import sys


COMMON_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "common")
if COMMON_DIR not in sys.path:
    sys.path.insert(0, COMMON_DIR)

from skill_schema import (
    SCHEMA_VERSION,
    TEMPLATE_SET_VERSION,
    build_action_from_slot_values,
    extract_template_slots,
    load_coordination_modes,
    load_skill_templates,
    render_subtask_text,
    validate_annotation,
)


TEMPLATE_VERSION, SKILLS = load_skill_templates()
COORDINATION_MODES = load_coordination_modes()


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
        "subject": "right_gripper",
        "interaction_target": "drawer",
        "pull_anchor": "drawer handle",
        "source_anchor": "closed position",
        "destination_anchor": "open position",
        "changed_object": "drawer",
        "state_change": "opened",
    }


def pick_values():
    return {
        "subject": "left_gripper",
        "manipulated_object": "cup",
        "source_anchor": "table",
        "grasp_anchor": "cup body",
        "grasp_method": "pinch",
    }


def place_values():
    return {
        "subject": "right_gripper",
        "manipulated_object": "book",
        "placement_relation": "on",
        "destination_anchor": "table",
    }


def twist_values():
    return {
        "subject": "right_gripper",
        "interaction_target": "bottle cap",
        "twist_anchor": "cap",
        "rotation_direction": "clockwise",
        "changed_object": "bottle",
        "state_change": "opened",
    }


def subtask(start, end, coordination_mode, actions):
    return {
        "start_frame": start,
        "end_frame": end,
        "coordination_mode": coordination_mode,
        "text": render_subtask_text(actions),
        "actions": actions,
    }


def annotation(subtasks):
    return {
        "schema_version": SCHEMA_VERSION,
        "template_set_version": TEMPLATE_SET_VERSION,
        "video_text": "机器人完成抽屉和杯子的操作",
        "subtasks": subtasks,
    }


def main():
    if TEMPLATE_VERSION != TEMPLATE_SET_VERSION:
        raise AssertionError("skill_templates.yaml version mismatch")
    pass_case("skill_templates.yaml 能加载")

    if len(COORDINATION_MODES) != 6:
        raise AssertionError("coordination_modes.yaml should contain 6 modes")
    pass_case("coordination_modes.yaml 能加载")

    for skill_id, skill in SKILLS.items():
        if set(extract_template_slots(skill["template"])) != set(skill["required_slots"]):
            raise AssertionError(f"{skill_id} template slots mismatch required_slots")
    pass_case("每个 skill 的 template slots 和 required_slots 一致")

    if extract_template_slots(SKILLS["pull"]["template"]) != SKILLS["pull"]["required_slots"]:
        raise AssertionError("pull slots mismatch")
    pass_case("pull 的 UI slot 列表正确")

    base_pull = action("pull", pull_values())
    base_pick = action("pick", pick_values())
    expected_pull_text = (
        "right_gripper pull drawer at drawer handle from closed position "
        "to/toward open position, causing drawer to opened"
    )
    if base_pull["text"] != expected_pull_text:
        raise AssertionError(base_pull["text"])
    pass_case("action.text 自动生成正确")

    two_action_text = render_subtask_text([base_pull, base_pick])
    if "; meanwhile " not in two_action_text:
        raise AssertionError(two_action_text)
    pass_case("subtask.text 自动生成正确")

    assert_ok(
        "single_hand 下单 action 可以保存",
        annotation([subtask(0, 10, "single_hand", [base_pull])]),
    )
    assert_ok(
        "parallel_different_skills 下两个 action 可以保存",
        annotation([subtask(0, 10, "parallel_different_skills", [base_pull, base_pick])]),
    )
    assert_ok(
        "primary_with_support 下单 action 可以保存",
        annotation([subtask(0, 10, "primary_with_support", [base_pull])]),
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
    del bad["subtasks"][0]["actions"][0]["slots"]["destination_anchor"]
    assert_fail("缺 required slot 报错", bad)

    bad = copy.deepcopy(annotation([subtask(0, 10, "primary_with_support", [base_pull])]))
    bad["subtasks"][0]["actions"][0]["slots"]["extra_slot"] = "x"
    assert_fail("多余 slot 报错", bad)

    bad = copy.deepcopy(annotation([subtask(0, 10, "primary_with_support", [place_action])]))
    bad["subtasks"][0]["actions"][0]["slots"]["placement_relation"] = "inside"
    assert_fail("place.placement_relation 非法时报错", bad)

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
