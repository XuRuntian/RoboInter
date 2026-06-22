import sys
import os
import argparse
import re
from PyQt5.QtCore import QPoint, QTimer, Qt
import cv2
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QPushButton, QMessageBox, QLineEdit, QDialogButtonBox, QTextEdit, QGridLayout,
                             QLabel, QSlider, QDialog, QHBoxLayout, QFrame, QProgressDialog, QRadioButton, QPlainTextEdit, QComboBox, QCheckBox,
                             QListWidget, QListWidgetItem)
from PyQt5.QtGui import QImage, QPixmap, QPainter, QColor, QMouseEvent
from PyQt5.QtCore import Qt, QRect, QPoint, pyqtSignal, QThread

import yaml, time
from utils import request_video_and_anno, save_anno, drawback_video, get_avaiable_username
import numpy as np

COMMON_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "common")
if COMMON_DIR not in sys.path:
    sys.path.insert(0, COMMON_DIR)

from skill_schema import (
    SCHEMA_VERSION,
    TEMPLATE_SET_VERSION,
    build_action_from_slot_values,
    build_scene_from_values,
    load_coordination_modes,
    load_scene_templates,
    load_skill_templates,
    render_scene_text,
    render_subtask_text,
    validate_annotation,
    validate_scene,
    validate_subtask,
)


TEMPLATE_SET_VERSION, SKILL_TEMPLATES = load_skill_templates()
COORDINATION_MODES = load_coordination_modes()
SCENE_TEMPLATE = load_scene_templates()
SKILL_LIST = list(SKILL_TEMPLATES.values())
DEFAULT_SKILL_ID = "manipulate" if "manipulate" in SKILL_TEMPLATES else SKILL_LIST[-1]["id"]
DEFAULT_COORDINATION_MODE = (
    "single_hand"
    if "single_hand" in COORDINATION_MODES
    else "primary_with_support"
    if "primary_with_support" in COORDINATION_MODES
    else next(iter(COORDINATION_MODES))
)


def get_subtask_display(subtask):
    if not isinstance(subtask, dict):
        return "", "", ""
    actions = subtask.get("actions") or []
    primary_skill = actions[0].get("skill", "") if actions else ""
    return subtask.get("text", ""), primary_skill, ""


class SceneInputDialog(QDialog):

    def __init__(self, initial_scene=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("场景标注")
        self.setFocusPolicy(Qt.StrongFocus)
        self.scene_result = None
        self.object_rows = []
        self.main_layout = QVBoxLayout(self)
        self.form_layout = QGridLayout()
        self.main_layout.addLayout(self.form_layout)

        initial_scene = initial_scene if isinstance(initial_scene, dict) else {}
        self.scene_level1_select = self.create_enum_combo("scene_level1", initial_scene.get("scene_level1", ""))
        self.scene_level2_select = self.create_enum_combo("scene_level2", initial_scene.get("scene_level2", ""))
        self.task_type_select = self.create_enum_combo("task_type", initial_scene.get("task_type", ""))
        initial_location = initial_scene.get("scene_location") or {}
        if not initial_location and initial_scene.get("scene_area"):
            initial_location = {"space": initial_scene.get("scene_area"), "anchor": ""}
        self.scene_space_input = QLineEdit(self)
        self.scene_space_input.setPlaceholderText("英文，例如 bathroom / bedroom / kitchen")
        self.scene_space_input.setText(initial_location.get("space", ""))
        self.scene_space_input.textChanged.connect(self.update_preview)
        self.scene_anchor_input = QLineEdit(self)
        self.scene_anchor_input.setPlaceholderText("英文，例如 toilet / bed / sink")
        self.scene_anchor_input.setText(initial_location.get("anchor", ""))
        self.scene_anchor_input.textChanged.connect(self.update_preview)

        row = 0
        self.form_layout.addWidget(QLabel("一级场景:", self), row, 0)
        self.form_layout.addWidget(self.scene_level1_select, row, 1)
        row += 1
        self.form_layout.addWidget(QLabel("二级场景:", self), row, 0)
        self.form_layout.addWidget(self.scene_level2_select, row, 1)
        row += 1
        self.form_layout.addWidget(QLabel("任务类型:", self), row, 0)
        self.form_layout.addWidget(self.task_type_select, row, 1)
        row += 1
        self.form_layout.addWidget(QLabel("任务所在空间:", self), row, 0)
        self.form_layout.addWidget(self.scene_space_input, row, 1)
        row += 1
        self.form_layout.addWidget(QLabel("任务场景锚点:", self), row, 0)
        self.form_layout.addWidget(self.scene_anchor_input, row, 1)
        row += 1

        template_box = QTextEdit(self)
        template_box.setReadOnly(True)
        template_box.setFixedSize(840, 55)
        template_box.setStyleSheet("background-color: #E3E3E3; font-weight: bold;")
        template_box.setText(SCENE_TEMPLATE["ui_template"])
        self.form_layout.addWidget(QLabel("场景模板:", self), row, 0)
        self.form_layout.addWidget(template_box, row, 1)

        object_title_layout = QHBoxLayout()
        object_title_layout.addWidget(QLabel("物体列表（请填写英文短语，界面显示中文，保存英文）", self))
        self.add_object_button = QPushButton("添加物体", self)
        self.add_object_button.clicked.connect(lambda: self.add_object_row({}))
        object_title_layout.addWidget(self.add_object_button)
        self.main_layout.addLayout(object_title_layout)

        self.objects_layout = QGridLayout()
        self.main_layout.addLayout(self.objects_layout)

        self.preview = QTextEdit(self)
        self.preview.setReadOnly(True)
        self.preview.setFixedSize(960, 70)
        self.preview.setStyleSheet("background-color: #E3E3E3; font-weight: bold;")
        self.main_layout.addWidget(QLabel("保存英文预览:", self))
        self.main_layout.addWidget(self.preview)

        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        self.button_box.button(QDialogButtonBox.Ok).setText("确定")
        self.button_box.button(QDialogButtonBox.Cancel).setText("取消")
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        self.main_layout.addWidget(self.button_box)

        initial_objects = initial_scene.get("objects") or [{}]
        for obj in initial_objects:
            self.add_object_row(obj)
        self.update_preview()

    def create_enum_combo(self, field_name, current_value):
        combo = QComboBox(self)
        combo.setFixedSize(360, 30)
        values = SCENE_TEMPLATE.get("enum_constraints", {}).get(field_name, []) or []
        display_names = SCENE_TEMPLATE.get("enum_display_names", {}).get(field_name, {}) or {}
        if values:
            combo.addItem("请选择", "")
            for value in values:
                label = display_names.get(value, value)
                combo.addItem(f"{label} ({value})", value)
            self.set_combo_by_data(combo, current_value)
        else:
            combo.setEditable(True)
            combo.setEditText(current_value or "")
        combo.currentIndexChanged.connect(self.update_preview)
        if combo.isEditable():
            combo.editTextChanged.connect(self.update_preview)
        return combo

    def create_role_combo(self, current_role):
        combo = QComboBox(self)
        for role in SCENE_TEMPLATE.get("object_roles", []):
            combo.addItem(role.get("display_name", role["id"]), role["id"])
        self.set_combo_by_data(combo, current_role or "main")
        combo.currentIndexChanged.connect(self.update_preview)
        combo.setFixedSize(130, 30)
        return combo

    def create_affordance_editor(self, selected_values):
        affordance_values = SCENE_TEMPLATE.get("enum_constraints", {}).get("affordance", []) or []
        display_names = SCENE_TEMPLATE.get("enum_display_names", {}).get("affordance", {}) or {}
        selected_values = [value for value in affordance_values if value in set(selected_values or [])]
        if not affordance_values:
            editor = QLineEdit(self)
            editor.setPlaceholderText("英文逗号分隔，例如 foldable, graspable")
            editor.setText(", ".join(selected_values))
            editor.textChanged.connect(self.update_preview)
            editor.setFixedSize(210, 30)
            return editor

        button = QPushButton(self)
        button.selected_affordance_values = selected_values
        button.affordance_options = affordance_values
        button.affordance_display_names = display_names
        button.setFixedSize(210, 30)
        button.clicked.connect(lambda: self.open_affordance_selector(button))
        self.update_affordance_button_text(button)
        return button

    def update_affordance_button_text(self, button):
        selected_values = getattr(button, "selected_affordance_values", [])
        display_names = getattr(button, "affordance_display_names", {})
        if not selected_values:
            button.setText("选择属性")
            button.setToolTip("")
            return
        display_items = [display_names.get(value, value) for value in selected_values]
        button.setText(f"已选 {len(selected_values)} 项")
        button.setToolTip(", ".join(
            f"{display_names.get(value, value)} ({value})" for value in selected_values
        ))

    def open_affordance_selector(self, button):
        dialog = QDialog(self)
        dialog.setWindowTitle("选择 affordance")
        dialog.setFixedSize(520, 520)
        layout = QVBoxLayout(dialog)

        affordance_list = QListWidget(dialog)
        affordance_list.setFixedSize(490, 430)
        selected_values = set(getattr(button, "selected_affordance_values", []))
        display_names = getattr(button, "affordance_display_names", {})
        for value in getattr(button, "affordance_options", []):
            item = QListWidgetItem(f"{display_names.get(value, value)} ({value})")
            item.setData(Qt.UserRole, value)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if value in selected_values else Qt.Unchecked)
            affordance_list.addItem(item)
        layout.addWidget(affordance_list)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, dialog)
        button_box.button(QDialogButtonBox.Ok).setText("确定")
        button_box.button(QDialogButtonBox.Cancel).setText("取消")
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)

        if dialog.exec_() == QDialog.Accepted:
            selected = []
            for idx in range(affordance_list.count()):
                item = affordance_list.item(idx)
                if item.checkState() == Qt.Checked:
                    selected.append(item.data(Qt.UserRole))
            button.selected_affordance_values = selected
            self.update_affordance_button_text(button)
            self.update_preview()

    def set_combo_by_data(self, combo, value):
        for idx in range(combo.count()):
            if combo.itemData(idx) == value:
                combo.setCurrentIndex(idx)
                return
        combo.setCurrentIndex(0)

    def combo_value(self, combo):
        data = combo.itemData(combo.currentIndex())
        if data is not None and data != "":
            return data
        return combo.currentText().strip()

    def split_input_list(self, text):
        return [item.strip() for item in re.split(r"[,，;；\n]+", text or "") if item.strip()]

    def affordance_values(self, widget):
        if isinstance(widget, QLineEdit):
            return self.split_input_list(widget.text())
        return list(getattr(widget, "selected_affordance_values", []))

    def add_object_row(self, obj):
        row_idx = len(self.object_rows) + 1
        if row_idx == 1:
            headers = ["物体英文名", "角色", "支撑/区域", "状态（英文逗号分隔）", "affordance", ""]
            for col, header in enumerate(headers):
                label = QLabel(header, self)
                label.setStyleSheet("font-weight: bold;")
                self.objects_layout.addWidget(label, 0, col)

        name_input = QLineEdit(self)
        name_input.setPlaceholderText("blue towel")
        name_input.setText(obj.get("name", ""))
        name_input.textChanged.connect(self.update_preview)
        name_input.setFixedSize(140, 30)

        role_select = self.create_role_combo(obj.get("role", "main"))

        support_input = QLineEdit(self)
        support_input.setPlaceholderText("tray / table surface")
        support_input.setText(obj.get("support_or_region", ""))
        support_input.textChanged.connect(self.update_preview)
        support_input.setFixedSize(160, 30)

        states_input = QLineEdit(self)
        states_input.setPlaceholderText("unfolded, empty")
        states_input.setText(", ".join(obj.get("states", []) or []))
        states_input.textChanged.connect(self.update_preview)
        states_input.setFixedSize(180, 30)

        affordance_editor = self.create_affordance_editor(obj.get("affordance", []) or [])
        remove_button = QPushButton("删除", self)
        remove_button.setFixedSize(70, 30)

        row_data = {
            "name": name_input,
            "role": role_select,
            "support_or_region": support_input,
            "states": states_input,
            "affordance": affordance_editor,
            "remove": remove_button,
        }
        remove_button.clicked.connect(lambda: self.remove_object_row(row_data))
        self.object_rows.append(row_data)
        self.render_object_rows()

    def render_object_rows(self):
        for row_idx, row_data in enumerate(self.object_rows, start=1):
            self.objects_layout.addWidget(row_data["name"], row_idx, 0)
            self.objects_layout.addWidget(row_data["role"], row_idx, 1)
            self.objects_layout.addWidget(row_data["support_or_region"], row_idx, 2)
            self.objects_layout.addWidget(row_data["states"], row_idx, 3)
            self.objects_layout.addWidget(row_data["affordance"], row_idx, 4)
            self.objects_layout.addWidget(row_data["remove"], row_idx, 5)

    def remove_object_row(self, row_data):
        if row_data not in self.object_rows:
            return
        self.object_rows.remove(row_data)
        for widget in row_data.values():
            widget.setParent(None)
            widget.deleteLater()
        self.update_preview()

    def collect_objects(self):
        objects = []
        for row_data in self.object_rows:
            objects.append({
                "name": row_data["name"].text().strip(),
                "role": self.combo_value(row_data["role"]),
                "support_or_region": row_data["support_or_region"].text().strip(),
                "states": self.split_input_list(row_data["states"].text()),
                "affordance": self.affordance_values(row_data["affordance"]),
            })
        return objects

    def collect_scene_values(self):
        return {
            "scene_level1": self.combo_value(self.scene_level1_select),
            "scene_level2": self.combo_value(self.scene_level2_select),
            "task_type": self.combo_value(self.task_type_select),
            "space": self.scene_space_input.text().strip(),
            "anchor": self.scene_anchor_input.text().strip(),
        }

    def build_scene(self):
        return build_scene_from_values(
            self.collect_scene_values(),
            self.collect_objects(),
            SCENE_TEMPLATE,
        )

    def update_preview(self):
        try:
            scene = self.build_scene()
            self.preview.setText(render_scene_text(scene, SCENE_TEMPLATE))
        except Exception:
            self.preview.clear()

    def accept(self):
        scene = self.build_scene()
        error = validate_scene(scene, SCENE_TEMPLATE)
        if error:
            QMessageBox.warning(self, "提示", error)
            return
        self.scene_result = scene
        super().accept()

    def get_scene_result(self):
        return self.scene_result


class TextInputDialog(QDialog):

    def __init__(self, initial_text='', parent=None, is_video=True, video_anno_json=None, origin_text=None):
        super().__init__(parent)
        self.setWindowTitle('请输入语言标注')
        self.setFocusPolicy(Qt.StrongFocus)
        self.is_video = is_video
        self.video_anno_json = video_anno_json or {}
        self.clip_result = None
        self.slot_widgets = {}
        self.secondary_slot_widgets = {}
        self.main_layout = QGridLayout(self)
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        self.button_box.button(QDialogButtonBox.Ok).setText("确定")
        self.button_box.button(QDialogButtonBox.Cancel).setText("取消")

        if is_video:
            global_instruction_C = self.video_anno_json.get('instructionC', '')
            self.text_title = QLabel('输入语言标注:', self)
            self.text_input = QPlainTextEdit(self)
            self.text_input.setPlainText(global_instruction_C if initial_text is None or len(initial_text) == 0 else initial_text)
            self.text_input.setFixedSize(500, 50)
            self.main_layout.addWidget(self.text_title, 0, 0)
            self.main_layout.addWidget(self.text_input, 0, 1)
            self.main_layout.addWidget(self.button_box, 1, 0, 1, 2)
        else:
            self.initial_clip = initial_text
            self.build_clip_ui(initial_text)

        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

    def build_clip_ui(self, initial_clip):
        subtask = initial_clip if isinstance(initial_clip, dict) else {}
        actions = subtask.get("actions") or []
        primary_action = actions[0] if actions else {}
        secondary_action = actions[1] if len(actions) > 1 else {}
        selected_skill = primary_action.get("skill") or DEFAULT_SKILL_ID

        self.skill_select = QComboBox()
        self.skill_select.setFixedSize(400, 30)
        self.populate_skill_combo(self.skill_select, selected_skill)

        self.coordination_select = QComboBox()
        self.coordination_select.setFixedSize(400, 30)
        coord_mode = subtask.get("coordination_mode") or DEFAULT_COORDINATION_MODE
        self.populate_coordination_combo(coord_mode, primary_action.get("subject"))

        self.template_preview = QTextEdit(self)
        self.template_preview.setReadOnly(True)
        self.template_preview.setFixedSize(760, 55)
        self.template_preview.setStyleSheet("background-color: #E3E3E3;")

        self.description_preview = QTextEdit(self)
        self.description_preview.setReadOnly(True)
        self.description_preview.setFixedSize(760, 70)
        self.description_preview.setStyleSheet("background-color: #E3E3E3; font-weight: bold;")

        self.primary_slots_layout = QHBoxLayout()
        self.secondary_enable = QCheckBox("添加辅助动作", self)
        self.secondary_skill_select = QComboBox()
        self.secondary_skill_select.setFixedSize(400, 30)
        self.populate_skill_combo(self.secondary_skill_select, secondary_action.get("skill") or selected_skill)
        self.secondary_slots_layout = QHBoxLayout()

        row = 0
        self.main_layout.addWidget(QLabel("选择技能:", self), row, 0)
        self.main_layout.addWidget(self.skill_select, row, 1)
        row += 1
        self.main_layout.addWidget(QLabel("协同方式:", self), row, 0)
        self.main_layout.addWidget(self.coordination_select, row, 1)
        row += 1
        self.main_layout.addWidget(QLabel("动作提示:", self), row, 0)
        self.main_layout.addWidget(self.template_preview, row, 1)
        row += 1
        self.main_layout.addWidget(QLabel("主动作填空:", self), row, 0)
        self.main_layout.addLayout(self.primary_slots_layout, row, 1)
        row += 1
        self.main_layout.addWidget(self.secondary_enable, row, 0)
        self.main_layout.addWidget(self.secondary_skill_select, row, 1)
        row += 1
        self.main_layout.addWidget(QLabel("辅助动作填空:", self), row, 0)
        self.main_layout.addLayout(self.secondary_slots_layout, row, 1)
        row += 1
        self.main_layout.addWidget(QLabel("自动生成文本:", self), row, 0)
        self.main_layout.addWidget(self.description_preview, row, 1)
        row += 1
        self.main_layout.addWidget(self.button_box, row, 0, 1, 2)

        self.primary_initial_values = self.action_to_slot_values(primary_action)
        self.secondary_initial_values = self.action_to_slot_values(secondary_action)
        self.secondary_enable.setChecked(bool(secondary_action))
        self.secondary_skill_select.setVisible(self.secondary_enable.isChecked())

        self.skill_select.currentIndexChanged.connect(self.on_skill_changed)
        self.secondary_skill_select.currentIndexChanged.connect(self.on_secondary_skill_changed)
        self.coordination_select.currentIndexChanged.connect(self.update_description_preview)
        self.secondary_enable.stateChanged.connect(self.on_secondary_toggled)

        self.render_primary_slots(selected_skill, self.primary_initial_values)
        self.render_secondary_slots(self.combo_data(self.secondary_skill_select), self.secondary_initial_values)
        self.update_coordination_options()
        self.on_secondary_toggled()
        self.update_description_preview()

    def populate_skill_combo(self, combo, current_skill):
        for skill in SKILL_LIST:
            skill_id = skill["id"]
            combo.addItem(f'{skill.get("display_name", skill_id)} ({skill_id})', skill_id)
        self.set_combo_by_data(combo, current_skill)

    def populate_coordination_combo(self, current_mode=None, primary_subject=None):
        current_mode = current_mode or self.combo_data(self.coordination_select) or DEFAULT_COORDINATION_MODE
        self.coordination_select.blockSignals(True)
        self.coordination_select.clear()
        for mode_id, mode in COORDINATION_MODES.items():
            if self.coordination_mode_allows_subject(mode_id, primary_subject):
                self.coordination_select.addItem(mode.get("display_name", mode_id), mode_id)
        if self.coordination_select.count() == 0:
            for mode_id, mode in COORDINATION_MODES.items():
                self.coordination_select.addItem(mode.get("display_name", mode_id), mode_id)
        self.set_combo_by_data(self.coordination_select, current_mode)
        self.coordination_select.blockSignals(False)

    def coordination_mode_allows_subject(self, mode_id, subject):
        if not subject:
            return True
        allowed_subjects = COORDINATION_MODES.get(mode_id, {}).get("allowed_primary_subjects")
        return not allowed_subjects or subject in allowed_subjects

    def set_combo_by_data(self, combo, value):
        for idx in range(combo.count()):
            if combo.itemData(idx) == value:
                combo.setCurrentIndex(idx)
                return
        combo.setCurrentIndex(0)

    def combo_data(self, combo):
        return combo.itemData(combo.currentIndex()) or combo.currentText()

    def action_to_slot_values(self, action):
        values = {}
        if isinstance(action, dict):
            values.update(action.get("slots") or {})
            if action.get("subject"):
                values["subject"] = action["subject"]
        return values

    def clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def create_slot_widgets(self, layout, skill_id, values):
        widgets = {}
        skill_config = SKILL_TEMPLATES.get(skill_id, SKILL_TEMPLATES[DEFAULT_SKILL_ID])
        enum_constraints = skill_config.get("enum_constraints", {})
        enum_display_names = skill_config.get("enum_display_names", {})
        slot_display_names = skill_config.get("slot_display_names", {})
        ui_template = skill_config.get("ui_template") or skill_config["template"]
        parts = re.split(r"(\[[^\]]+\])", ui_template)
        for part in parts:
            if not part:
                continue
            slot_match = re.fullmatch(r"\[([^\]]+)\]", part)
            if not slot_match:
                label = QLabel(part, self)
                label.setStyleSheet("font-weight: bold;")
                layout.addWidget(label)
                continue

            slot = slot_match.group(1)
            placeholder = slot_display_names.get(slot, slot)
            if slot in enum_constraints:
                widget = QComboBox(self)
                display_names = enum_display_names.get(slot, {})
                for value in enum_constraints[slot]:
                    label = display_names.get(value, value)
                    widget.addItem(f"{label} ({value})", value)
                if values.get(slot):
                    for idx in range(widget.count()):
                        if widget.itemData(idx) == values[slot]:
                            widget.setCurrentIndex(idx)
                            break
                if slot == "subject":
                    widget.currentIndexChanged.connect(self.on_primary_subject_changed)
                else:
                    widget.currentIndexChanged.connect(self.update_description_preview)
            else:
                widget = QLineEdit(self)
                widget.setPlaceholderText(placeholder)
                widget.setText(values.get(slot, ""))
                widget.textChanged.connect(self.update_description_preview)
            widget.setFixedSize(150 if slot != "subject" else 130, 30)
            layout.addWidget(widget)
            widgets[slot] = widget
        return widgets

    def render_primary_slots(self, skill_id, values=None):
        self.clear_layout(self.primary_slots_layout)
        self.slot_widgets = self.create_slot_widgets(self.primary_slots_layout, skill_id, values or {})

    def render_secondary_slots(self, skill_id, values=None):
        self.clear_layout(self.secondary_slots_layout)
        self.secondary_slot_widgets = self.create_slot_widgets(self.secondary_slots_layout, skill_id, values or {})
        self.set_layout_visible(self.secondary_slots_layout, self.secondary_enable.isChecked())

    def set_layout_visible(self, layout, visible):
        for idx in range(layout.count()):
            item = layout.itemAt(idx)
            widget = item.widget()
            if widget is not None:
                widget.setVisible(visible)

    def on_skill_changed(self):
        skill_id = self.combo_data(self.skill_select)
        self.primary_initial_values = {}
        self.render_primary_slots(skill_id)
        self.update_coordination_options()
        self.update_description_preview()

    def on_secondary_skill_changed(self):
        self.secondary_initial_values = {}
        self.render_secondary_slots(self.combo_data(self.secondary_skill_select))
        self.update_description_preview()

    def on_secondary_toggled(self):
        enabled = self.secondary_enable.isChecked()
        self.secondary_skill_select.setVisible(enabled)
        self.set_layout_visible(self.secondary_slots_layout, enabled)
        self.update_description_preview()

    def current_primary_subject(self):
        subject_widget = self.slot_widgets.get("subject")
        if subject_widget is None:
            return None
        return self.widget_value(subject_widget)

    def update_coordination_options(self):
        self.populate_coordination_combo(primary_subject=self.current_primary_subject())

    def on_primary_subject_changed(self):
        self.update_coordination_options()
        self.update_description_preview()

    def widget_value(self, widget):
        if isinstance(widget, QComboBox):
            return widget.itemData(widget.currentIndex()) or widget.currentText()
        return widget.text().strip()

    def collect_slot_values(self, widgets):
        return {slot: self.widget_value(widget) for slot, widget in widgets.items()}

    def render_current_description(self):
        skill_id = self.combo_data(self.skill_select)
        actions = [self.build_action(skill_id, self.slot_widgets, allow_empty=True)]
        if self.secondary_enable.isChecked():
            secondary_skill = self.combo_data(self.secondary_skill_select)
            actions.append(self.build_action(secondary_skill, self.secondary_slot_widgets, allow_empty=True))
        return render_subtask_text(actions)

    def update_description_preview(self):
        if self.is_video:
            return
        skill_id = self.combo_data(self.skill_select)
        skill_config = SKILL_TEMPLATES.get(skill_id, SKILL_TEMPLATES[DEFAULT_SKILL_ID])
        ui_template = skill_config.get("ui_template") or skill_config["template"]
        end_frame_definition = skill_config.get("end_frame_definition", "")
        self.template_preview.setText(ui_template)
        if end_frame_definition:
            self.template_preview.setText(f"{ui_template}\n结束帧定义: {end_frame_definition}")
        self.description_preview.setText(self.render_current_description())

    def build_action(self, skill_id, widgets, allow_empty=False):
        values = self.collect_slot_values(widgets)
        return build_action_from_slot_values(
            skill_id, values, SKILL_TEMPLATES, allow_empty=allow_empty
        )

    def build_clip_result(self):
        skill_id = self.combo_data(self.skill_select)
        actions = [self.build_action(skill_id, self.slot_widgets)]
        if self.secondary_enable.isChecked():
            secondary_skill = self.combo_data(self.secondary_skill_select)
            actions.append(self.build_action(secondary_skill, self.secondary_slot_widgets))
        return {
            "coordination_mode": self.combo_data(self.coordination_select),
            "text": render_subtask_text(actions),
            "actions": actions,
        }

    def validate_action_widgets(self, skill_id, widgets, action_name):
        skill_config = SKILL_TEMPLATES.get(skill_id, SKILL_TEMPLATES[DEFAULT_SKILL_ID])
        for slot in skill_config.get("required_slots", []):
            widget = widgets.get(slot)
            if widget is None or not self.widget_value(widget):
                return f"{action_name} 缺少必填 slot: {slot}"
        return None

    def validate_clip_inputs(self):
        error = self.validate_action_widgets(self.combo_data(self.skill_select), self.slot_widgets, "primary action")
        if error:
            return error
        if self.secondary_enable.isChecked():
            return self.validate_action_widgets(
                self.combo_data(self.secondary_skill_select),
                self.secondary_slot_widgets,
                "secondary action",
            )
        return None

    def accept(self):
        if not self.is_video:
            error = self.validate_clip_inputs()
            if error:
                QMessageBox.warning(self, "提示", error)
                return
            try:
                self.clip_result = self.build_clip_result()
            except ValueError as exc:
                QMessageBox.warning(self, "提示", str(exc))
                return
        super().accept()

    def get_text(self):
        return self.text_input.toPlainText() if self.is_video else self.build_clip_result()["text"]

    def get_prim(self):
        if self.is_video:
            return ''
        actions = self.build_clip_result().get("actions") or []
        return actions[0].get("skill", "") if actions else ""

    def get_select_lang(self):
        return ''

    def get_structured_result(self):
        if self.is_video:
            return None
        return self.clip_result or self.build_clip_result()


class ObjectAnnotationDialog(QDialog):
    
    def __init__(self, object_size, frame_number, keyframes, parent=None):
        super().__init__(parent)
        self.setWindowTitle('请输入物体标注')
        self.setFocusPolicy(Qt.StrongFocus)
        self.main_layout = QGridLayout(self)
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        self.button_box.button(QDialogButtonBox.Ok).setText("确定")
        self.button_box.button(QDialogButtonBox.Cancel).setText("取消")
        # add object size input box
        self.object_size = object_size
        self.start_frame_id = [0] + keyframes
        for idx, start_idx in enumerate(self.start_frame_id):
            
            if idx == len(self.start_frame_id)-1:
                end_idx = frame_number - 1
            else:
                end_idx = self.start_frame_id[idx+1] - 1
            
            self.main_layout.addWidget(QLabel(f'视频范围: [{start_idx+1}:{end_idx+1}]', self), idx, 0)
            select_button = QComboBox()
            select_button.addItems([f"物体{i+1}" for i in range(self.object_size)])
            select_button.setFixedSize(100, 30)
            select_button.setCurrentIndex(idx if idx < self.object_size else -1)
            self.main_layout.addWidget(select_button, idx, 1)
        
        self.main_layout.addWidget(self.button_box, len(self.start_frame_id), 0, 1, 2)
        # self.main_layout.itemAt(self.object_size*2-1).widget().setText(str(frame_number))
        
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
    
    def get_obj_id(self):
        return [self.main_layout.itemAt(i+1).widget().currentIndex() + 1 for i in range(0, len(self.start_frame_id)*2, 2)]
    
    def get_frame_id(self):
        return [int(self.main_layout.itemAt(i).widget().text().split('[')[1].split(':')[0]) for i in range(0, len(self.start_frame_id)*2, 2)]
    
    def get_result(self):
        return dict(zip(self.get_frame_id(), self.get_obj_id()))
    

class VideoPlayer(QWidget):
    def __init__(self, args):
        super().__init__()
        self.setWindowTitle("RoboInter 标注工具")
        ###########################################################
        #################### Main Area Layout ####################
        ###########################################################
        main_layout = QHBoxLayout()     
        self.mode, self.username, self.ip_address, self.port, self.time = self.mode_choose()
        if self.mode == '语言标注':
            #resize the window
            self.setFixedSize(1500, 760)
        else:
            self.setFixedSize(1900, 730)
        ###########################################################
        #################### Video Area Layout ####################
        ###########################################################
        video_layout = QVBoxLayout()
        # Video display label
        self.video_label = QLabel(self)
        self.video_label.setMouseTracking(True)
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_views_layout = QGridLayout()
        self.video_views_layout.addWidget(self.video_label, 0, 0)
        video_layout.addLayout(self.video_views_layout)
        # Progress slider
        self.progress_slider = QSlider(self)
        self.progress_slider.setOrientation(Qt.Horizontal)  
        self.progress_slider.valueChanged.connect(self.seek_video)
        self.progress_slider.hide()  # Hide initially
        video_layout.addWidget(self.progress_slider)
        # Keyframe indicator bar
        self.keyframe_bar = QLabel(self)
        self.keyframe_bar.setFixedHeight(10) 
        self.keyframe_bar.setMouseTracking(True)
        self.keyframe_bar.setAlignment(Qt.AlignCenter)  
        self.keyframe_bar.installEventFilter(self)  
        video_layout.addWidget(self.keyframe_bar)
        # Dynamic frame position label that floats above the slider
        self.frame_position_label = QLabel(self)
        self.frame_position_label.setStyleSheet("background-color: #E3E3E3;")
        self.frame_position_label.setAlignment(Qt.AlignCenter)
        self.frame_position_label.setFixedSize(150, 30)
        self.frame_position_label.hide()
        video_control_button_layout = QHBoxLayout()
        # Video position label
        self.video_position_label = QLabel(self)
        self.video_position_label.setStyleSheet("background-color: #E3E3E3;")
        self.video_position_label.setAlignment(Qt.AlignCenter)
        if self.mode != '语言标注':
            self.video_position_label.setFixedSize(130, 30)
        else:
            self.video_position_label.setFixedSize(310, 30)
        video_control_button_layout.addWidget(self.video_position_label)
        self.hist_num_label = QLabel(self)
        self.hist_num_label.setStyleSheet("background-color: #E3E3E3;")
        self.hist_num_label.setAlignment(Qt.AlignCenter)
        if self.mode != '语言标注':
            self.hist_num_label.setFixedSize(160, 30)
        else:
            self.hist_num_label.setFixedSize(310, 30)
        video_control_button_layout.addWidget(self.hist_num_label)
        
        if self.mode != '语言标注':
            self.one_num_label = QLabel(self)
            self.one_num_label.setStyleSheet("background-color: #E3E3E3;")
            self.one_num_label.setAlignment(Qt.AlignCenter)
            self.one_num_label.setFixedSize(270, 30)
            video_control_button_layout.addWidget(self.one_num_label)
        
        if self.mode != '语言标注':
            self.two_num_label = QLabel(self)
            self.two_num_label.setStyleSheet("background-color: #E3E3E3;")
            self.two_num_label.setAlignment(Qt.AlignCenter)
            self.two_num_label.setFixedSize(270, 30)
            video_control_button_layout.addWidget(self.two_num_label)
        
        if self.mode != '语言标注':
            self.three_num_label = QLabel(self)
            self.three_num_label.setStyleSheet("background-color: #E3E3E3;")
            self.three_num_label.setAlignment(Qt.AlignCenter)
            self.three_num_label.setFixedSize(270, 30)
            video_control_button_layout.addWidget(self.three_num_label)
        
        # Next video button
        video_layout.addLayout(video_control_button_layout)
        video_load_button_layout = QHBoxLayout()
        self.play_button = QPushButton("播放", self)
        self.play_button.setCheckable(True)
        self.play_button.clicked.connect(self.toggle_playback)
        video_load_button_layout.addWidget(self.play_button)
        
        # 标注次数选择
        if self.mode != '语言标注':
            self.re_annotation_text = QLabel("质检次数: ", self)
            self.re_annotation_text.setFixedSize(80, 30)
            video_load_button_layout.addWidget(self.re_annotation_text)
            self.re_annotation_button = QComboBox()
            self.re_annotation_button.setFixedSize(80, 30)
            self.re_annotation_button.addItem('0')
            self.re_annotation_button.addItem('1')
            self.re_annotation_button.addItem('2')
            self.re_annotation_button.addItem('3')
            self.re_annotation_button.setCurrentIndex(self.time)
            text_sep = QLabel(' ')
            text_sep.setFixedSize(40, 30)
            video_load_button_layout.addWidget(self.re_annotation_button)
            video_load_button_layout.addWidget(text_sep)
            # video_load_button_layout.addStretch(1)
            # 检测状态变化
            self.re_annotation_button.currentIndexChanged.connect(self.check_re_anno)
        
        # 选择是否完成
        if self.mode != '语言标注':
            self.is_finished_button = QCheckBox("完成", self)
            self.is_finished_button.setChecked(False)
            self.is_finished_button.setFixedSize(80, 30)
            self.is_finished_button.toggled.connect(self.change_hard_button)
            video_load_button_layout.addWidget(self.is_finished_button)
            self.is_finished_button.hide()
            
            self.is_hard_sample_button = QCheckBox("困难样本", self)
            self.is_hard_sample_button.setChecked(False)
            self.is_hard_sample_button.setFixedSize(110, 30)
            self.is_hard_sample_button.toggled.connect(self.change_finish_button)
            video_load_button_layout.addWidget(self.is_hard_sample_button)
            self.is_hard_sample_button.hide()

            text_sep = QLabel(' ')
            text_sep.setFixedSize(40, 30)
            video_load_button_layout.addWidget(text_sep)
        
        
        # 复选框
        self.is_pre_button = QCheckBox("返回上一条", self)
        self.is_pre_button.setChecked(False)
        self.is_pre_button.setFixedSize(100, 30)
        self.is_pre_button.setDisabled(True)
        # 检测状态变化
        self.is_pre_button.toggled.connect(self.set_button_text)
        video_load_button_layout.addWidget(self.is_pre_button)
        
        
        self.next_button = QPushButton("保存并加载", self)
        self.next_button.clicked.connect(self.next_video_and_load)
        video_load_button_layout.addWidget(self.next_button)
        video_layout.addLayout(video_load_button_layout)
        main_layout.addLayout(video_layout)
        ###########################################################
        ######################## Separator ########################
        ###########################################################
        separator = QFrame()
        separator.setFrameShape(QFrame.VLine)
        separator.setFrameShadow(QFrame.Sunken)
        main_layout.addWidget(separator)
        ###########################################################
        #################### Toolbar Area Layout ##################
        ###########################################################
        self.toolbar_layout = QVBoxLayout()
        # Auto-annotation function title layout
        function_title_layout = QHBoxLayout()
        function_title = QLabel("分割标注工具区", self)
        function_title.setAlignment(Qt.AlignLeft)  # Left align the title
        function_title.setStyleSheet("color: grey; font-weight: bold;")  # Set font color and weight
        function_title_layout.addWidget(function_title)
        fline = QFrame(self)
        fline.setFrameShape(QFrame.HLine)
        fline.setFrameShadow(QFrame.Sunken)
        fline.setStyleSheet("color: grey;")  # Set the same color as the title
        function_title_layout.addWidget(fline)
        self.sam_object_layout = QHBoxLayout()
        if self.mode != '语言标注':
            self.toolbar_layout.addLayout(function_title_layout)
            # run button
            self.button_param_select = QComboBox()
            self.button_param_select.addItem('双向视频模式')
            self.button_param_select.addItem('正向视频模式')
            self.button_param_select.addItem('反向视频模式')
            self.button_param_select.setFixedSize(150, 30)
            self.sam_object_layout.addWidget(self.button_param_select)
        
        # sam pre object button
        self.sam_pre_button = QPushButton("上一个物体", self)
        self.sam_pre_button.clicked.connect(self.pre_sam_object)
        self.sam_pre_button.setDisabled(True)
        # sam object position label
        self.sam_obj_pos_label = QLabel(self)
        self.sam_obj_pos_label.setStyleSheet("background-color: #E3E3E3;")
        self.sam_obj_pos_label.setAlignment(Qt.AlignCenter)
        self.sam_obj_pos_label.setFixedSize(150, 30)
        # sam next object button
        self.sam_next_button = QPushButton("下一个物体", self)
        self.sam_next_button.clicked.connect(self.next_sam_object)
        self.sam_next_button.setDisabled(True)
        self.sam_object_layout.addWidget(self.sam_pre_button)
        self.sam_object_layout.addWidget(self.sam_obj_pos_label)
        self.sam_object_layout.addWidget(self.sam_next_button)
        if self.mode != '语言标注':
            self.toolbar_layout.addLayout(self.sam_object_layout)

        # edit mode are layout
        annotation_title_layout = QHBoxLayout()
        annotation_title = QLabel("标注编辑区", self)
        annotation_title.setAlignment(Qt.AlignLeft)  # Left align the title
        annotation_title.setStyleSheet("color: grey; font-weight: bold;")  # Set font color and weight
        annotation_title_layout.addWidget(annotation_title)
        annoline = QFrame(self)
        annoline.setFrameShape(QFrame.HLine)
        annoline.setFrameShadow(QFrame.Sunken)
        annoline.setStyleSheet("color: grey;")  # Set the same color as the title
        annotation_title_layout.addWidget(annoline)
        if self.mode != '语言标注':
            self.toolbar_layout.addLayout(annotation_title_layout)
        # clear all button
        self.control_button_layout = QHBoxLayout()
        self.clear_all_button = QPushButton("删除全部标注", self)
        self.clear_all_button.clicked.connect(self.clear_annotations)
        self.control_button_layout.addWidget(self.clear_all_button)
        # remove last button
        self.remove_last_button = QPushButton("删除上一个标注", self)
        self.remove_last_button.clicked.connect(self.remove_last_annotation)
        self.control_button_layout.addWidget(self.remove_last_button)
        # remove frame button
        self.remove_frame_button = QPushButton("删除当前物体标注", self)
        self.remove_frame_button.clicked.connect(self.remove_obj_annotation)
        self.control_button_layout.addWidget(self.remove_frame_button)
        # save button
        if self.mode != '语言标注':
            self.toolbar_layout.addLayout(self.control_button_layout)

        # Video language annotation area
        lang_layout = QVBoxLayout()
        lang_title_layout = QHBoxLayout()
        lang_title = QLabel("视频语言标注显示区", self)
        lang_title.setAlignment(Qt.AlignLeft)  # Left align the title
        lang_title.setStyleSheet("color: grey; font-weight: bold;")  # Set font color and weight
        lang_title_layout.addWidget(lang_title)
        videoline = QFrame(self)
        videoline.setFrameShape(QFrame.HLine)
        videoline.setFrameShadow(QFrame.Sunken)
        videoline.setStyleSheet("color: grey;")  # Set the same color as the title
        lang_title_layout.addWidget(videoline)
        lang_layout.addLayout(lang_title_layout)
        # Video Language annotation show area
        self.video_lang_input = QTextEdit(self)
        self.video_lang_input.setReadOnly(True)
        self.video_lang_input.setFixedSize(610, 70)
        self.video_lang_input.setStyleSheet("background-color: #E3E3E3; font-weight: bold;")
        lang_layout.addWidget(self.video_lang_input)

        scene_button_layout = QHBoxLayout()
        self.scene_anno_button = QPushButton("添加/修改场景标注", self)
        self.scene_anno_button.clicked.connect(self.add_scene_annotation)
        scene_button_layout.addWidget(self.scene_anno_button)
        lang_layout.addLayout(scene_button_layout)

        self.scene_lang_input = QTextEdit(self)
        self.scene_lang_input.setReadOnly(True)
        self.scene_lang_input.setFixedSize(610, 95)
        self.scene_lang_input.setStyleSheet("background-color: #E3E3E3; font-weight: bold;")
        lang_layout.addWidget(self.scene_lang_input)
        
        # Video clip language annotation area 
        lang_title_layout = QHBoxLayout()
        clip_title = QLabel("视频片段语言标注显示区", self)
        clip_title.setAlignment(Qt.AlignLeft)  # Left align the title
        clip_title.setStyleSheet("color: grey; font-weight: bold;")  # Set font color and weight
        lang_title_layout.addWidget(clip_title)
        clipline = QFrame(self)
        clipline.setFrameShape(QFrame.HLine)
        clipline.setFrameShadow(QFrame.Sunken)
        clipline.setStyleSheet("color: grey;")  # Set the same color as the title
        lang_title_layout.addWidget(clipline)
        lang_layout.addLayout(lang_title_layout)
        # Video clip Language annotation show area
        self.clip_lang_input = QTextEdit(self)
        self.clip_lang_input.setReadOnly(True)
        self.clip_lang_input.setFixedSize(610, 100)
        self.clip_lang_input.setStyleSheet("background-color: #E3E3E3; font-weight: bold;")
        lang_layout.addWidget(self.clip_lang_input)
        
        if self.mode == '分割标注':
            # 删除语言标注区域
            self.video_lang_input.hide()
            self.scene_anno_button.hide()
            self.scene_lang_input.hide()
            self.clip_lang_input.hide()
            clip_title.hide()
            lang_title.hide()
            clipline.hide()
            videoline.hide()
            tips_items = ['A: 上一帧', 'D: 下一帧', 'W: 标记接触帧', 'S: 标记物体分段帧', '退格键: 删除标记帧', 'L: 绑定物体顺序']
            self.sam_time = "first"

        elif self.mode == '语言标注':
            fline.hide()
            self.sam_pre_button.hide()
            self.sam_next_button.hide()
            self.sam_obj_pos_label.hide()
            self.keyframe_bar.hide()
            function_title.hide()
            annotation_title.hide()
            annoline.hide()
            self.clear_all_button.hide()
            self.remove_last_button.hide()
            self.remove_frame_button.hide()
            tips_items = ['W: 标志开始帧','S: 标记结束帧','F: 播放/暂停视频', '退格键: 删除标记段','A: 上一帧','回车: 添加视频标注','G: 场景标注','D: 下一帧', 'L: 修改视频段语言']
            
            preview_clip_layout = QVBoxLayout()
            preview_lang_title_layout = QHBoxLayout()
            preview_clip_title = QLabel("视频段可用语言预览", self)
            preview_clip_title.setAlignment(Qt.AlignLeft)  # Left align the title
            preview_clip_title.setStyleSheet("color: grey; font-weight: bold;")  # Set font color and weight
            preview_lang_title_layout.addWidget(preview_clip_title)
            preview_clipline = QFrame(self)
            preview_clipline.setFrameShape(QFrame.HLine)
            preview_clipline.setFrameShadow(QFrame.Sunken)
            preview_clipline.setStyleSheet("color: grey;")  # Set the same color as the title
            preview_lang_title_layout.addWidget(preview_clipline)
            preview_clip_layout.addLayout(preview_lang_title_layout)
            # Video clip Language annotation show area
            self.preview_clip_lang_input = QTextEdit(self)
            self.preview_clip_lang_input.setReadOnly(True)
            self.preview_clip_lang_input.setFixedSize(610, 160)
            self.preview_clip_lang_input.setStyleSheet("background-color: #E3E3E3; font-weight: bold;")
            preview_clip_layout.addWidget(self.preview_clip_lang_input)
            lang_layout.addLayout(preview_clip_layout)
            self.toolbar_layout.addLayout(lang_layout)
              
        self.tips_layout = QVBoxLayout()
        self.tips_title_layout = QHBoxLayout()
        tips_title = QLabel("快捷键", self)
        tips_title.setAlignment(Qt.AlignLeft)  # Left align the title
        tips_title.setStyleSheet("color: grey; font-weight: bold;")  # Set font color and weight
        self.tips_title_layout.addWidget(tips_title)
        line = QFrame(self)
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        line.setStyleSheet("color: grey;")  # Set the same color as the title
        self.tips_title_layout.addWidget(line)
        self.tips_layout.addLayout(self.tips_title_layout)
        self.toolbar_layout.addLayout(self.tips_layout)
        self.tips_text_layout = QGridLayout()
        
        for i, item in enumerate(tips_items):
            tips_input = QTextEdit(self)
            tips_input.setText(item)
            tips_input.setReadOnly(True)
            tips_input.setSizeAdjustPolicy(QTextEdit.AdjustToContents)
            if self.mode != '语言标注':
                tips_input.setFixedSize(240, 30)
            else:
                tips_input.setFixedSize(200, 30)
            
            if self.mode == '语言标注':
                num_per_line = 3
            else:
                num_per_line = 2

            line = int(i // num_per_line)
            self.tips_text_layout.addWidget(tips_input, line, i % num_per_line)
        
        self.toolbar_layout.addLayout(self.tips_text_layout)
        
        if self.mode != '语言标注':
            # 添加视频名称展示区域
            video_name_layout = QHBoxLayout()
            video_name_title = QLabel("视频名称: ", self)
            video_name_title.setAlignment(Qt.AlignLeft)
            video_name_title.setStyleSheet("color: grey; font-weight: bold;")
            video_name_layout.addWidget(video_name_title)
            self.video_name_input = QLineEdit(self)
            self.video_name_input.setReadOnly(True)
            self.video_name_input.setAlignment(Qt.AlignLeft)
            self.video_name_input.setStyleSheet("color: grey; font-weight: bold;")
            self.video_name_input.setFixedSize(610, 30)
            video_name_layout.addWidget(self.video_name_input)
            self.toolbar_layout.addLayout(video_name_layout)
        
        main_layout.addLayout(self.toolbar_layout)
        self.setLayout(main_layout)

        self.cur_video_idx = 1
        self.video_position_label.setText(f"帧: -/-")
        if self.mode != '语言标注':
            self.sam_obj_pos_label.setText("物体: -/-")
        self.timer = QTimer()
        self.timer.timeout.connect(self.play_video)

        ##############################################################
        ##################### initialize Configs #####################
        ##############################################################
        config_path = "./config/config.yaml"
        with open(self.get_exe_path(config_path), "r") as f:
            self.model_config = yaml.load(f, Loader=yaml.FullLoader)
        self.sam_config = self.model_config["sam"]
        self.co_tracker_config = self.model_config["cotracker"]

        ##############################################################
        #################### initialize Variables ####################
        ##############################################################
        self.frame_count = 0
        self.is_stop = False
        self.current_frame = 0
        self.is_first = True
        self.last_frame = None
        self.ori_video = {}
        self.vis_track_res = False
        self.sam_anno = False
        self.lang_anno = dict()
        self.scene_annotation = None
        self.max_point_num = dict()
        self.video_2_lang = dict()
        self.loaded_lang_annotation = None
        self.cur_frame_idx = self.progress_slider.value()
        self.keyframes = {} 
        self.selected_keyframe = None 
        self.key_frame_mode = 'start'
        self.sam_point_anno = dict()
        self.lang_only_anno = dict()
        self.video_path = None
        self.primary_video_path = None
        self.frame_contact = set()
        
        self.next_video_and_load(is_first=True)
        
    def change_finish_button(self):
        if self.is_hard_sample_button.isChecked():
            self.is_finished_button.setDisabled(True)
        else:
            self.is_finished_button.setDisabled(False)
    
    def change_hard_button(self):
        if self.is_finished_button.isChecked():
            self.is_hard_sample_button.setDisabled(True)
        else:
            self.is_hard_sample_button.setDisabled(False)

    def ask_yes_no(self, title, text, default_yes=True):
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Question)
        msg.setWindowTitle(title)
        msg.setText(text)
        yes_button = msg.addButton("是", QMessageBox.YesRole)
        no_button = msg.addButton("否", QMessageBox.NoRole)
        msg.setDefaultButton(yes_button if default_yes else no_button)
        msg.exec_()
        return msg.clickedButton() == yes_button
    
    def closeEvent(self, event):
        if self.ask_yes_no('确认退出', '你确定要退出吗？', default_yes=False):
            event.accept()
            if self.mode == '语言标注':
                drawback_video(self.ip_address, self.port, self.video_path, 'lang')
            else:
                drawback_video(self.ip_address, self.port, self.video_path, 'sam', self.username)
        else:
            event.ignore()
    
    def check_re_anno(self):
        if self.re_annotation_button.currentText() == '0':
            self.is_pre_button.setDisabled(False)
            self.is_finished_button.show()
            self.is_hard_sample_button.hide()
        elif self.re_annotation_button.currentText() == '1':
            if not self.has_one_anno:
                self.smart_message("暂无需要一次复检的视频，请耐心等待")
                self.re_annotation_button.setCurrentIndex(0)
                return
            else:
                self.is_pre_button.setDisabled(False)
                self.is_finished_button.show()
                # self.is_hard_sample_button.hide()
                self.is_hard_sample_button.setText("问题样本")
                self.is_hard_sample_button.show()
        elif self.re_annotation_button.currentText() == '2':
            if not self.has_two_anno:
                self.smart_message("暂无需要二次复检的视频，请耐心等待")
                self.re_annotation_button.setCurrentIndex(0)
                return
            else:
                self.is_pre_button.setDisabled(False)
                self.is_finished_button.show()
                # self.is_hard_sample_button.hide()
                self.is_hard_sample_button.setText("问题样本")
                self.is_hard_sample_button.show()
        elif self.re_annotation_button.currentText() == '3':
            if not self.has_three_anno:
                self.smart_message("暂无需要三次复检的视频，请耐心等待")
                self.re_annotation_button.setCurrentIndex(0)
                return
            else:
                self.is_pre_button.setDisabled(False)
                self.is_finished_button.show()
                self.is_hard_sample_button.setText("困难样本")
                self.is_hard_sample_button.show()
              
    def get_exe_path(self, relative_path):
        try:
            base_path = sys._MEIPASS
        except AttributeError:
            base_path = os.path.abspath(".")
    
        return os.path.normpath(os.path.join(base_path, relative_path))
      
    def set_button_text(self):
        if self.is_pre_button.isChecked():
            self.next_button.setText("加载上一个视频")
        else:
            self.next_button.setText("保存并进行下一次标注")
    
    def mode_choose(self):
        
        # 在主窗口上直接弹出对话框，选择模式
        dialog = QDialog(self)
        dialog.setWindowTitle("选择模式")
        dialog.setFixedSize(500, 300)
        # center the dialog
        # desktop = QApplication.desktop()
        # dialog.move(int(desktop.width()*0.4), int(desktop.height()*0.4))
        
        dialog_layout = QVBoxLayout()
        dialog.setLayout(dialog_layout)
        
        
        # 添加用户名字输入框
        username_layout = QHBoxLayout()
        username_label = QLabel("请输入用户名: ", self)
        username_label.setFixedSize(150, 30)
        username_layout.addWidget(username_label)
        
        user_name = QLineEdit(self)
        user_name.setPlaceholderText("请输入用户名")
        user_name.setFixedSize(275, 30)
        username_layout.addWidget(user_name)
        dialog_layout.addLayout(username_layout)
        
        ip_address_layout = QHBoxLayout()
        ip_address_label = QLabel("请输入服务器地址: ", self)
        ip_address_label.setFixedSize(150, 30)
        ip_address_layout.addWidget(ip_address_label)
        
        ip_address = QLineEdit(self)
        ip_address.setPlaceholderText("服务器地址")
        ip_address.setFixedSize(180, 30)
        ip_address_layout.addWidget(ip_address)
        
        port = QLineEdit(self)
        port.setPlaceholderText("端口地址")
        port.setFixedSize(80, 30)
        ip_address_layout.addWidget(port)
        dialog_layout.addLayout(ip_address_layout)
        
        mode_layout = QHBoxLayout()
        mode_label = QLabel("请选择标注模式: ", self)
        mode_label.setFixedSize(150, 30)
        mode_layout.addWidget(mode_label)
        
        self.mode_select = QComboBox()
        self.mode_select.addItem('语言标注')
        self.mode_select.addItem('分割标注')
        self.mode_select.setFixedSize(275, 30)
        self.mode_select.currentIndexChanged.connect(self.check_anno_mode)
        mode_layout.addWidget(self.mode_select)
        dialog_layout.addLayout(mode_layout)
        
        time_layout = QHBoxLayout()
        self.time_label = QLabel("请选择质检次数: ", self)
        self.time_label.setFixedSize(150, 30)
        time_layout.addWidget(self.time_label)
        self.time_select = QComboBox()
        self.time_select.addItem('0')
        self.time_select.addItem('1')
        self.time_select.addItem('2')
        self.time_select.addItem('3')
        self.time_select.setFixedSize(275, 30)
        time_layout.addWidget(self.time_select)
        dialog_layout.addLayout(time_layout)

        self.time_label.hide()
        self.time_select.hide()
        
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        button_box.button(QDialogButtonBox.Ok).setText("确定")
        button_box.button(QDialogButtonBox.Cancel).setText("取消")
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        dialog_layout.addWidget(button_box)
        if dialog.exec_() == QDialog.Accepted:
            if len(user_name.text()) == 0 or len(ip_address.text()) == 0:
                self.smart_message("用户名和服务器地址不能为空")
                sys.exit()
        else:
            sys.exit()
            
        while True:
            username = user_name.text().strip()
            ipaddress = ip_address.text().strip()
            ip_port = port.text().strip() 
            username = get_avaiable_username(ipaddress, ip_port, username)
            if username == '':
                self.smart_message("用户名不存在，请重新输入")
                dialog.exec_()
            else:
                break
            
        return self.mode_select.currentText(), username, ipaddress, ip_port, int(self.time_select.currentText())
    
    def check_anno_mode(self):
        if self.mode_select.currentText() == '分割标注':
            self.time_label.show()
            self.time_select.show()
        else:
            self.time_label.hide()
            self.time_select.hide()

    def pre_sam_object(self):
        if self.sam_object_id[self.progress_slider.value()] > 0:
            self.sam_object_id[self.progress_slider.value()] -= 1
        if self.sam_object_id[self.progress_slider.value()] == 0:
            self.sam_pre_button.setDisabled(True)
        
        self.sam_next_button.setDisabled(False)
        cur_id = self.sam_object_id[self.progress_slider.value()] + 1
        all_object_size = len(self.tracking_points_sam[self.progress_slider.value()])
        self.sam_obj_pos_label.setText(f"标注物体: {cur_id}/{all_object_size}")
        
        self.draw_image()
    
    def resizeEvent(self, event):
        self.seek_video()
        self.clear_keyframes()
        self.update_keyframe_bar()
        
        self.setAutoFillBackground(False)
        palette = self.palette()
        # palette.setBrush(self.backgroundRole(), QBrush(QPixmap('./demo/bg.png').scaled(self.size(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)))
        self.setPalette(palette)
        # if  len(self.ori_video)>0 and self.mode == '语言标注':
        self.keyframe_bar.show()
        # else:
        #     self.keyframe_bar.hide()
    
    def next_sam_object(self):
        
        self.sam_object_id[self.progress_slider.value()] += 1
        if self.sam_object_id[self.progress_slider.value()] == len(self.tracking_points_sam[self.progress_slider.value()]):
            self.tracking_points_sam[self.progress_slider.value()].append(
                dict(pos=[], raw_pos=[], neg=[], raw_neg=[], labels=[])
            )
        self.sam_pre_button.setDisabled(False)
        
        if len(self.tracking_points_sam[self.progress_slider.value()][self.sam_object_id[self.progress_slider.value()]]['pos']) == 0:
            self.sam_next_button.setDisabled(True)
        else:
            self.sam_next_button.setDisabled(False)
        
        cur_id = self.sam_object_id[self.progress_slider.value()] + 1
        all_object_size = len(self.tracking_points_sam[self.progress_slider.value()])
        self.sam_obj_pos_label.setText(f"标注物体: {cur_id}/{all_object_size}")
        
        self.draw_image()
    
    def next_video_and_load(self, is_first=False):
        if is_first:
            self.load_video_async()
        else:            
            if self.has_anno() and not self.is_pre_button.isChecked():
                if not self.ask_yes_no("提示", "确认保存并加载下一个视频？"):
                    return
                self.video_position_label.setText(f"帧: -/-")
                if self.mode == '语言标注':
                    res = self.save_lang_anno()
                else:
                    res = self.save_sam_anno()
                
                if res == -1:
                    return
                self.clear_video()
                self.load_video_async()
            
            elif self.is_pre_button.isChecked():
                self.clear_video()
                self.load_video_async()
            
            elif self.is_finished_button.isChecked() and self.mode != '语言标注': 
                res = self.save_sam_anno()
                if res == -1:
                    return
                self.load_video_async()
            
            elif self.is_hard_sample_button.isChecked() and self.mode != '语言标注':
                res = self.save_sam_anno()
                if res == -1:
                    return
                self.load_video_async()
            
            else:
                self.smart_message("请先完成当前视频的标注")

        return

    def has_anno(self):
        if self.mode == '语言标注':
            return any(key != (0, 0) for key in self.lang_anno)
        else:
            for i in self.tracking_points_sam:
                if len(self.tracking_points_sam[i][0]['pos']) > 0:
                    return True
            return False
    
    def next_frame(self):
        if self.cur_frame_idx < self.frame_count - 1:
            self.cur_frame_idx += 1
        else:
            return
        self.video_position_label.setText(f"帧: {self.cur_frame_idx}/{self.frame_count}")
        self.sam_object_id[self.cur_frame_idx] = 0
        
        if self.sam_object_id[self.cur_frame_idx] == 0:
            self.sam_pre_button.setDisabled(True)     
        
        self.update_frame(self.cur_frame_idx)
        self.progress_slider.setValue(self.cur_frame_idx)
        
        cur_id = self.sam_object_id[self.progress_slider.value()] + 1
        all_object_size = len(self.tracking_points_sam[self.progress_slider.value()])
        self.sam_obj_pos_label.setText(f"标注物体: {cur_id}/{all_object_size}")   
        
        video_text = self.lang_anno.get((0, 0), "")
        self.video_lang_input.setText(f"视频整体描述: {video_text}" if video_text else "")
        
        anno_loc, (clip_text, prim, origin_text) = self.get_clip_description()
        anno_loc = anno_loc[1]
        if anno_loc is not None:
            self.clip_lang_input.setText(f"开始帧: {anno_loc[0]+1} | 结束帧: {anno_loc[1]+1}\n原子动作: {prim}\n动作描述: {clip_text}")
        else:
            self.clip_lang_input.setText('')
        
    def pre_frame(self):
        if self.cur_frame_idx >= 1:
            self.cur_frame_idx -= 1
        else:
            return
        self.video_position_label.setText(f"帧: {self.cur_frame_idx+1}/{self.frame_count}")
        self.sam_object_id[self.cur_frame_idx] = 0
        
        if self.sam_object_id[self.cur_frame_idx] == 0:
            self.sam_pre_button.setDisabled(True)
        
        self.sam_next_button.setDisabled(False)
        self.update_frame(self.cur_frame_idx)
        self.progress_slider.setValue(self.cur_frame_idx)
        
        cur_id = self.sam_object_id[self.progress_slider.value()] + 1
        all_object_size = len(self.tracking_points_sam[self.progress_slider.value()])
        self.sam_obj_pos_label.setText(f"物体标注: {cur_id}/{all_object_size}")
        
        video_text = self.lang_anno.get((0, 0), "")
        self.video_lang_input.setText(f"视频整体描述: {video_text}" if video_text else "")
        
        anno_loc, (clip_text, prim, origin_text) = self.get_clip_description()
        anno_loc = anno_loc[1]
        if anno_loc is not None:
            self.clip_lang_input.setText(f"开始帧: {anno_loc[0]+1} | 结束帧: {anno_loc[1]+1}\n原子动作: {prim}\n动作描述: {clip_text}")
        else:
            self.clip_lang_input.setText('') 
    
    def request_video(self):
        # try:
        if self.is_pre_button.isChecked():
            self.button_mode = 'pre'
            self.is_pre_button.setChecked(False)
            self.is_pre_button.setDisabled(True)
        else:
            if not self.is_first:
                self.is_pre_button.setDisabled(False)
            self.is_pre_button.setChecked(False)
            self.button_mode = 'next'
        if self.mode == '语言标注':
            return request_video_and_anno(self.ip_address, self.port, 'lang', self.username, self.button_mode, self.video_path)
        else:
            re_anno = int(self.re_annotation_button.currentText())
            return request_video_and_anno(self.ip_address, self.port, 'sam', self.username, self.button_mode, self.video_path, re_anno)
        
        # except Exception as e:
        #     if self.mode == '语言标注':
        #         return None
        #     else:
        #         return None
               
    def request_video_async(self):
        class VideoThread(QThread):
            finished = pyqtSignal(object)
            def __init__(self, parent):
                super().__init__()
                self.parent = parent
            def run(self):
                res = self.parent.request_video()
                try_count = 0
                while res is None:
                    if try_count > 3:
                        break
                    time.sleep(3)
                    res = self.parent.request_video()
                    try_count += 1
                if try_count > 3:
                    raise Exception("请求视频失败")
                self.finished.emit(res)
        video_thread = VideoThread(self)
        return video_thread
       
    def save_lang_anno(self):
        self.progress = QProgressDialog("请等待，正在储存标注结果...", None, 0, 0, self)
        self.progress.setWindowModality(Qt.WindowModal)
        self.progress.setCancelButton(None)
        self.progress.setMinimumDuration(0)
        self.progress.show()
        
        if self.validate_lang_clip_coverage() == -1:
            self.progress.close()
            return -1
        video_text = self.lang_anno.get((0, 0), "").strip()
        if not video_text:
            self.progress.close()
            self.smart_message("请按回车标注整体视频描述")
            return -1
        if not self.scene_annotation:
            self.progress.close()
            self.smart_message("请先完成场景标注")
            return -1

        lang_res = {
            "schema_version": SCHEMA_VERSION,
            "template_set_version": TEMPLATE_SET_VERSION,
            "video_text": video_text,
            "scene": self.scene_annotation,
            "subtasks": [],
        }
        clip_items = sorted((key, value) for key, value in self.lang_anno.items() if key != (0, 0))
        for clip_range, lang in clip_items:
            if not isinstance(lang, dict):
                self.progress.close()
                self.smart_message(f"请完成帧{clip_range[0]}到帧{clip_range[1]}之前的语言标注")
                return -1
            subtask = dict(lang)
            subtask["start_frame"] = clip_range[0]
            subtask["end_frame"] = clip_range[1]
            error = validate_subtask(subtask, SKILL_TEMPLATES, COORDINATION_MODES)
            if error:
                self.progress.close()
                self.smart_message(error)
                return -1
            lang_res["subtasks"].append(subtask)

        error = validate_annotation(lang_res, SKILL_TEMPLATES, COORDINATION_MODES, SCENE_TEMPLATE)
        if error:
            self.progress.close()
            self.smart_message(error)
            return -1

        save_metadata = {
            "user": self.username,
            "video_path": self.video_path,
            "primary_video_path": self.primary_video_path or self.video_path,
        }
        res = save_anno(self.ip_address, self.port, self.save_path, lang_res, save_metadata)
        try_time = 0
        while not res:
            if try_time > 3:
                break
            self.smart_message("保存失败，进行第{}次重试".format(try_time+1))
            time.sleep(4)
            res = save_anno(self.ip_address, self.port, self.save_path, lang_res, save_metadata)
            try_time += 1
        
        if not res:
            self.progress.close()
            self.smart_message("保存失败，即将退出系统重启软件")
            drawback_video(self.ip_address, self.port, self.video_path, 'lang')
            sys.exit()
            
        self.progress.close()
        self.lang_anno = dict()
        self.scene_annotation = None
        return 0

    def validate_lang_clip_coverage(self):
        clip_ranges = sorted(key for key in self.lang_anno if key != (0, 0))
        if len(clip_ranges) == 0:
            self.smart_message("请至少标注一个视频片段")
            return -1

        expected_start = None
        for start_frame, end_frame in clip_ranges:
            if expected_start is not None and start_frame != expected_start:
                self.smart_message(
                    f"视频片段不连续：上一段结束后应从第{expected_start + 1}帧开始，"
                    f"但下一段从第{start_frame + 1}帧开始"
                )
                return -1

            if end_frame < start_frame:
                self.smart_message(f"视频片段帧范围错误：第{start_frame + 1}帧到第{end_frame + 1}帧")
                return -1

            lang = self.lang_anno[(start_frame, end_frame)]
            if not isinstance(lang, dict) or not lang.get("text"):
                self.smart_message(f"请完成帧{start_frame + 1}到帧{end_frame + 1}之间的语言标注")
                return -1

            expected_start = end_frame + 1

        return 0
    
    def clear_annotations(self):
        self.tracking_points_sam = dict()
        for k in range(self.frame_count):
            self.tracking_points_sam[k] = [
                dict(pos=[], raw_pos=[], neg=[], raw_neg=[], labels=[])
            ]
        self.lang_anno = dict()
        self.scene_annotation = None
        self.update_scene_display()
        self.sam_next_button.setDisabled(False)
        self.sam_pre_button.setDisabled(True)
        self.sam_object_id[self.progress_slider.value()] = 0
        self.sam_obj_pos_label.setText("标注物体: 1/1")
        self.sam_frame_id = set()
        
        if self.last_frame is not None:
            self.draw_image()

    def clear_keyframes(self):
        self.keyframes = {}
        self.lang_anno = dict()
        if self.last_frame is not None:
            self.draw_image()
        self.update_keyframe_bar()
           
    def clear_video(self):
        self.video_label.clear()
        self.video_views = None
        if hasattr(self, "video_view_labels"):
            for label in self.video_view_labels.values():
                label.clear()
                label.setParent(None)
                label.deleteLater()
            self.video_view_labels = {}
        self.progress_slider.setValue(0)
        self.frame_position_label.hide()
        self.keyframes = {}
        self.ori_video = {}
        self.selected_keyframe = None
        self.update_keyframe_bar()
        self.keyframe_bar.hide()
        self.last_frame = None
        self.cur_frame_idx = 0
        self.current_frame = 0
        self.sam_object_id = [0] * self.frame_count
        self.max_point_num = dict()
        # self.vis_ori.setChecked(True)
        self.lang_anno = dict()
        self.scene_annotation = None
        self.video_lang_input.clear()
        self.update_scene_display()
        self.clip_lang_input.clear()
        self.video_position_label.setText(f"帧: -/-")
    
    def remove_last_sam_annotation(self):
        if len(self.tracking_points_sam) == 0:
            self.smart_message("请先标注!")
            return
        
        sam_object_id = self.sam_object_id[self.progress_slider.value()]
        click_action = self.tracking_points_sam[self.progress_slider.value()][sam_object_id]['labels']
        pos_click_position = self.tracking_points_sam[self.progress_slider.value()][sam_object_id]['pos']
        neg_click_position = self.tracking_points_sam[self.progress_slider.value()][sam_object_id]['neg']
        
        if len(click_action) > 0 and click_action[-1] == 1 and len(pos_click_position) > 0:
            if len(pos_click_position) > 0:
                self.tracking_points_sam[self.progress_slider.value()][sam_object_id]['pos'].pop()
                self.tracking_points_sam[self.progress_slider.value()][sam_object_id]['raw_pos'].pop()
                self.tracking_points_sam[self.progress_slider.value()][sam_object_id]['labels'].pop()
        elif len(click_action) > 0 and click_action[-1] == -1 and len(neg_click_position) > 0:
            if len(neg_click_position) > 0:
                self.tracking_points_sam[self.progress_slider.value()][sam_object_id]['neg'].pop()
                self.tracking_points_sam[self.progress_slider.value()][sam_object_id]['raw_neg'].pop()
                self.tracking_points_sam[self.progress_slider.value()][sam_object_id]['labels'].pop()
        
        if len(self.tracking_points_sam[self.progress_slider.value()][sam_object_id]['pos']) == 0 and len(self.tracking_points_sam[self.progress_slider.value()][sam_object_id]['neg']) == 0:
            if self.progress_slider.value() in self.sam_frame_id:
                self.sam_frame_id.remove(self.progress_slider.value())
            cur_obj_id = self.sam_object_id[self.progress_slider.value()]
            if cur_obj_id > 0:
                self.tracking_points_sam[self.progress_slider.value()].pop(cur_obj_id)
                self.sam_object_id[self.progress_slider.value()] -= 1
        
            cur_id = self.sam_object_id[self.progress_slider.value()] + 1
            all_object_size = len(self.tracking_points_sam[self.progress_slider.value()])
            self.sam_obj_pos_label.setText(f"物体标注: {cur_id}/{all_object_size}")
            
        if self.last_frame is not None:
            self.draw_image()
     
    def remove_last_annotation(self):
        self.remove_last_sam_annotation()
    
    def remove_obj_annotation(self):
        if len(self.tracking_points_sam) == 0:
            self.smart_message("请先加载视频!")
            return
        cur_obj_id = self.sam_object_id[self.progress_slider.value()]
        self.tracking_points_sam[self.progress_slider.value()].pop(cur_obj_id)
        
        if cur_obj_id > 0:
            self.sam_object_id[self.progress_slider.value()] -= 1
        else:
            self.sam_object_id[self.progress_slider.value()] = 0
        
        if len(self.tracking_points_sam[self.progress_slider.value()]) == 0:
            self.tracking_points_sam[self.progress_slider.value()].append(
                dict(pos=[], raw_pos=[], neg=[], raw_neg=[], labels=[])
            )
            self.sam_object_id[self.progress_slider.value()]=0
            if self.progress_slider.value() in self.sam_frame_id:
                self.sam_frame_id.remove(self.progress_slider.value())
        
        cur_id = self.sam_object_id[self.progress_slider.value()] + 1
        all_object_size = len(self.tracking_points_sam[self.progress_slider.value()])
        self.sam_obj_pos_label.setText(f"标注物体: {cur_id}/{all_object_size}")
        
        if self.last_frame is not None:
            self.draw_image()
    
    def load_video_callback(self, res):
        if res == 0:
            self.smart_message("暂无需要标注的视频，请耐心等待")
            sys.exit()
        
        if self.mode != '语言标注':
            video, save_path, video_path, hist_num, \
                one_anno_num, all_one_anno_num, two_anno_num, all_two_anno_num, three_anno_num, all_three_anno_num = res
        else:
            if len(res) == 6:
                video, lang, save_path, primary_video_path, hist_num, task_id = res
            else:
                video, lang, save_path, primary_video_path, hist_num = res
                task_id = primary_video_path
            self.loaded_lang_annotation = (
                lang if isinstance(lang, dict) and lang.get("schema_version") == SCHEMA_VERSION else None
            )
            self.video_2_lang = dict(
                task_stepsC=dict(),
                instructionC='',
                action_stepsC=[],
                task_stepsC_list=[]
            )
            video_path = task_id
            self.primary_video_path = primary_video_path
        self.save_path = save_path
        self.video_path = video_path
        self.hist_num = hist_num
        self.hist_num_label.setText(f"已标注数量: {self.hist_num}")
        if self.mode != '语言标注':
            self.two_anno_num = two_anno_num
            self.one_anno_num = one_anno_num
            self.three_anno_num = three_anno_num
            self.all_one_anno_num = all_one_anno_num
            self.all_two_anno_num = all_two_anno_num
            self.all_three_anno_num = all_three_anno_num
            self.one_num_label.setText(f"一次复检(可用/总数): {self.one_anno_num}/{self.all_one_anno_num}")
            self.two_num_label.setText(f"二次复检(可用/总数): {self.two_anno_num}/{self.all_two_anno_num}")
            self.three_num_label.setText(f"三次复检(可用/总数): {self.three_anno_num}/{self.all_three_anno_num}")
            self.has_one_anno = one_anno_num > 0
            self.has_two_anno = two_anno_num > 0
            self.has_three_anno = three_anno_num > 0
            self.video_name_input.setText(video_path.split('/')[-1].split('.')[0])
        
        if video is not None:
            self.load_video(video)
            self.progress.close()
        else:
            self.progress.close()
            self.smart_message("视频加载失败，请检查网络设置")
            return
        
    def load_video_async(self):
        self.progress = QProgressDialog("请等待，正在加载视频...", None, 0, 0, self)
        self.progress.setWindowModality(Qt.WindowModal)
        self.progress.setCancelButton(None)
        self.progress.setMinimumDuration(0)  # 立即显示对话框
        self.progress.show()

        self.video_thread = self.request_video_async()
        self.video_thread.finished.connect(self.load_video_callback)
        self.video_thread.start()
    
    def load_video(self, video):
        if video is None:
            return -1
        self.video_views = video if isinstance(video, dict) else None
        if self.video_views:
            min_frames = min(view_video.shape[0] for view_video in self.video_views.values())
            self.frame_count = min_frames
        else:
            self.frame_count = video.shape[0]
        self.sam_object_id = [0] * self.frame_count
        self.lang_anno = dict()
        self.scene_annotation = None
        self.tracking_points_sam = dict()
        self.ori_video = self.video_views if self.video_views else np.array(video)
        self.setup_video_view_labels()
        self.sam_obj_pos_label.setText("标注物体: 1/1")
        
        for i in range(self.frame_count):
            self.tracking_points_sam[i] = [dict(
                    pos=[], raw_pos=[], neg=[], raw_neg=[], labels=[]
            )]
        self.sam_object_id = [0] * self.frame_count

        self.progress_slider.setMaximum(self.frame_count - 1)
        self.progress_slider.show()
        self.frame_position_label.show()
        self.update_keyframe_bar()
        self.update_frame(0)
        self.progress_slider.setValue(0)
        # if self.mode == '语言标注':
        self.keyframe_bar.show()
        self.video_position_label.setText(f"帧: {self.cur_frame_idx+1}/{self.frame_count}")
        # self.pre_f_button.setDisabled(True)
        self.max_point_num = 0
        self.hist_num = dict()
        self.sam_frame_id = set()
        self.start_frame_to_object_id = dict()
        self.frame_contact = set()
        self.use_L = False
        
        if self.mode != '语言标注':
            self.check_re_anno()
            self.button_param_select.setCurrentIndex(0)
            self.is_finished_button.setChecked(False)
            self.is_finished_button.setDisabled(False)
            self.is_hard_sample_button.setChecked(False)
            self.is_hard_sample_button.setDisabled(False)
        
        self.seek_video()
        # for align the keyframe display length
        if 0 not in self.keyframes and self.is_first:
            self.mark_keyframe(debug=True)
            self.selected_keyframe = self.progress_slider.value()
            self.remove_keyframe()
            self.is_first = False
        
        # load global language annotation
        if self.mode == '语言标注':
            if self.loaded_lang_annotation:
                video_text = self.loaded_lang_annotation.get("video_text", "")
                if video_text:
                    self.lang_anno[(0, 0)] = video_text
                loaded_scene = self.loaded_lang_annotation.get("scene")
                if isinstance(loaded_scene, dict):
                    self.scene_annotation = loaded_scene
                for subtask in self.loaded_lang_annotation.get("subtasks", []):
                    try:
                        start_frame = int(subtask["start_frame"])
                        end_frame = int(subtask["end_frame"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    subtask_data = {
                        key: value for key, value in subtask.items()
                        if key not in ("start_frame", "end_frame")
                    }
                    self.lang_anno[(start_frame, end_frame)] = subtask_data
                    self.keyframes[start_frame] = 'start'
                    self.keyframes[end_frame] = 'end'
                self.update_keyframe_bar()
            video_text = self.lang_anno.get((0, 0), "")
            self.video_lang_input.setText(f"视频整体描述: {video_text}" if video_text else "")
            self.update_scene_display()
            self.preview_clip_lang_input.setText(self.get_clip_lang_anno())
        
        return 1
            
    def update_frame(self, frame_number):
        if self.video_views:
            if len(self.video_views) == 0:
                self.smart_message('请先加载视频！')
                return
            self.update_multiview_frame(frame_number)
            return

        if  len(self.ori_video) == 0:
            self.smart_message('请先加载视频！')
            return
        frame = self.ori_video[frame_number]
        self.height, self.width, channel = frame.shape

        # Scale the image to fit QLabel
        label_width = self.video_label.width()
        label_height = self.video_label.height()
        self.scale_width = label_width / self.width
        self.scale_height = label_height / self.height
        self.scale = min(self.scale_width, self.scale_height)
        new_width = int(self.width * self.scale)
        new_height = int(self.height * self.scale)

        resized_frame = cv2.resize(frame, (new_width, new_height), interpolation=cv2.INTER_AREA)
        
        # Update and reposition frame position label
        self.update_frame_position_label()
        self.last_frame = resized_frame
        
        self.draw_image()

    def setup_video_view_labels(self):
        if not hasattr(self, "video_view_labels"):
            self.video_view_labels = {}
        for label in self.video_view_labels.values():
            label.setParent(None)
            label.deleteLater()
        self.video_view_labels = {}

        while self.video_views_layout.count():
            item = self.video_views_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                self.video_views_layout.removeWidget(widget)

        if self.mode == '语言标注' and self.video_views:
            for idx, view_name in enumerate(sorted(self.video_views)):
                view_box = QVBoxLayout()
                name_label = QLabel(view_name, self)
                name_label.setAlignment(Qt.AlignCenter)
                name_label.setStyleSheet("background-color: #E3E3E3; font-weight: bold;")
                frame_label = QLabel(self)
                frame_label.setAlignment(Qt.AlignCenter)
                frame_label.setMinimumSize(360, 220)
                view_box.addWidget(name_label)
                view_box.addWidget(frame_label)
                self.video_views_layout.addLayout(view_box, idx // 2, idx % 2)
                self.video_view_labels[view_name] = frame_label
            self.video_label.hide()
        else:
            self.video_label.show()
            self.video_views_layout.addWidget(self.video_label, 0, 0)

    def update_multiview_frame(self, frame_number):
        self.update_frame_position_label()
        for view_name, video in self.video_views.items():
            frame = video[frame_number]
            height, width, _ = frame.shape
            label = self.video_view_labels.get(view_name)
            if label is None:
                continue
            label_width = max(label.width(), 360)
            label_height = max(label.height(), 220)
            scale = min(label_width / width, label_height / height)
            new_width = int(width * scale)
            new_height = int(height * scale)
            resized_frame = cv2.resize(frame, (new_width, new_height), interpolation=cv2.INTER_AREA)
            q_image = QImage(
                resized_frame.data,
                resized_frame.shape[1],
                resized_frame.shape[0],
                resized_frame.strides[0],
                QImage.Format_RGB888,
            )
            label.setPixmap(QPixmap.fromImage(q_image))
        self.last_frame = True
                
    def seek_video(self):
        if self.last_frame is None:
            return 
        frame_number = self.progress_slider.value()
        self.update_frame(frame_number)
        self.cur_frame_idx = self.progress_slider.value()
        self.video_position_label.setText(f"帧: {self.cur_frame_idx+1}/{self.frame_count}")
        
        self.sam_object_id[self.cur_frame_idx] = 0
        self.sam_obj_pos_label.setText(f"标注物体: {self.sam_object_id[self.cur_frame_idx]+1}/{len(self.tracking_points_sam[self.cur_frame_idx])}")
        self.sam_pre_button.setDisabled(True)
        self.sam_next_button.setDisabled(False)
        
        video_text = self.lang_anno.get((0, 0), "")
        self.video_lang_input.setText(f"视频整体描述: {video_text}" if video_text else "")
        
        anno_loc, (clip_text, prim, origin_text) = self.get_clip_description()
        anno_loc = anno_loc[1]
        if anno_loc is not None:
            self.clip_lang_input.setText(f"开始帧: {anno_loc[0]+1} | 结束帧: {anno_loc[1]+1}\n原子动作: {prim}\n动作描述: {clip_text}")
        else:
            self.clip_lang_input.clear()
            
    def toggle_playback(self):
        if self.play_button.isChecked():
            self.play_button.setText("暂停")
            self.current_frame = self.progress_slider.value()
            self.timer.start(30)  # Set timer to update frame every 30 ms
        else:
            self.play_button.setText("播放")
            self.timer.stop()

    def update_frame_position_label(self):
        # Update the text of the label to show the current frame position
        frame_number = self.progress_slider.value()
        # check if the frame number has keyframe
        if frame_number in self.keyframes:
            keyframe_type = self.keyframes[frame_number]
            # keyframe_type = '开始' if keyframe_type.lower() == 'start' else '结束'
            # keyframe_type = keyframe_type if 
            if keyframe_type.lower() == 'start':
                keyframe_type = '开始'
            elif keyframe_type.lower() == 'end':
                keyframe_type = '结束'
            elif keyframe_type.lower() == 'object_sep':
                keyframe_type = '物体分段'
            elif keyframe_type.lower() == 'object_contact':
                keyframe_type = '接触'
            
            self.frame_position_label.setText(f"帧: {frame_number+1}({keyframe_type})")
        else:
            self.frame_position_label.setText(f"帧: {frame_number+1}")

        # Calculate the position for the label above the slider handle
        slider_x = self.progress_slider.x()
        slider_width = self.progress_slider.width()
        # print(self.progress_slider.maximum(), self.progress_slider.minimum())
        value_ratio = frame_number / (self.progress_slider.maximum() - self.progress_slider.minimum())
        label_x = slider_x + int(value_ratio * slider_width) - self.frame_position_label.width() // 2
        
        # Set the position of the label
        label_y = self.progress_slider.y() - self.frame_position_label.height() - 4
        label_x = max(slider_x, min(label_x, slider_x + slider_width - self.frame_position_label.width()))
        self.frame_position_label.move(label_x, label_y)
        self.frame_position_label.show()  # Show the label

    def get_frame_position(self):
        current_position = self.progress_slider.value()
        return current_position
    
    def play_video(self):
        # if self.cap is not None:
        if self.current_frame < self.frame_count - 1:
            self.current_frame += 1
            self.update_frame(self.current_frame)
            self.progress_slider.setValue(self.current_frame)
        else:
            self.timer.stop()
            self.play_button.setChecked(False)
            self.play_button.setText("播放")
    
    # 自动播放视频，再点击停止播放
    def autoplayorstop(self):
        if self.is_stop:
            self.play_button.setText("暂停")
            self.current_frame = self.progress_slider.value()
            self.timer.start(30)
        else:
            self.play_button.setText("播放")
            self.timer.stop()

    def set_sam_config(self):
        tracking_points = self.tracking_points_sam
        select_frames = list(self.sam_frame_id)
        self.sam_config['video_path'] = self.video_path
        # print(self.video_path)
        self.sam_config['user'] = self.username
        self.sam_config["hard_sample_type"] = 'normal'
        
        if self.is_hard_sample_button.isChecked() and self.is_finished_button.isChecked():
            self.smart_message("困难样本不可标注为完成，请检查")
            return -1
        
        if self.is_finished_button.isChecked():
            self.sam_config['is_finished'] = True
            self.sam_config['is_hard_sample'] = False
            self.sam_config["hard_sample_type"] = self.is_hard_sample_button.text() 
            return 0
        
        if self.is_hard_sample_button.isChecked():
            self.sam_config['is_hard_sample'] = True
            self.sam_config['is_finished'] = False
            self.sam_config["hard_sample_type"] = self.is_hard_sample_button.text()
            return 0
        
        if len(select_frames) == 0:
            self.smart_message("请先标注物体")
            return -1
        
        if not self.use_L:
            self.smart_message("完成标注物体后，请按下L键确认物体绑定顺序")
            return -1
        
        if len(select_frames) > 1 and self.button_param_select.currentText() != '双向视频模式':
            self.smart_message("多帧模式仅支持双向视频模式，请检查")
            return -1
        
        for i in select_frames[1:]:
            if len(tracking_points[i]) != len(tracking_points[select_frames[0]]):
                self.smart_message(f"第{i}帧标注物体数量与第0帧不匹配, 请检查")
                return -1
        
        objects = list(set([i for i in self.start_frame_to_object_id.values()]))
        if len(tracking_points[select_frames[0]]) > 0 and len(tracking_points[select_frames[0]]) != len(objects):
            self.smart_message("标注物体数量与关键帧数量不匹配, 请检查")
            return -1
        
        if self.align_contact_frame_with_object_sep() == -1:
            return -1
        
        positive_points_all = {}
        negative_points_all = {}
        labels_all = {}
        
        if self.button_param_select.currentText() == '双向视频模式':
            direction = 'bidirection' 
        elif self.button_param_select.currentText() == '正向视频模式':
            direction = 'forward'
        else:
            direction = 'backward'
        is_video = True
        
        for select_frame in select_frames:
            positive_points_all[select_frame] = {}
            negative_points_all[select_frame] = {}
            labels_all[select_frame] = {}
            frame_pts = tracking_points[select_frame]
            # select all objects
            for obj_id, obj_pts in enumerate(frame_pts):
                positive_points, negative_points, labels = [], [], []
                if obj_pts['raw_pos'] != []:
                    positive_points.extend([[pt.x(), pt.y()] for pt in obj_pts['raw_pos']])
                if obj_pts['raw_neg'] != []:
                    negative_points.extend([[pt.x(), pt.y()] for pt in obj_pts['raw_neg']])
                if (obj_pts['raw_pos'] != []) or (obj_pts['raw_neg'] != []):
                    labels.extend(obj_pts['labels'])
                
                positive_points_all[select_frame][obj_id] = positive_points
                negative_points_all[select_frame][obj_id] = negative_points
                labels_all[select_frame][obj_id] = labels
        
        self.sam_config['is_video'] = is_video
        self.sam_config['direction'] = direction
        self.sam_config['positive_points'] = positive_points_all
        self.sam_config['negative_points'] = negative_points_all
        self.sam_config['labels'] = labels_all
        self.sam_config['select_frames'] = select_frames
        self.sam_config['button_mode'] = self.button_mode
        self.sam_config['start_frame_2_obj_id'] = self.start_frame_to_object_id
        self.sam_config['frame_contact_2_obj_id'] = self.frame_contact_to_object_id
        self.sam_config['is_finished'] = False
        self.sam_config['is_hard_sample'] = False
        
        print(self.start_frame_to_object_id)
        print(self.frame_contact_to_object_id)
        
        return 0
    
    def smart_message(self, message, auto_close=True):
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Information)
        msg.setWindowTitle('提示')
        msg.setText(message)
        msg.exec_()
    
    def save_sam_anno(self):
        res = self.set_sam_config()
        if res == -1:
            return -1
        self.progress = QProgressDialog("请等待，正在储存标注结果...", None, 0, 0, self)
        self.progress.setWindowModality(Qt.WindowModal)
        self.progress.setCancelButton(None)
        self.progress.setMinimumDuration(0)
        self.progress.show()
        
        saved_config = self.sam_config.copy()
        saved_config['video_path'] = self.video_path
        res = save_anno(self.ip_address, self.port, self.save_path, self.sam_config.copy())
        try_time = 0
        while not res:
            if try_time > 3:
                break
            self.smart_message("保存失败，进行第{}次重试".format(try_time+1))
            time.sleep(4)
            res = save_anno(self.ip_address, self.port, self.save_path, self.sam_config.copy())
            try_time += 1
        
        if not res:
            self.progress.close()
            self.smart_message("保存失败，即将退出系统重启软件")
            drawback_video(self.ip_address, self.port, self.video_path, 'sam')
            sys.exit()
        
        self.progress.close()
        return 0
              
    def mousePressEvent(self, event: QMouseEvent):        
        if self.last_frame is None:
            return
        
        if self.mode == '语言标注':
            return
        
        if event.button() == Qt.LeftButton and self.last_frame is not None:
            pos = self.video_label.mapFromGlobal(event.globalPos())
            gt_pos = self.get_align_point(pos.x(), pos.y())
            if gt_pos is None:
                return
            click_position = QPoint(gt_pos[0], gt_pos[1])
            original_position = QPoint(int(gt_pos[0]//self.scale), int(gt_pos[1]//self.scale))      
            sam_object_id = self.sam_object_id[self.progress_slider.value()]
            self.tracking_points_sam[self.progress_slider.value()][sam_object_id]['raw_pos'].append(original_position)
            self.tracking_points_sam[self.progress_slider.value()][sam_object_id]['pos'].append(click_position)
            self.tracking_points_sam[self.progress_slider.value()][sam_object_id]['labels'].append(1)
            self.sam_next_button.setDisabled(False)
            self.sam_frame_id.add(self.progress_slider.value())
                
        elif event.button() == Qt.RightButton and self.last_frame is not None:
            pos = self.video_label.mapFromGlobal(event.globalPos())
            gt_pos = self.get_align_point(pos.x(), pos.y())
            if gt_pos is None:
                return
            click_position = QPoint(gt_pos[0], gt_pos[1])
            original_position = QPoint(int(gt_pos[0]//self.scale), int(gt_pos[1]//self.scale))
            sam_object_id = self.sam_object_id[self.progress_slider.value()]
            self.tracking_points_sam[self.progress_slider.value()][sam_object_id]['neg'].append(click_position)
            self.tracking_points_sam[self.progress_slider.value()][sam_object_id]['raw_neg'].append(original_position)
            self.tracking_points_sam[self.progress_slider.value()][sam_object_id]['labels'].append(-1)
            self.sam_next_button.setDisabled(False)
            self.sam_frame_id.add(self.progress_slider.value())
            
        self.draw_image()
    
    def get_align_point(self, x, y): 
        label_height, label_width = self.video_label.height(), self.video_label.width()
        resized_width = int(self.width * min(self.scale_width, self.scale_height))
        resized_height = int(self.height * min(self.scale_width, self.scale_height))
        offset_x = (label_width - resized_width) // 2
        offset_y = (label_height - resized_height) // 2
        x -= offset_x
        y -= offset_y
        
        gt_shape = self.last_frame.shape
        if x < 0 or y < 0 or x >= gt_shape[1] or y >= gt_shape[0]:
            return None
        
        return (x, y)
     
    def draw_image(self):
        if self.last_frame is None:
            return
        frame = self.last_frame.copy()

        if self.mode != '语言标注':
            sam_object_id = self.sam_object_id[self.progress_slider.value()]
            if self.progress_slider.value() in self.tracking_points_sam:
                pos_click_position = self.tracking_points_sam[self.progress_slider.value()][sam_object_id]['pos']
                neg_click_position = self.tracking_points_sam[self.progress_slider.value()][sam_object_id]['neg']
            else:
                pos_click_position, neg_click_position = [], []
        else:
            pos_click_position, neg_click_position = [], []

        for point in pos_click_position:
            x, y = point.x(), point.y()
            cv2.circle(frame, (x, y), 3, (0, 255, 0), -1, lineType=cv2.LINE_AA)
            height, width, channel = frame.shape
            bytes_per_line = 3 * width
            q_img = QImage(frame.data, width, height, bytes_per_line, QImage.Format_RGB888)
        
        for point in neg_click_position:
            x, y = point.x(), point.y()
            cv2.circle(frame, (x, y), 3, (255, 0, 0), -1, lineType=cv2.LINE_AA)
            height, width, channel = frame.shape
            bytes_per_line = 3 * width
            q_img = QImage(frame.data, width, height, bytes_per_line, QImage.Format_RGB888)
        
        if len(pos_click_position)==0 and len(neg_click_position)==0:
            height, width, channel = frame.shape
            bytes_per_line = 3 * width
            q_img = QImage(frame.data, width, height, bytes_per_line, QImage.Format_RGB888)
        
        self.video_label.setPixmap(QPixmap.fromImage(q_img))

    def submit_description(self):
        self.add_video_description()

    def mark_keyframe(self, debug=False):
        current_frame = self.progress_slider.value()
        if self.key_frame_mode == 'start':
            # check if the last keyframe is 'end'
            if len(self.keyframes) > 0 and list(self.keyframes.values())[-1] == 'start':
                if not debug:
                    # self.is_stop = False
                    # self.autoplayorstop()
                    pass
                self.smart_message('请标注结束帧')
                return -1
            
            if len(self.keyframes) > 0:
                for i in list(self.lang_anno.keys()):
                    if i[0] <= current_frame and i[1] >= current_frame and i[0] != i[1]:
                        if not debug:
                            # self.is_stop = False
                            # self.autoplayorstop()
                            pass
                        self.smart_message('请勿在上一个视频段中标记')
                        return -1
            
            if current_frame in self.keyframes and self.keyframes[current_frame] == 'end':
                if not debug:
                    # self.is_stop = False
                    # self.autoplayorstop()
                    pass
                self.smart_message('请勿重复标记')
                return -1
            if not self.is_first:
                self.keyframes[current_frame] = 'start'
            self.update_keyframe_bar()
            self.update_frame_position_label()
            if not debug:
                # self.is_stop = True
                # self.autoplayorstop()
                pass
            
            self.last_start_frame = current_frame
        
        elif self.key_frame_mode == 'End':
            # check if the last keyframe is 'start'
            if len(self.keyframes) > 0 and list(self.keyframes.values())[-1] == 'end':
                if not debug:
                    # self.is_stop = False
                    # self.autoplayorstop()
                    pass
                self.smart_message('请标记开始帧')
                return -1
            
            if current_frame in self.keyframes and self.keyframes[current_frame] == 'start':
                if not debug:
                    # self.is_stop = False
                    # self.autoplayorstop()
                    pass
                self.smart_message('请勿重复标记')
                return -1
            
            if len(self.keyframes) > 0:
                for i in list(self.lang_anno.keys()):
                    if i[0] <= current_frame and i[1] >= current_frame:
                        if not debug:
                            # self.is_stop = False
                            # self.autoplayorstop()
                            pass
                        self.smart_message('请勿在上一个视频段中标记')
                        return -1

                    if self.last_start_frame <= i[0] and i[1] <= current_frame and i[0] != 0:
                        if not debug:
                            # self.is_stop = False
                            # self.autoplayorstop()
                            pass
                        self.keyframes.pop(self.last_start_frame)
                        self.update_keyframe_bar()
                        self.last_start_frame = None
                        self.smart_message('中间包含其他视频段')
                        return -1
            
            if len(self.keyframes) == 0:
                self.smart_message('请先标记开始帧')
                if not debug:
                    # self.is_stop = False
                    # self.autoplayorstop()
                    pass
                return -1
            
            self.keyframes[current_frame] = 'end'
            self.update_keyframe_bar()
            self.update_frame_position_label()
            if not debug:
                # self.is_stop = False
                # self.autoplayorstop()
                pass
            self.add_frame_discribtion()
        
        return 0
    
    def update_lang_anno(self):
        key_frame_list = sorted(self.keyframes.keys())
        key_pairs = []
        if len(key_frame_list) <= 1:
            self.smart_message('请先标记关键帧')
            return -1
        
        if len(key_frame_list) % 2 != 0:
            self.smart_message('请检查关键帧标记是否正确，必须是开始帧和结束帧交替出现')
            return -1
        
        for i in range(0, len(key_frame_list), 2):
            start_frame = key_frame_list[i]
            end_frame = key_frame_list[i+1]
            if self.keyframes[start_frame] != 'start' or self.keyframes[end_frame] != 'end':
                self.smart_message('请检查关键帧标记是否正确，必须是开始帧和结束帧交替出现')
                return -1
            key_pairs.append((start_frame, end_frame))
            
        for i in key_pairs:
            if i not in self.lang_anno:
                self.lang_anno[i] = (None, None, None)

    def remove_keyframe(self):
        if self.selected_keyframe is not None:
            frame_to_remove = self.selected_keyframe
            if frame_to_remove in self.keyframes:
                if self.keyframes[frame_to_remove] == 'object_contact':
                    self.frame_contact.remove(frame_to_remove)
                self.keyframes.pop(frame_to_remove)
                self.update_keyframe_bar()

    def update_keyframe_bar(self):
        # Clear the keyframe bar
        keyframe_image = QImage(self.keyframe_bar.width(), self.keyframe_bar.height(), QImage.Format_RGB32)
        keyframe_image.fill(Qt.gray)

        painter = QPainter(keyframe_image)
        for frame, key_type in self.keyframes.items():
            x_position = int((frame / self.frame_count) * self.keyframe_bar.width())
            color = QColor('red') if key_type == 'start' else QColor('blue')
            color = color if key_type != 'object_sep' else QColor('black')
            color = color if key_type != 'object_contact' else QColor('green')
            painter.fillRect(QRect(x_position, 0, 5, self.keyframe_bar.height()), color)
        painter.end()

        # Set the updated image to the QLabel
        self.keyframe_bar.setPixmap(QPixmap.fromImage(keyframe_image))
    
    def keyPressEvent(self, event):   
        key = event.key()
        if key == Qt.Key_A:
            self.pre_frame()
        elif key == Qt.Key_D:
            self.next_frame()
        elif key == Qt.Key_W and self.mode == '语言标注':
            self.key_frame_mode = 'start'
            self.is_stop = True
            self.mark_keyframe()
        elif key == Qt.Key_S and self.mode == '语言标注':
            self.key_frame_mode = 'End'
            self.is_stop = False
            self.mark_keyframe()
        elif key == Qt.Key_S and self.mode == '分割标注':
            self.add_object_sep()
            self.update_frame_position_label()
        elif key == Qt.Key_W and self.mode == '分割标注':
            self.add_object_contact_frame()
            self.update_frame_position_label()
            self.frame_contact.add(self.progress_slider.value())
        elif key == Qt.Key_Backspace and self.mode == '语言标注':
            self.selected_keyframe = self.progress_slider.value()
            # self.remove_keyframe()
            self.delete_keyframe()
            self.update_frame_position_label()
        elif key == Qt.Key_Backspace and self.mode == '分割标注':
            self.selected_keyframe = self.progress_slider.value()
            self.remove_keyframe()
            self.update_frame_position_label()
        elif key == Qt.Key_Return and self.mode == '语言标注':
            self.submit_description()
        elif key == Qt.Key_G and self.mode == '语言标注':
            self.add_scene_annotation()
        elif key == Qt.Key_F:
            self.is_stop = not self.is_stop
            self.autoplayorstop()
        elif key == Qt.Key_L and self.mode == '语言标注':
            self.add_frame_discribtion()
        elif key == Qt.Key_L and self.mode == '分割标注':
            self.add_object_sep_2_id()
        elif key == Qt.Key_P:
            self.next_button.click()
        elif key == Qt.Key_E:
            self.sam_next_button.click()
    
    def add_object_sep(self):
        self.keyframes[self.progress_slider.value()] = 'object_sep'
        self.update_keyframe_bar()
    
    def add_object_contact_frame(self):
        self.keyframes[self.progress_slider.value()] = 'object_contact'
        self.update_keyframe_bar()
    
    def add_object_sep_2_id(self):
        self.use_L = True
        self.start_frame_to_object_id = dict()
        object_size = max([len(i) for i in self.tracking_points_sam.values()])
        key_frames = [k for (k, v) in self.keyframes.items() if v == 'object_sep']
        
        if object_size > 1:
            # if object_size != len(key_frames) + 1:
            #     self.smart_message('关键帧分割和物体标注数量不一致！')
            #     return
            dialog = ObjectAnnotationDialog(object_size, self.frame_count, key_frames, self)
            while True:
                if dialog.exec_() == QDialog.Accepted:
                    try:
                        self.start_frame_to_object_id = dialog.get_result()
                        break
                    except:
                        self.smart_message('有视频段未标注，请检查')
                        continue
                else:
                    return
        elif object_size == 1:
            # if len(key_frames) > 0:
            #     self.smart_message('关键帧分割和物体标注数量不一致！')
            #     return
            dialog = ObjectAnnotationDialog(object_size, self.frame_count, key_frames, self)
            while True:
                try:
                    if dialog.exec_() == QDialog.Accepted:
                        self.start_frame_to_object_id = dialog.get_result()
                        break
                except:
                    self.smart_message('有视频段未标注，请检查')
                    continue
                else:
                    return
            
        else:
            self.smart_message('无物体标注')
            return
    
    def align_contact_frame_with_object_sep(self):
        self.frame_contact_to_object_id = dict()
        # if len(self.frame_contact) != len(self.start_frame_to_object_id):
        #     print(self.frame_contact, self.start_frame_to_object_id)
        #     self.smart_message('接触帧数量和物体标注数量不一致')
        #     return -1

        self.frame_contact_to_object_id = dict()
        frame_contact_ids = sorted(list(self.frame_contact))
        sep_frame_ids = sorted(list(self.start_frame_to_object_id.keys()))
        
        for c_id, s_id in zip(frame_contact_ids, sep_frame_ids):
            self.frame_contact_to_object_id[c_id] = self.start_frame_to_object_id[s_id]
        
        return 0
    
    def delete_keyframe(self):
        info, lang = self.get_clip_description()
        if info[0] is not None:
            idx, loc = info
            self.lang_anno.pop(loc)
            self.keyframes.pop(loc[0])
            self.keyframes.pop(loc[1])
            self.update_keyframe_bar()
            self.clip_lang_input.clear()
            self.selected_keyframe = None
        
    def add_frame_discribtion(self):
        frame_number = self.progress_slider.value()
        if self.update_lang_anno() == -1:
            return
        key_pairs = [key for key in self.lang_anno if key != (0, 0)]
        has_key = [i[0] <= frame_number <= i[1] for i in key_pairs].count(True) > 0
        if not has_key:
            self.smart_message('请先标记当前所在区域的起止帧')
            return

        # load the cached subtask
        anno_loc = [(idx, i) for idx, i in enumerate(key_pairs) if i[0] <= frame_number <= i[1] and i[0] != i[1]]
        if len(anno_loc) == 0:
            self.smart_message('请移动到所在区域的起止帧之间')
            return
        anno_id, anno_loc = anno_loc[0]
        
        cached_clip = self.lang_anno[anno_loc]
        cached_lang, prim, origin_text = get_subtask_display(cached_clip)
        if not isinstance(cached_clip, dict):
            cached_clip = ''
            cached_lang, prim, origin_text = '', '', ''
        # Create a dialog to get the structured subtask from the user
        dialog = TextInputDialog(cached_clip, self, False, self.video_2_lang, origin_text=origin_text)
        if dialog.exec_() == QDialog.Accepted:
            structured_clip = dialog.get_structured_result()
            cached_lang, prim, _ = get_subtask_display(structured_clip)
            self.lang_anno[anno_loc] = structured_clip
            self.clip_lang_input.setText(f"开始帧: {anno_loc[0]+1} | 结束帧: {anno_loc[1]+1}\n原子动作: {prim}\n动作描述: {cached_lang}")
            self.preview_clip_lang_input.setText(self.get_clip_lang_anno())
        else:
            self.delete_keyframe()
            return
    
    def add_video_description(self):
        cached_lang = self.lang_anno.get((0, 0), "")
        dialog = TextInputDialog(cached_lang, self, True, self.video_2_lang)
        if dialog.exec_() == QDialog.Accepted:
            video_description = dialog.get_text().strip()
            self.lang_anno[(0, 0)] = video_description
            self.video_lang_input.setText(f"视频整体描述: {video_description}")

    def update_scene_display(self):
        if not hasattr(self, "scene_lang_input"):
            return
        if not self.scene_annotation:
            self.scene_lang_input.clear()
            return
        object_count = len(self.scene_annotation.get("objects") or [])
        scene_location = self.scene_annotation.get("scene_location") or {}
        self.scene_lang_input.setText(
            f"场景标注: {self.scene_annotation.get('text', '')}\n"
            f"一级场景: {self.scene_annotation.get('scene_level1', '')} | "
            f"二级场景: {self.scene_annotation.get('scene_level2', '')} | "
            f"任务类型: {self.scene_annotation.get('task_type', '')} | "
            f"空间: {scene_location.get('space', '')} | "
            f"锚点: {scene_location.get('anchor', '')} | "
            f"物体数: {object_count}"
        )

    def add_scene_annotation(self):
        dialog = SceneInputDialog(self.scene_annotation, self)
        if dialog.exec_() == QDialog.Accepted:
            self.scene_annotation = dialog.get_scene_result()
            self.update_scene_display()

    def get_clip_description(self):
        # Get the subtask text for the clip
        key_pairs = [key for key in self.lang_anno if key != (0, 0)]
        frame_number = self.progress_slider.value()
        anno_loc = [(idx, i) for idx, i in enumerate(key_pairs) if i[0] <= frame_number <= i[1] and i[0] != i[1]]
        if len(anno_loc) > 0:
            anno_loc = anno_loc[0]
            return anno_loc, get_subtask_display(self.lang_anno[anno_loc[1]])
        return (None, None), (None, None, None)

    def get_clip_lang_anno(self):
        out_text = ''
        for idx, ((start_frame, end_frame), subtask) in enumerate(
            sorted((key, value) for key, value in self.lang_anno.items() if key != (0, 0))
        ):
            text, _, _ = get_subtask_display(subtask)
            out_text += f"{idx + 1}: 帧{start_frame + 1}-{end_frame + 1} {text}\n"
        return out_text.strip()


if __name__ == "__main__":
    try:
        import pyi_splash
        pyi_splash.close()
    except ImportError:
        pass
    args = argparse.ArgumentParser()
    args.add_argument('--out_file', type=str, default='./annotation.pkl')
    args.add_argument('--sam_anno', type=str, default='./sam_anno.pkl')
    args.add_argument('--lang_anno', type=str, default='./lang_anno.pkl')
    args = args.parse_args()
    
    app = QApplication(sys.argv)
    player = VideoPlayer(args)
    player.resize(1100, 600)  # Adjusted size to accommodate the toolbar
    player.show()
    sys.exit(app.exec_())
