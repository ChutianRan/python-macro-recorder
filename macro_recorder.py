import json
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk

from pynput import keyboard, mouse


if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).resolve().parent
else:
    APP_DIR = Path(__file__).resolve().parent
RECORDS_FILE = APP_DIR / "macro_records.json"

CONTROL_KEYS = {
    keyboard.Key.f9,
    keyboard.Key.f10,
    keyboard.Key.f12,
}


def key_to_data(key):
    if isinstance(key, keyboard.KeyCode):
        if key.char is not None:
            return {"kind": "char", "value": key.char}
        return {"kind": "vk", "value": key.vk}
    return {"kind": "special", "value": key.name}


def data_to_key(data):
    if data["kind"] == "char":
        return keyboard.KeyCode.from_char(data["value"])
    if data["kind"] == "vk":
        return keyboard.KeyCode.from_vk(data["value"])
    return getattr(keyboard.Key, data["value"])


def button_to_name(button):
    return button.name


def name_to_button(name):
    return getattr(mouse.Button, name)


def key_data_to_text(data):
    if data["kind"] == "char":
        return data["value"]
    if data["kind"] == "vk":
        return f"vk:{data['value']}"
    return data["value"]


def text_to_key_data(text):
    value = text.strip()
    if not value:
        raise ValueError("按键不能为空")

    if value.lower().startswith("key."):
        value = value[4:]

    if value.lower().startswith("vk:"):
        return {"kind": "vk", "value": int(value[3:])}

    if len(value) == 1:
        return {"kind": "char", "value": value}

    if hasattr(keyboard.Key, value):
        return {"kind": "special", "value": value}

    raise ValueError("无法识别这个按键。普通按键输入 w/a/s/d，特殊按键输入 space、enter、shift 等。")


def key_data_equal(left, right):
    return left["kind"] == right["kind"] and left["value"] == right["value"]


def key_data_id(data):
    return (data["kind"], data["value"])


def events_to_modules(events):
    modules = []
    previous_time = 0.0
    index = 0

    while index < len(events):
        event = events[index]
        event_time = float(event.get("time", previous_time))
        wait_time = max(0.0, event_time - previous_time)
        if wait_time > 0.001:
            modules.append({"type": "wait", "duration": round(wait_time, 5)})

        next_event = events[index + 1] if index + 1 < len(events) else None
        if (
            event["type"] == "key"
            and event["action"] == "press"
            and next_event
            and next_event["type"] == "key"
            and next_event["action"] == "release"
            and key_data_equal(event["key"], next_event["key"])
        ):
            duration = max(0.0, float(next_event["time"]) - event_time)
            modules.append({"type": "key_hold", "key": dict(event["key"]), "duration": round(duration, 5)})
            previous_time = float(next_event["time"])
            index += 2
            continue

        if (
            event["type"] == "mouse_click"
            and event["pressed"]
            and next_event
            and next_event["type"] == "mouse_click"
            and not next_event["pressed"]
            and event["button"] == next_event["button"]
        ):
            duration = max(0.0, float(next_event["time"]) - event_time)
            modules.append(
                {
                    "type": "mouse_click",
                    "button": event["button"],
                    "x": event["x"],
                    "y": event["y"],
                    "duration": round(duration, 5),
                }
            )
            previous_time = float(next_event["time"])
            index += 2
            continue

        modules.append(event_to_module(event))
        previous_time = event_time
        index += 1

    return modules


def event_to_module(event):
    if event["type"] == "key":
        return {"type": "key_event", "action": event["action"], "key": dict(event["key"])}
    if event["type"] == "mouse_move":
        return {"type": "mouse_move", "x": event["x"], "y": event["y"]}
    if event["type"] == "mouse_scroll":
        return {
            "type": "mouse_scroll",
            "x": event["x"],
            "y": event["y"],
            "dx": event["dx"],
            "dy": event["dy"],
        }
    return dict(event)


def modules_to_events(modules):
    events = []
    current_time = 0.0

    for module in modules:
        module_type = module["type"]
        if module_type == "wait":
            current_time += max(0.0, float(module["duration"]))
            continue

        if module_type == "key_hold":
            duration = max(0.0, float(module["duration"]))
            events.append(
                {"type": "key", "action": "press", "key": dict(module["key"]), "time": round(current_time, 5)}
            )
            current_time += duration
            events.append(
                {"type": "key", "action": "release", "key": dict(module["key"]), "time": round(current_time, 5)}
            )
            continue

        if module_type == "key_event":
            events.append(
                {
                    "type": "key",
                    "action": module["action"],
                    "key": dict(module["key"]),
                    "time": round(current_time, 5),
                }
            )
            continue

        if module_type == "mouse_click":
            duration = max(0.0, float(module["duration"]))
            events.append(
                {
                    "type": "mouse_click",
                    "x": int(module["x"]),
                    "y": int(module["y"]),
                    "button": module["button"],
                    "pressed": True,
                    "time": round(current_time, 5),
                }
            )
            current_time += duration
            events.append(
                {
                    "type": "mouse_click",
                    "x": int(module["x"]),
                    "y": int(module["y"]),
                    "button": module["button"],
                    "pressed": False,
                    "time": round(current_time, 5),
                }
            )
            continue

        if module_type == "mouse_move":
            events.append(
                {
                    "type": "mouse_move",
                    "x": int(module["x"]),
                    "y": int(module["y"]),
                    "time": round(current_time, 5),
                }
            )
            continue

        if module_type == "mouse_scroll":
            events.append(
                {
                    "type": "mouse_scroll",
                    "x": int(module["x"]),
                    "y": int(module["y"]),
                    "dx": int(module["dx"]),
                    "dy": int(module["dy"]),
                    "time": round(current_time, 5),
                }
            )

    return events


def module_type_text(module_type):
    return {
        "wait": "等待",
        "key_hold": "按住按键",
        "key_event": "按键事件",
        "mouse_click": "鼠标点击",
        "mouse_move": "鼠标移动",
        "mouse_scroll": "鼠标滚轮",
    }.get(module_type, module_type)


def module_duration_text(module):
    if module["type"] in {"wait", "key_hold", "mouse_click"}:
        return f"{float(module.get('duration', 0.0)):.3f}s"
    return ""


def module_detail_text(module):
    module_type = module["type"]
    if module_type == "wait":
        return "无操作"
    if module_type == "key_hold":
        return f"按键 {key_data_to_text(module['key'])}"
    if module_type == "key_event":
        action = "按下" if module["action"] == "press" else "松开"
        return f"{action} {key_data_to_text(module['key'])}"
    if module_type == "mouse_click":
        return f"{module['button']} at ({module['x']}, {module['y']})"
    if module_type == "mouse_move":
        return f"移动到 ({module['x']}, {module['y']})"
    if module_type == "mouse_scroll":
        return f"滚动 dx={module['dx']}, dy={module['dy']} at ({module['x']}, {module['y']})"
    return ""


class MacroStore:
    def __init__(self, path):
        self.path = path
        self.records = []
        self.load()

    def load(self):
        if not self.path.exists():
            self.records = []
            return
        try:
            with self.path.open("r", encoding="utf-8") as file:
                data = json.load(file)
            self.records = data.get("records", [])
        except (json.JSONDecodeError, OSError):
            self.records = []

    def save(self):
        data = {"version": 1, "records": self.records}
        with self.path.open("w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)

    def add(self, name, events):
        record = {
            "id": str(int(time.time() * 1000)),
            "name": name,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "events": events,
        }
        self.records.append(record)
        self.save()
        return record

    def delete(self, record_id):
        self.records = [record for record in self.records if record["id"] != record_id]
        self.save()

    def rename(self, record_id, name):
        for record in self.records:
            if record["id"] == record_id:
                record["name"] = name
                self.save()
                return record
        return None

    def update_events(self, record_id, events):
        for record in self.records:
            if record["id"] == record_id:
                record["events"] = events
                self.save()
                return record
        return None


class MacroEditor(tk.Toplevel):
    def __init__(self, parent, record):
        super().__init__(parent)
        self.parent = parent
        self.record = record
        self.modules = events_to_modules(record["events"])
        self.field_vars = {
            "duration": tk.StringVar(),
            "key": tk.StringVar(),
            "action": tk.StringVar(),
            "button": tk.StringVar(),
            "x": tk.StringVar(),
            "y": tk.StringVar(),
            "dx": tk.StringVar(),
            "dy": tk.StringVar(),
        }
        self.field_widgets = {}

        self.title(f"查看/编辑记录 - {record['name']}")
        self.geometry("980x560")
        self.minsize(900, 500)
        self.transient(parent)

        self._build_ui()
        self._refresh_module_list()
        if self.modules:
            self.module_tree.selection_set("0")
            self.module_tree.focus("0")
            self._load_selected_module()

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=0)
        self.rowconfigure(0, weight=1)

        left = ttk.Frame(self, padding=(12, 12, 8, 8))
        left.grid(row=0, column=0, sticky="nsew")
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)

        columns = ("index", "type", "duration", "detail")
        self.module_tree = ttk.Treeview(left, columns=columns, show="headings", selectmode="browse")
        self.module_tree.heading("index", text="#")
        self.module_tree.heading("type", text="模块")
        self.module_tree.heading("duration", text="持续")
        self.module_tree.heading("detail", text="内容")
        self.module_tree.column("index", width=48, anchor="center", stretch=False)
        self.module_tree.column("type", width=110, anchor="center", stretch=False)
        self.module_tree.column("duration", width=90, anchor="center", stretch=False)
        self.module_tree.column("detail", width=430)
        self.module_tree.grid(row=0, column=0, sticky="nsew")
        self.module_tree.bind("<<TreeviewSelect>>", self._load_selected_module)
        self.module_tree.bind("<Double-1>", self._load_selected_module)

        scrollbar = ttk.Scrollbar(left, orient="vertical", command=self.module_tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.module_tree.configure(yscrollcommand=scrollbar.set)

        list_buttons = ttk.Frame(left)
        list_buttons.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(list_buttons, text="上移", command=lambda: self._move_selected(-1)).grid(row=0, column=0)
        ttk.Button(list_buttons, text="下移", command=lambda: self._move_selected(1)).grid(row=0, column=1, padx=(8, 0))
        ttk.Button(list_buttons, text="删除模块", command=self._delete_selected).grid(row=0, column=2, padx=(8, 0))

        right = ttk.Frame(self, padding=(8, 12, 12, 8))
        right.grid(row=0, column=1, sticky="ns")
        right.columnconfigure(1, weight=1)

        ttk.Label(right, text="选中模块").grid(row=0, column=0, columnspan=2, sticky="w")
        self.selected_type_text = tk.StringVar(value="未选择")
        ttk.Label(right, textvariable=self.selected_type_text).grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 12))

        fields = [
            ("duration", "持续秒数"),
            ("key", "按键"),
            ("action", "按键动作"),
            ("button", "鼠标按钮"),
            ("x", "X 坐标"),
            ("y", "Y 坐标"),
            ("dx", "横向滚动"),
            ("dy", "纵向滚动"),
        ]

        for row, (name, label) in enumerate(fields, start=2):
            ttk.Label(right, text=label).grid(row=row, column=0, sticky="w", pady=3)
            if name == "action":
                widget = ttk.Combobox(
                    right,
                    textvariable=self.field_vars[name],
                    values=("press", "release"),
                    state="readonly",
                    width=22,
                )
            elif name == "button":
                widget = ttk.Combobox(
                    right,
                    textvariable=self.field_vars[name],
                    values=("left", "right", "middle"),
                    state="readonly",
                    width=22,
                )
            else:
                widget = ttk.Entry(right, textvariable=self.field_vars[name], width=24)
            widget.grid(row=row, column=1, sticky="ew", pady=3)
            self.field_widgets[name] = widget

        ttk.Label(
            right,
            text="按键示例：w、s、space、enter、shift、ctrl_l。等待时间改“持续秒数”。",
            wraplength=250,
        ).grid(row=10, column=0, columnspan=2, sticky="ew", pady=(10, 8))

        ttk.Button(right, text="应用到模块", command=self._apply_selected).grid(row=11, column=0, columnspan=2, sticky="ew")
        ttk.Button(right, text="保存到记录", command=self._save_record).grid(
            row=12, column=0, columnspan=2, sticky="ew", pady=(8, 0)
        )
        ttk.Button(right, text="关闭", command=self.destroy).grid(row=13, column=0, columnspan=2, sticky="ew", pady=(8, 0))

    def _refresh_module_list(self):
        selection = self.module_tree.selection()
        selected_index = int(selection[0]) if selection else None
        for item in self.module_tree.get_children():
            self.module_tree.delete(item)

        for index, module in enumerate(self.modules):
            self.module_tree.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    index + 1,
                    module_type_text(module["type"]),
                    module_duration_text(module),
                    module_detail_text(module),
                ),
            )

        if selected_index is not None and 0 <= selected_index < len(self.modules):
            self.module_tree.selection_set(str(selected_index))
            self.module_tree.focus(str(selected_index))

    def _selected_index(self):
        selection = self.module_tree.selection()
        if not selection:
            return None
        return int(selection[0])

    def _selected_module(self):
        index = self._selected_index()
        if index is None or index >= len(self.modules):
            return None
        return self.modules[index]

    def _load_selected_module(self, _event=None):
        module = self._selected_module()
        for var in self.field_vars.values():
            var.set("")

        if not module:
            self.selected_type_text.set("未选择")
            self._set_enabled_fields(set())
            return

        module_type = module["type"]
        self.selected_type_text.set(module_type_text(module_type))

        if module_type in {"wait", "key_hold", "mouse_click"}:
            self.field_vars["duration"].set(str(module.get("duration", 0.0)))
        if module_type in {"key_hold", "key_event"}:
            self.field_vars["key"].set(key_data_to_text(module["key"]))
        if module_type == "key_event":
            self.field_vars["action"].set(module["action"])
        if module_type == "mouse_click":
            self.field_vars["button"].set(module["button"])
        if module_type in {"mouse_click", "mouse_move", "mouse_scroll"}:
            self.field_vars["x"].set(str(module["x"]))
            self.field_vars["y"].set(str(module["y"]))
        if module_type == "mouse_scroll":
            self.field_vars["dx"].set(str(module["dx"]))
            self.field_vars["dy"].set(str(module["dy"]))

        enabled = {
            "wait": {"duration"},
            "key_hold": {"duration", "key"},
            "key_event": {"key", "action"},
            "mouse_click": {"duration", "button", "x", "y"},
            "mouse_move": {"x", "y"},
            "mouse_scroll": {"x", "y", "dx", "dy"},
        }.get(module_type, set())
        self._set_enabled_fields(enabled)

    def _set_enabled_fields(self, enabled):
        for name, widget in self.field_widgets.items():
            if name in enabled:
                widget.configure(state="readonly" if name in {"action", "button"} else "normal")
            else:
                widget.configure(state="disabled")

    def _parse_duration(self):
        duration = float(self.field_vars["duration"].get())
        if duration < 0:
            raise ValueError("持续秒数不能小于 0")
        return round(duration, 5)

    def _parse_int_field(self, name, label):
        return int(float(self.field_vars[name].get()))

    def _apply_selected(self):
        index = self._selected_index()
        if index is None:
            return False

        module = dict(self.modules[index])
        try:
            module_type = module["type"]
            if module_type == "wait":
                module["duration"] = self._parse_duration()
            elif module_type == "key_hold":
                module["key"] = text_to_key_data(self.field_vars["key"].get())
                module["duration"] = self._parse_duration()
            elif module_type == "key_event":
                module["key"] = text_to_key_data(self.field_vars["key"].get())
                module["action"] = self.field_vars["action"].get()
            elif module_type == "mouse_click":
                button = self.field_vars["button"].get()
                if not hasattr(mouse.Button, button):
                    raise ValueError("鼠标按钮只能是 left、right 或 middle")
                module["button"] = button
                module["x"] = self._parse_int_field("x", "X 坐标")
                module["y"] = self._parse_int_field("y", "Y 坐标")
                module["duration"] = self._parse_duration()
            elif module_type == "mouse_move":
                module["x"] = self._parse_int_field("x", "X 坐标")
                module["y"] = self._parse_int_field("y", "Y 坐标")
            elif module_type == "mouse_scroll":
                module["x"] = self._parse_int_field("x", "X 坐标")
                module["y"] = self._parse_int_field("y", "Y 坐标")
                module["dx"] = self._parse_int_field("dx", "横向滚动")
                module["dy"] = self._parse_int_field("dy", "纵向滚动")
        except ValueError as error:
            messagebox.showerror("无法应用修改", str(error), parent=self)
            return False

        self.modules[index] = module
        self._refresh_module_list()
        self.module_tree.selection_set(str(index))
        self.module_tree.focus(str(index))
        self._load_selected_module()
        return True

    def _move_selected(self, direction):
        index = self._selected_index()
        if index is None:
            return

        target = index + direction
        if target < 0 or target >= len(self.modules):
            return

        self.modules[index], self.modules[target] = self.modules[target], self.modules[index]
        self._refresh_module_list()
        self.module_tree.selection_set(str(target))
        self.module_tree.focus(str(target))
        self.module_tree.see(str(target))
        self._load_selected_module()

    def _delete_selected(self):
        index = self._selected_index()
        if index is None:
            return

        del self.modules[index]
        self._refresh_module_list()
        if self.modules:
            next_index = min(index, len(self.modules) - 1)
            self.module_tree.selection_set(str(next_index))
            self.module_tree.focus(str(next_index))
            self._load_selected_module()
        else:
            self._load_selected_module()

    def _save_record(self):
        index = self._selected_index()
        if index is not None and not self._apply_selected():
            return

        events = modules_to_events(self.modules)
        updated = self.parent.store.update_events(self.record["id"], events)
        if not updated:
            messagebox.showerror("保存失败", "没有找到要保存的记录。", parent=self)
            return

        self.record = updated
        self.parent.status_text.set(f"已更新记录：{updated['name']}，共 {len(events)} 个事件")
        self.parent._refresh_record_list()
        self.parent.record_tree.selection_set(updated["id"])
        self.parent.record_tree.focus(updated["id"])
        self.parent.selected_record_id = updated["id"]
        messagebox.showinfo("已保存", "记录动作已保存。", parent=self)


class MacroApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Python 鼠标键盘宏")
        self.geometry("760x520")
        self.minsize(700, 460)

        self.store = MacroStore(RECORDS_FILE)
        self.mouse_controller = mouse.Controller()
        self.keyboard_controller = keyboard.Controller()

        self.recording = False
        self.playing = False
        self.record_start_time = 0.0
        self.record_events = []
        self.record_pressed_keys = set()
        self.last_move_time = 0.0
        self.mouse_listener = None
        self.keyboard_listener = None
        self.global_hotkey_listener = None
        self.play_thread = None
        self.stop_playback = threading.Event()

        self.status_text = tk.StringVar(value="准备就绪")
        self.play_count_var = tk.StringVar(value="1")
        self.selected_record_id = None
        self.window_bounds = (0, 0, 0, 0)

        self._build_ui()
        self._refresh_record_list()
        self._start_global_hotkeys()
        self.bind("<Configure>", self._update_window_bounds)
        self.after(100, self._update_window_bounds)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        top = ttk.Frame(self, padding=(14, 14, 14, 8))
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(6, weight=1)

        self.start_button = ttk.Button(top, text="开始记录 (F9)", command=self.start_recording)
        self.start_button.grid(row=0, column=0, padx=(0, 8))

        self.finish_button = ttk.Button(top, text="完成记录 (F10)", command=self.finish_recording, state="disabled")
        self.finish_button.grid(row=0, column=1, padx=(0, 8))

        ttk.Label(top, text="运行次数").grid(row=0, column=2, padx=(0, 4))

        self.play_count_entry = ttk.Entry(top, textvariable=self.play_count_var, width=6)
        self.play_count_entry.grid(row=0, column=3, padx=(0, 8))

        self.play_count_button = ttk.Button(top, text="运行", command=self.play_selected_count)
        self.play_count_button.grid(row=0, column=4, padx=(0, 8))

        self.play_loop_button = ttk.Button(top, text="无限重复", command=lambda: self.play_selected(repeat_count=None))
        self.play_loop_button.grid(row=0, column=5, padx=(0, 8))

        self.stop_button = ttk.Button(top, text="停止运行 (F12)", command=self.stop_running, state="disabled")
        self.stop_button.grid(row=0, column=6, sticky="w")

        main = ttk.Frame(self, padding=(14, 6, 14, 8))
        main.grid(row=1, column=0, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(1, weight=1)

        ttk.Label(main, text="已保存记录").grid(row=0, column=0, sticky="w")

        columns = ("name", "events", "created_at")
        self.record_tree = ttk.Treeview(main, columns=columns, show="headings", selectmode="browse")
        self.record_tree.heading("name", text="名称")
        self.record_tree.heading("events", text="事件数")
        self.record_tree.heading("created_at", text="创建时间")
        self.record_tree.column("name", width=310)
        self.record_tree.column("events", width=90, anchor="center")
        self.record_tree.column("created_at", width=180, anchor="center")
        self.record_tree.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
        self.record_tree.bind("<<TreeviewSelect>>", self._on_record_select)
        self.record_tree.bind("<Double-1>", self.rename_selected)

        scrollbar = ttk.Scrollbar(main, orient="vertical", command=self.record_tree.yview)
        scrollbar.grid(row=1, column=1, sticky="ns", pady=(6, 0))
        self.record_tree.configure(yscrollcommand=scrollbar.set)

        bottom = ttk.Frame(self, padding=(14, 0, 14, 14))
        bottom.grid(row=2, column=0, sticky="ew")
        bottom.columnconfigure(3, weight=1)

        self.edit_button = ttk.Button(bottom, text="查看/编辑记录", command=self.edit_selected)
        self.edit_button.grid(row=0, column=0, sticky="w")

        self.rename_button = ttk.Button(bottom, text="重命名选中记录", command=self.rename_selected)
        self.rename_button.grid(row=0, column=1, sticky="w", padx=(8, 0))

        self.delete_button = ttk.Button(bottom, text="删除选中记录", command=self.delete_selected)
        self.delete_button.grid(row=0, column=2, sticky="w", padx=(8, 0))

        ttk.Label(
            bottom,
            text="热键：F9 开始记录，F10 完成记录，F12 停止运行。录制时会忽略本窗口内的鼠标点击。",
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(10, 0))

        status = ttk.Label(self, textvariable=self.status_text, relief="sunken", anchor="w", padding=(8, 4))
        status.grid(row=3, column=0, sticky="ew")

    def _refresh_record_list(self):
        for item in self.record_tree.get_children():
            self.record_tree.delete(item)

        for record in self.store.records:
            self.record_tree.insert(
                "",
                "end",
                iid=record["id"],
                values=(record["name"], len(record["events"]), record["created_at"]),
            )
        self._update_buttons()

    def _on_record_select(self, _event=None):
        selection = self.record_tree.selection()
        self.selected_record_id = selection[0] if selection else None
        self._update_buttons()

    def _update_buttons(self):
        has_selection = self.selected_record_id is not None
        idle = not self.recording and not self.playing

        self.start_button.configure(state="normal" if idle else "disabled")
        self.finish_button.configure(state="normal" if self.recording else "disabled")
        self.play_count_entry.configure(state="normal" if idle else "disabled")
        self.play_count_button.configure(state="normal" if idle and has_selection else "disabled")
        self.play_loop_button.configure(state="normal" if idle and has_selection else "disabled")
        self.edit_button.configure(state="normal" if idle and has_selection else "disabled")
        self.rename_button.configure(state="normal" if idle and has_selection else "disabled")
        self.delete_button.configure(state="normal" if idle and has_selection else "disabled")
        self.stop_button.configure(state="normal" if self.playing else "disabled")

    def _update_window_bounds(self, _event=None):
        self.window_bounds = (
            self.winfo_rootx(),
            self.winfo_rooty(),
            self.winfo_rootx() + self.winfo_width(),
            self.winfo_rooty() + self.winfo_height(),
        )

    def start_recording(self):
        if self.recording or self.playing:
            return

        self.recording = True
        self.record_events = []
        self.record_pressed_keys.clear()
        self.record_start_time = time.perf_counter()
        self.last_move_time = 0.0
        self.status_text.set("正在记录输入，按 F10 完成记录")
        self._update_buttons()

        self.mouse_listener = mouse.Listener(
            on_move=self._on_mouse_move,
            on_click=self._on_mouse_click,
            on_scroll=self._on_mouse_scroll,
        )
        self.keyboard_listener = keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release,
        )
        self.mouse_listener.start()
        self.keyboard_listener.start()

    def _start_global_hotkeys(self):
        self.global_hotkey_listener = keyboard.Listener(on_press=self._on_global_hotkey)
        self.global_hotkey_listener.start()

    def _on_global_hotkey(self, key):
        if key == keyboard.Key.f9 and not self.recording and not self.playing:
            self.after(0, self.start_recording)
        elif key == keyboard.Key.f10 and self.recording:
            self.after(0, self.finish_recording)
        elif key == keyboard.Key.f12 and self.playing:
            self.stop_playback.set()

    def finish_recording(self):
        if not self.recording:
            return

        self._release_recorded_keys()
        self.recording = False
        self._stop_record_listeners()

        events = list(self.record_events)
        self.record_events = []
        self.record_pressed_keys.clear()

        if not events:
            self.status_text.set("没有录到任何可保存的输入")
            self._update_buttons()
            return

        name = simpledialog.askstring("保存记录", "给这段宏起个名字：", parent=self)
        if not name:
            name = time.strftime("宏记录 %Y-%m-%d %H-%M-%S")

        self.store.add(name.strip(), events)
        self.status_text.set(f"已保存：{name.strip()}，共 {len(events)} 个事件")
        self._refresh_record_list()
        self._update_buttons()

    def _stop_record_listeners(self):
        if self.mouse_listener:
            self.mouse_listener.stop()
            self.mouse_listener = None
        if self.keyboard_listener:
            self.keyboard_listener.stop()
            self.keyboard_listener = None

    def _record_time(self):
        return time.perf_counter() - self.record_start_time

    def _add_event(self, event):
        if not self.recording:
            return
        event["time"] = round(self._record_time(), 5)
        self.record_events.append(event)

    def _release_recorded_keys(self):
        for key_kind, key_value in list(self.record_pressed_keys):
            self._add_event(
                {
                    "type": "key",
                    "action": "release",
                    "key": {"kind": key_kind, "value": key_value},
                }
            )
        self.record_pressed_keys.clear()

    def _is_inside_window(self, x, y):
        left, top, right, bottom = self.window_bounds
        return left <= x <= right and top <= y <= bottom

    def _on_mouse_move(self, x, y):
        if not self.recording or self._is_inside_window(x, y):
            return

        now = time.perf_counter()
        if now - self.last_move_time < 0.03:
            return
        self.last_move_time = now
        self._add_event({"type": "mouse_move", "x": x, "y": y})

    def _on_mouse_click(self, x, y, button, pressed):
        if not self.recording or self._is_inside_window(x, y):
            return
        self._add_event(
            {
                "type": "mouse_click",
                "x": x,
                "y": y,
                "button": button_to_name(button),
                "pressed": pressed,
            }
        )

    def _on_mouse_scroll(self, x, y, dx, dy):
        if not self.recording or self._is_inside_window(x, y):
            return
        self._add_event({"type": "mouse_scroll", "x": x, "y": y, "dx": dx, "dy": dy})

    def _on_key_press(self, key):
        if key == keyboard.Key.f10:
            self.after(0, self.finish_recording)
            return False
        if key in CONTROL_KEYS:
            return
        key_data = key_to_data(key)
        key_id = key_data_id(key_data)
        if key_id in self.record_pressed_keys:
            return
        self.record_pressed_keys.add(key_id)
        self._add_event({"type": "key", "action": "press", "key": key_data})

    def _on_key_release(self, key):
        if key in CONTROL_KEYS:
            return
        key_data = key_to_data(key)
        key_id = key_data_id(key_data)
        if key_id not in self.record_pressed_keys:
            return
        self.record_pressed_keys.remove(key_id)
        self._add_event({"type": "key", "action": "release", "key": key_data})

    def get_selected_record(self):
        if not self.selected_record_id:
            return None
        for record in self.store.records:
            if record["id"] == self.selected_record_id:
                return record
        return None

    def play_selected_count(self):
        try:
            repeat_count = int(self.play_count_var.get())
        except ValueError:
            messagebox.showerror("次数无效", "运行次数必须是正整数。", parent=self)
            return

        if repeat_count <= 0:
            messagebox.showerror("次数无效", "运行次数必须大于 0。", parent=self)
            return

        self.play_selected(repeat_count=repeat_count)

    def play_selected(self, repeat_count):
        if self.recording or self.playing:
            return

        record = self.get_selected_record()
        if not record:
            messagebox.showinfo("提示", "请先选择一个记录。")
            return

        self.playing = True
        self.stop_playback.clear()
        mode = "无限重复" if repeat_count is None else f"运行 {repeat_count} 次"
        self.status_text.set(f"正在{mode}：{record['name']}，按 F12 可停止")
        self._update_buttons()

        self.play_thread = threading.Thread(
            target=self._play_worker,
            args=(record, repeat_count),
            daemon=True,
        )
        self.play_thread.start()

    def _play_worker(self, record, repeat_count):
        keyboard_stop_listener = keyboard.Listener(on_press=self._on_playback_hotkey)
        keyboard_stop_listener.start()

        try:
            if repeat_count is None:
                while not self.stop_playback.is_set():
                    self._play_events(record["events"])
            else:
                for index in range(repeat_count):
                    if self.stop_playback.is_set():
                        break
                    self.after(0, self._set_playback_progress, record["name"], index + 1, repeat_count)
                    self._play_events(record["events"])
        finally:
            keyboard_stop_listener.stop()
            self.after(0, self._playback_finished)

    def _set_playback_progress(self, record_name, current, total):
        if not self.playing:
            return
        self.status_text.set(f"正在运行 {current}/{total} 次：{record_name}，按 F12 可停止")

    def _on_playback_hotkey(self, key):
        if key == keyboard.Key.f12:
            self.stop_playback.set()
            return False
        return True

    def _play_events(self, events):
        previous_time = 0.0
        for event in events:
            if self.stop_playback.is_set():
                return

            wait_for = max(0.0, event["time"] - previous_time)
            previous_time = event["time"]
            if self.stop_playback.wait(wait_for):
                return

            self._execute_event(event)

    def _execute_event(self, event):
        event_type = event["type"]

        if event_type == "mouse_move":
            self.mouse_controller.position = (event["x"], event["y"])
            return

        if event_type == "mouse_click":
            self.mouse_controller.position = (event["x"], event["y"])
            button = name_to_button(event["button"])
            if event["pressed"]:
                self.mouse_controller.press(button)
            else:
                self.mouse_controller.release(button)
            return

        if event_type == "mouse_scroll":
            self.mouse_controller.position = (event["x"], event["y"])
            self.mouse_controller.scroll(event["dx"], event["dy"])
            return

        if event_type == "key":
            key = data_to_key(event["key"])
            if event["action"] == "press":
                self.keyboard_controller.press(key)
            else:
                self.keyboard_controller.release(key)

    def _playback_finished(self):
        self.playing = False
        self.stop_playback.clear()
        self.status_text.set("运行已停止")
        self._update_buttons()

    def stop_running(self):
        self.stop_playback.set()
        self.status_text.set("正在停止运行...")

    def edit_selected(self):
        if self.recording or self.playing:
            return

        record = self.get_selected_record()
        if not record:
            return

        MacroEditor(self, record)

    def rename_selected(self, _event=None):
        if self.recording or self.playing:
            return

        record = self.get_selected_record()
        if not record:
            return

        new_name = simpledialog.askstring(
            "重命名记录",
            "请输入新的记录名称：",
            initialvalue=record["name"],
            parent=self,
        )
        if new_name is None:
            return

        new_name = new_name.strip()
        if not new_name:
            messagebox.showinfo("提示", "记录名称不能为空。")
            return

        updated = self.store.rename(record["id"], new_name)
        if not updated:
            messagebox.showerror("错误", "没有找到要修改的记录。")
            return

        self.status_text.set(f"已重命名为：{new_name}")
        self._refresh_record_list()
        self.record_tree.selection_set(updated["id"])
        self.record_tree.focus(updated["id"])
        self.record_tree.see(updated["id"])
        self.selected_record_id = updated["id"]
        self._update_buttons()

    def delete_selected(self):
        record = self.get_selected_record()
        if not record:
            return
        confirmed = messagebox.askyesno("删除记录", f"确定删除“{record['name']}”吗？")
        if not confirmed:
            return
        self.store.delete(record["id"])
        self.selected_record_id = None
        self.status_text.set(f"已删除：{record['name']}")
        self._refresh_record_list()

    def _on_close(self):
        if self.recording:
            self.recording = False
            self._stop_record_listeners()
        if self.playing:
            self.stop_playback.set()
        if self.global_hotkey_listener:
            self.global_hotkey_listener.stop()
        self.destroy()


if __name__ == "__main__":
    app = MacroApp()
    app.mainloop()
