"""园林机械业务规则。

保养判定口径（统一在这里计算，台账与调度看板共用同一份结果）：

1. 下次保养日 = 最近一次有效保养日期 + 该机械类型的保养周期；
   从未保养过的机械，从购置日期起算。
2. 距下次保养日不足 5 天（含当天）或已经超期的机械，不许调度使用，
   返回明确缘由。
3. 机械年限超过该类型上限的，调度不拦，但单独给出超龄提示。
4. 已报废机械不参与排班，调度看板中直接剔除。
5. 保养周期/年限阈值按机械类型分别配置；判定标准调整后，全量重算已有
   保养记录与台账派生字段。
6. 同一台机械同一保养日期重复登记，只认第一回，后到记录作废并说明原因。
7. 只有本班组管理员能登记/改动保养记录，跨班组改动一律拦下。
"""
from __future__ import annotations

import copy
from datetime import date, datetime, timedelta
from typing import Any

from app.store import store

MODULE = "equipment"
MAINTENANCE_MODULE = "equipment_maintenance"

REQUIRED_FIELDS = ["机械编号", "机械名称", "机械类型", "规格型号", "购置日期", "所属班组"]
STATUS_ORDER = ["可用", "使用中", "保养中", "已报废"]
ACTION_RULES = {"安排保养": "保养中", "调度使用": "使用中", "申请报废": "已报废"}

# 距下次保养日不足该天数（含）即禁止调度
DISPATCH_WARNING_DAYS = 5

# 各机械类型单独给阈值：保养周期（天）、使用年限上限（年）
DEFAULT_TYPE_RULES: dict[str, dict[str, int]] = {
    "油锯": {"保养周期天数": 30, "使用年限上限": 8},
    "绿篱机": {"保养周期天数": 30, "使用年限上限": 6},
    "割草机": {"保养周期天数": 30, "使用年限上限": 6},
    "割灌机": {"保养周期天数": 45, "使用年限上限": 6},
    "吹风机": {"保养周期天数": 45, "使用年限上限": 8},
}


def _parse_date(value: Any) -> date | None:
    """尽量宽容地解析 YYYY-MM-DD 日期；解析不了返回 None。"""
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


class EquipmentService:
    def __init__(self) -> None:
        # 运行期可调整的判定标准；调整后触发全量重算
        self.type_rules: dict[str, dict[str, int]] = copy.deepcopy(DEFAULT_TYPE_RULES)

    # ---- 通用读取 ------------------------------------------------------

    def rule_for(self, eq_type: Any) -> dict[str, int] | None:
        return self.type_rules.get(str(eq_type or "").strip())

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        eq_type: str | None = None,
        team: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [
                row for row in rows
                if keyword in str(row.get("机械编号", ""))
                or keyword in str(row.get("机械名称", ""))
            ]
        if eq_type:
            rows = [row for row in rows if str(row.get("机械类型", "")) == eq_type]
        if team:
            rows = [row for row in rows if str(row.get("所属班组", "")) == team]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        rows = [self._decorate(row) for row in rows]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        return self._decorate(entry) if entry else None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        eq_type = str(values.get("机械类型") or "").strip()
        if self.rule_for(eq_type) is None:
            return None, [f"机械类型「{eq_type}」尚未配置保养周期与年限阈值"]
        if _parse_date(values.get("购置日期")) is None:
            return None, ["购置日期需为 YYYY-MM-DD 格式"]
        rows = store.rows(MODULE)
        code = str(values.get("机械编号") or "").strip()
        if any(str(row.get("机械编号")) == code for row in rows):
            return None, [f"机械编号 {code} 已存在，请勿重复登记"]
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        for field in REQUIRED_FIELDS:
            entry[field] = str(values.get(field) or "").strip()
        entry["规格型号"] = str(values.get("规格型号") or "").strip()
        entry["上次保养"] = str(values.get("上次保养") or "").strip()
        entry["下次保养日"] = ""
        entry["操作人员"] = str(values.get("操作人员") or "").strip()
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        entry["机械状态"] = STATUS_ORDER[0]
        # 登记时若补录了上次保养，同步落一条有效保养记录
        backfill_day = str(values.get("上次保养") or "").strip()
        if backfill_day:
            if _parse_date(backfill_day) is None:
                return None, ["上次保养需为 YYYY-MM-DD 格式"]
            self._append_maintenance(
                code, backfill_day, "登记台账时补录",
                str(values.get("登记人") or values.get("操作人员") or ""),
                entry["所属班组"],
            )
        rows.append(entry)
        self.recompute_all()
        return self._decorate(entry), []

    # ---- 状态动作 ------------------------------------------------------

    def run_action(
        self, entry_id: int, action: str, operator: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"园林机械 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于园林机械可执行范围"

        view = self._decorate(entry)
        if action == "调度使用":
            allowed, reason = self._dispatch_check(view, operator)
            if not allowed:
                return None, reason

        target = ACTION_RULES[action]
        entry["status"] = target
        entry["机械状态"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = False
        note = f"园林机械已{action}"
        if action == "调度使用" and view.get("超龄提示"):
            note += f"；提示：{view['超龄提示']}"
        return self._decorate(entry), note

    def _dispatch_check(
        self, view: dict[str, Any], operator: dict[str, Any] | None
    ) -> tuple[bool, str]:
        """调度准入口径：已报废、临近保养（<5天）、已超期一律拦下。"""
        if view.get("status") == "已报废":
            return False, f"{view.get('机械编号')} 已报废，不参与排班"
        flag = str(view.get("保养判定") or "")
        next_day = view.get("下次保养日") or "未算出"
        if flag == "已超期":
            return False, (
                f"{view.get('机械编号')} 已超过保养期限（下次保养日 {next_day}），"
                "完成保养前不许调度使用"
            )
        if flag == "临近保养":
            return False, (
                f"{view.get('机械编号')} 距下次保养日（{next_day}）不足 "
                f"{DISPATCH_WARNING_DAYS} 天，暂不调度，请先安排保养"
            )
        if not view.get("下次保养日"):
            return False, f"{view.get('机械编号')} 缺少保养周期配置或日期有误，无法核算保养日，暂不调度"
        return True, ""

    # ---- 保养记录 ------------------------------------------------------

    def list_maintenance(
        self,
        *,
        code: str | None = None,
        team: str | None = None,
        only_valid: bool = False,
    ) -> list[dict[str, Any]]:
        rows = store.rows(MAINTENANCE_MODULE)
        equipment = {str(row.get("机械编号")): row for row in store.rows(MODULE)}
        result: list[dict[str, Any]] = []
        for record in rows:
            eq = equipment.get(str(record.get("机械编号")))
            record_team = str((eq or {}).get("所属班组") or record.get("登记班组") or "")
            if code and str(record.get("机械编号")) != code:
                continue
            if team and record_team != team:
                continue
            if only_valid and not record.get("有效", True):
                continue
            item = dict(record)
            item["所属班组"] = record_team
            result.append(item)
        result.sort(key=lambda r: (str(r.get("机械编号")), str(r.get("保养日期")), int(r.get("id", 0))))
        return result

    def add_maintenance(
        self, values: dict[str, Any], operator: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, str]:
        """登记保养记录。权限：必须是该机械所属班组的管理员。"""
        code = str(values.get("机械编号") or "").strip()
        day = _parse_date(values.get("保养日期"))
        content = str(values.get("保养内容") or "").strip()

        auth, reason = self._require_team_admin(operator, code=code)
        if not auth:
            return None, reason
        if not code:
            return None, "缺少机械编号，无法登记保养记录"
        if day is None:
            return None, "保养日期需为 YYYY-MM-DD 格式"
        if day > date.today():
            return None, "保养日期不能晚于今天"
        if not content:
            return None, "请填写保养内容"
        target = self._find_by_code(code)
        if target is not None and target.get("status") == "已报废":
            return None, f"{code} 已报废，不再登记保养记录"

        # 同一台机械同一天重复保养只认第一回
        dup = self._find_record(code, day)
        record = self._append_maintenance(
            code, day.isoformat(), content,
            str(operator.get("name") or ""), str(operator.get("team") or ""),
        )
        if dup is not None:
            record["有效"] = False
            record["作废原因"] = (
                f"{code} 在 {day.isoformat()} 已有首次保养记录（记录#{dup.get('id')}），"
                "同一台机械重复保养只认第一回"
            )
            self._sync_equipment(code)
            return record, (
                f"保养记录已登记但作废：{record['作废原因']}；"
                f"下次保养日仍按首次保养计算"
            )

        self._sync_equipment(code)
        return record, f"{code} 保养记录已登记，下次保养日已重算为 {self._next_day_text(code)}"

    def _require_team_admin(
        self, operator: dict[str, Any] | None, *, code: str | None = None, team: str | None = None
    ) -> tuple[bool, str]:
        if not operator or str(operator.get("role") or "") != "管理员":
            return False, "只有本班组管理员才能改动保养记录"
        operator_team = str(operator.get("team") or "").strip()
        if not operator_team:
            return False, "当前身份缺少班组信息，无法核验改动权限"
        target_team = team
        if code is not None:
            entry = self._find_by_code(code)
            if entry is None:
                return False, f"机械编号 {code} 不存在或已归档"
            target_team = str(entry.get("所属班组") or "")
        if target_team and operator_team != target_team:
            return False, (
                f"跨班组改动已拦下：该机械属「{target_team}」，"
                f"当前身份是「{operator_team}」管理员"
            )
        return True, ""

    def _append_maintenance(
        self, code: str, day: str, content: str, registrar: str, team: str
    ) -> dict[str, Any]:
        rows = store.rows(MAINTENANCE_MODULE)
        record = {
            "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
            "机械编号": code,
            "保养日期": day,
            "保养内容": content,
            "登记人": registrar,
            "登记班组": team,
            "有效": True,
            "作废原因": "",
        }
        rows.append(record)
        return record

    def _find_record(self, code: str, day: date) -> dict[str, Any] | None:
        for record in store.rows(MAINTENANCE_MODULE):
            if (
                str(record.get("机械编号")) == code
                and _parse_date(record.get("保养日期")) == day
            ):
                return record
        return None

    # ---- 判定标准（类型阈值） ------------------------------------------

    def list_rules(self) -> list[dict[str, Any]]:
        return [
            {"机械类型": eq_type, "保养周期天数": rule["保养周期天数"],
             "使用年限上限": rule["使用年限上限"]}
            for eq_type, rule in self.type_rules.items()
        ]

    def update_rules(
        self, rules: list[dict[str, Any]], operator: dict[str, Any]
    ) -> tuple[list[dict[str, Any]] | None, str]:
        """调整各类型阈值，随后全量重算已有保养记录与台账。"""
        if not operator or str(operator.get("role") or "") != "管理员":
            return None, "只有管理员才能调整保养判定标准"
        normalized: dict[str, dict[str, int]] = {}
        for item in rules:
            eq_type = str(item.get("机械类型") or "").strip()
            try:
                cycle = int(item.get("保养周期天数"))
                age_limit = int(item.get("使用年限上限"))
            except (TypeError, ValueError):
                return None, f"类型「{eq_type}」的周期与年限必须是整数"
            if not eq_type:
                return None, "存在未填写机械类型的阈值行"
            if cycle <= 0 or age_limit <= 0:
                return None, f"类型「{eq_type}」的周期与年限必须大于 0"
            normalized[eq_type] = {"保养周期天数": cycle, "使用年限上限": age_limit}
        if not normalized:
            return None, "没有收到任何类型阈值"

        known = set(self.type_rules)
        unknown = set(normalized) - known
        if unknown:
            return None, "以下类型尚无机械在册，暂不支持新增阈值：" + "、".join(sorted(unknown))

        self.type_rules = normalized
        voided = self.recompute_all()
        return self.list_rules(), f"判定标准已更新，已重算全部保养记录；新作废重复记录 {voided} 条"

    # ---- 重算口径 ------------------------------------------------------

    def recompute_all(self) -> int:
        """判定标准调整后重算：重复保养重新认定，台账的保养口径全部刷新。"""
        seen: set[tuple[str, str]] = set()
        voided = 0
        # 按登记先后（id）认定：同机同日只认第一回
        records = sorted(store.rows(MAINTENANCE_MODULE), key=lambda r: int(r.get("id", 0)))
        for record in records:
            key = (str(record.get("机械编号")), str(record.get("保养日期")))
            if key in seen:
                if record.get("有效", True):
                    voided += 1
                record["有效"] = False
                if not record.get("作废原因"):
                    record["作废原因"] = "判定标准重算：与同日首次保养记录重复，只认第一回"
            else:
                seen.add(key)
                record["有效"] = True
                record["作废原因"] = ""
        for entry in store.rows(MODULE):
            self._sync_equipment(str(entry.get("机械编号")))
        return voided

    def _sync_equipment(self, code: str) -> None:
        """把一台机械的「上次保养/下次保养日」按有效保养记录刷新回台账。"""
        entry = self._find_by_code(code)
        if entry is None:
            return
        valid_days = [
            _parse_date(record.get("保养日期"))
            for record in store.rows(MAINTENANCE_MODULE)
            if str(record.get("机械编号")) == code and record.get("有效", True)
        ]
        valid_days = [day for day in valid_days if day is not None]
        last_day = max(valid_days, default=None)
        entry["上次保养"] = last_day.isoformat() if last_day else ""

        rule = self.rule_for(entry.get("机械类型"))
        base = last_day or _parse_date(entry.get("购置日期"))
        if rule and base is not None:
            entry["下次保养日"] = (base + timedelta(days=rule["保养周期天数"])).isoformat()
        else:
            entry["下次保养日"] = ""

    def _next_day_text(self, code: str) -> str:
        entry = self._find_by_code(code)
        return str((entry or {}).get("下次保养日") or "未算出")

    def _find_by_code(self, code: str) -> dict[str, Any] | None:
        for row in store.rows(MODULE):
            if str(row.get("机械编号")) == code:
                return row
        return None

    # ---- 调度看板 ------------------------------------------------------

    def dispatch_board(
        self, *, team: str | None = None, operator: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """调度看板：已报废机械不参与排班；保养日直接取台账重算结果，保证一致。"""
        rows = store.rows(MODULE)
        if team:
            rows = [row for row in rows if str(row.get("所属班组")) == team]
        board: list[dict[str, Any]] = []
        for row in rows:
            view = self._decorate(row)
            if view.get("status") == "已报废":
                continue
            allowed, reason = self._dispatch_check(view, operator)
            # 保养中的机械暂不排班，但仍在看板上展示并说明
            if view.get("status") == "保养中":
                allowed, reason = False, "正在保养中，保养完成后方可调度"
            board.append({
                "机械编号": view.get("机械编号"),
                "机械名称": view.get("机械名称"),
                "机械类型": view.get("机械类型"),
                "所属班组": view.get("所属班组"),
                "上次保养": view.get("上次保养"),
                "下次保养日": view.get("下次保养日"),
                "保养判定": view.get("保养判定"),
                "超龄提示": view.get("超龄提示"),
                "状态": view.get("status"),
                "允许调度": allowed,
                "缘由": reason,
            })
        board.sort(key=lambda item: (item["允许调度"], str(item["机械编号"])))
        return board

    # ---- 派生字段 ------------------------------------------------------

    def _decorate(self, entry: dict[str, Any]) -> dict[str, Any]:
        """台账与看板共用的派生口径：保养判定、超龄提示、调度缘由。"""
        view = dict(entry)
        rule = self.rule_for(entry.get("机械类型"))
        today = date.today()

        next_day = _parse_date(entry.get("下次保养日"))
        if not next_day:
            # 台账上没有预算结果时即时补算（与重算口径一致）
            base = _parse_date(entry.get("上次保养")) or _parse_date(entry.get("购置日期"))
            if rule and base is not None:
                next_day = base + timedelta(days=rule["保养周期天数"])
                view["下次保养日"] = next_day.isoformat()

        flag = "未配置"
        if next_day is not None:
            delta = (next_day - today).days
            if delta < 0:
                flag = "已超期"
            elif delta < DISPATCH_WARNING_DAYS:
                flag = "临近保养"
            else:
                flag = "正常"
        view["保养判定"] = flag
        view["距下次保养天数"] = (next_day - today).days if next_day else None
        view["保养周期天数"] = rule["保养周期天数"] if rule else None

        age_tip = ""
        purchased = _parse_date(entry.get("购置日期"))
        if rule and purchased is not None:
            age_years = (today - purchased).days / 365.25
            view["使用年限"] = round(age_years, 1)
            if age_years > rule["使用年限上限"]:
                age_tip = (
                    f"已使用约 {age_years:.1f} 年，超过{entry.get('机械类型')}"
                    f"年限上限 {rule['使用年限上限']} 年，建议评估淘汰"
                )
        else:
            view["使用年限"] = None
        view["超龄提示"] = age_tip
        return view
