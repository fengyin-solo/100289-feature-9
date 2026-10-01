"""园林机械保养与调度规则。

统一口径（台账、调度看板、导出共用同一套算法，保证保养日一致）：

1. 下次保养日 = 上次保养日 + 该机械类型的保养周期天数；从未保养过的，自购置日期起算。
2. 距今天不足该类型提醒天数（默认 5 天）或已经超期的，禁止调度使用，并给出缘由。
3. 机龄超过该类型年限上限的，不拦调度，但另作超龄提示。
4. 已报废机械不参与排班。
5. 阈值按机械类型分别配置；判定标准调整后，已有机械的下次保养日按下注即时重算。
6. 保养记录只有本班组管理员可以登记；跨班组、非管理员一律拦下。
7. 同一台机械同一天重复保养只认第一回：重复登记直接拒绝，计算上次保养时也只取当日最早一条。
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.store import Store, store

MODULE = "equipment"
MAINTENANCE_MODULE = "equipment_maintenance"
RULE_MODULE = "equipment_type_rule"

STATUS_AVAILABLE = "可用"
STATUS_IN_USE = "使用中"
STATUS_IN_MAINTENANCE = "保养中"
STATUS_SCRAPPED = "已报废"
STATUSES = [STATUS_AVAILABLE, STATUS_IN_USE, STATUS_IN_MAINTENANCE, STATUS_SCRAPPED]

ROLE_ADMIN = "管理员"

REQUIRED_FIELDS = ["机械编号", "机械名称", "规格型号", "机械类型", "购置日期", "所属班组", "操作人员"]

# 不同机械类型各自的阈值：保养周期（天）、年限上限（年）、提前提醒（天）。
DEFAULT_RULES: list[tuple[str, int, int, int]] = [
    ("割草机", 30, 8, 5),
    ("绿篱机", 25, 6, 5),
    ("油锯", 20, 5, 5),
    ("割灌机", 30, 6, 5),
    ("打孔机", 45, 8, 5),
]


class EquipmentError(Exception):
    """业务校验失败：携带 HTTP 状态码与可读缘由。"""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def parse_date(value: Any, field: str = "日期") -> date | None:
    """解析 YYYY-MM-DD；空值返回 None，非法格式抛业务异常。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise EquipmentError(f"{field}格式应为 YYYY-MM-DD，收到的是「{text}」") from exc


def parse_positive_int(value: Any, field: str) -> int:
    """阈值字段必须是正整数，避免把 0 或负数当成周期。"""
    text = str(value).strip()
    try:
        number = int(text)
    except (TypeError, ValueError) as exc:
        raise EquipmentError(f"{field}必须是正整数，收到的是「{value}」") from exc
    if number <= 0:
        raise EquipmentError(f"{field}必须大于 0，收到的是 {number}")
    return number


class EquipmentService:
    def __init__(self, data_store: Store | None = None) -> None:
        self.store = data_store or store
        # 台账的待处理/异常标记按保养口径推导，避免种子数据与规则脱节。
        self.seed_rules()
        self.recompute_all()

    # ---------- 阈值（按机械类型） ----------

    def seed_rules(self) -> None:
        """首次使用时把默认类型阈值落进仓库，已存在则不覆盖。"""
        rows = self.store.rows(RULE_MODULE)
        existing = {row.get("机械类型") for row in rows}
        next_id = max((int(row.get("id", 0)) for row in rows), default=0) + 1
        for name, cycle, max_age, warn_days in DEFAULT_RULES:
            if name in existing:
                continue
            rows.append({
                "id": next_id,
                "机械类型": name,
                "保养周期天数": cycle,
                "年限上限年数": max_age,
                "提醒提前天数": warn_days,
            })
            next_id += 1

    def list_rules(self) -> list[dict[str, Any]]:
        self.seed_rules()
        return [dict(row) for row in self.store.rows(RULE_MODULE)]

    def rule_map(self) -> dict[str, dict[str, int]]:
        self.seed_rules()
        return {
            str(row["机械类型"]): {
                "保养周期天数": int(row["保养周期天数"]),
                "年限上限年数": int(row["年限上限年数"]),
                "提醒提前天数": int(row["提醒提前天数"]),
            }
            for row in self.store.rows(RULE_MODULE)
        }

    def create_type(self, values: dict[str, Any], identity: dict[str, str]) -> dict[str, Any]:
        self._require_admin(identity)
        name = str(values.get("机械类型") or "").strip()
        if not name:
            raise EquipmentError("缺少必填字段：机械类型")
        if name in self.rule_map():
            raise EquipmentError(f"机械类型「{name}」的阈值已存在，可直接调整")
        rule = {
            "id": max((int(r.get("id", 0)) for r in self.store.rows(RULE_MODULE)), default=0) + 1,
            "机械类型": name,
            "保养周期天数": parse_positive_int(values.get("保养周期天数"), "保养周期天数"),
            "年限上限年数": parse_positive_int(values.get("年限上限年数"), "年限上限年数"),
            "提醒提前天数": parse_positive_int(values.get("提醒提前天数"), "提醒提前天数"),
        }
        self.store.rows(RULE_MODULE).append(rule)
        return dict(rule)

    def update_rule(self, type_name: str, values: dict[str, Any], identity: dict[str, str]) -> tuple[dict[str, Any], int]:
        """调整某类型判定标准，并重算所有在册机械的下次保养日。"""
        self._require_admin(identity)
        target = next((row for row in self.store.rows(RULE_MODULE) if row.get("机械类型") == type_name), None)
        if target is None:
            raise EquipmentError(f"机械类型「{type_name}」尚未配置阈值", status_code=404)
        for field in ("保养周期天数", "年限上限年数", "提醒提前天数"):
            if values.get(field) is not None and str(values.get(field)).strip() != "":
                target[field] = parse_positive_int(values.get(field), field)
        affected = self.recompute_all()
        return dict(target), affected

    # ---------- 台账 ----------

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        machine_type: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = self.store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("机械编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if machine_type:
            rows = [row for row in rows if row.get("机械类型") == machine_type]
        decorated = [self.decorate(row) for row in rows]
        total = len(decorated)
        start = max(page - 1, 0) * size
        return decorated[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any]:
        entry = self.store.find(MODULE, entry_id)
        if entry is None:
            raise EquipmentError(f"园林机械 {entry_id} 不存在或已归档", status_code=404)
        return self.decorate(entry)

    def create_entry(self, values: dict[str, Any], identity: dict[str, str]) -> dict[str, Any]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            raise EquipmentError(f"缺少必填字段：{'、'.join(missing)}")
        machine_type = str(values["机械类型"]).strip()
        if machine_type not in self.rule_map():
            raise EquipmentError(f"机械类型「{machine_type}」未配置保养阈值，请先在类型阈值里登记")
        purchase_date = parse_date(values.get("购置日期"), "购置日期")
        code = str(values["机械编号"]).strip()
        if any(row.get("机械编号") == code for row in self.store.rows(MODULE)):
            raise EquipmentError(f"机械编号「{code}」已存在，台账不允许重复登记")
        entry = {
            "id": max((int(row.get("id", 0)) for row in self.store.rows(MODULE)), default=0) + 1,
            "机械编号": code,
            "机械名称": str(values["机械名称"]).strip(),
            "机械类型": machine_type,
            "规格型号": str(values["规格型号"]).strip(),
            "购置日期": purchase_date.isoformat(),
            "所属班组": str(values["所属班组"]).strip(),
            "操作人员": str(values["操作人员"]).strip(),
            "status": STATUS_AVAILABLE,
        }
        self.store.rows(MODULE).append(entry)
        self._sync_flags(entry)
        return self.decorate(entry)

    # ---------- 保养记录 ----------

    def list_maintenance(self, keyword: str | None = None) -> list[dict[str, Any]]:
        rows = self.store.rows(MAINTENANCE_MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("机械编号", ""))]
        rows = sorted(rows, key=lambda row: (str(row.get("保养日期", "")), int(row.get("id", 0))), reverse=True)
        return [dict(row) for row in rows]

    def register_maintenance(self, values: dict[str, Any], identity: dict[str, str]) -> tuple[dict[str, Any], dict[str, Any]]:
        """登记一次保养：本班组管理员限定，同机同日重复保养只认第一回。"""
        code = str(values.get("机械编号") or "").strip()
        if not code:
            raise EquipmentError("缺少必填字段：机械编号")
        entry = self._find_by_code(code)
        self._require_team_admin(entry, identity)
        if entry.get("status") == STATUS_SCRAPPED:
            raise EquipmentError(f"机械「{code}」已报废，不再登记保养")
        maintenance_date = parse_date(values.get("保养日期"), "保养日期")
        if maintenance_date is None:
            raise EquipmentError("缺少必填字段：保养日期")
        if maintenance_date > date.today():
            raise EquipmentError("保养日期不能晚于今天，不允许预填保养")
        # 同一台机械同一天重复保养只认第一回。
        duplicate = next(
            (
                row for row in self.store.rows(MAINTENANCE_MODULE)
                if row.get("机械编号") == code and str(row.get("保养日期")) == maintenance_date.isoformat()
            ),
            None,
        )
        if duplicate is not None:
            raise EquipmentError(
                f"机械「{code}」在 {maintenance_date.isoformat()} 的保养已由 {duplicate.get('登记人', '管理员')} "
                f"登记过（记录 #{duplicate.get('id')}），同一台机械重复保养只认第一回"
            )
        record = {
            "id": max((int(row.get("id", 0)) for row in self.store.rows(MAINTENANCE_MODULE)), default=0) + 1,
            "机械编号": code,
            "保养日期": maintenance_date.isoformat(),
            "保养内容": str(values.get("保养内容") or "").strip() or "常规保养",
            "登记人": identity["name"],
            "所属班组": identity["team"],
        }
        self.store.rows(MAINTENANCE_MODULE).append(record)
        entry["status"] = STATUS_AVAILABLE
        self._sync_flags(entry)
        return record, self.decorate(entry)

    # ---------- 调度 ----------

    def dispatch(self, entry_id: int, identity: dict[str, str]) -> tuple[dict[str, Any], str]:
        entry = self.store.find(MODULE, entry_id)
        if entry is None:
            raise EquipmentError(f"园林机械 {entry_id} 不存在或已归档", status_code=404)
        decorated = self.decorate(entry)
        if not bool(decorated["可调度"]):
            raise EquipmentError(f"调度被拦下：{decorated['调度说明']}")
        entry["status"] = STATUS_IN_USE
        self._sync_flags(entry)
        decorated = self.decorate(entry)
        note = f"机械「{entry.get('机械编号')}」已调度使用"
        if decorated.get("超龄提示"):
            note += f"；另请注意：{decorated['超龄提示']}"
        return decorated, note

    def scrap(self, entry_id: int, identity: dict[str, str]) -> dict[str, Any]:
        entry = self.store.find(MODULE, entry_id)
        if entry is None:
            raise EquipmentError(f"园林机械 {entry_id} 不存在或已归档", status_code=404)
        self._require_team_admin(entry, identity)
        if entry.get("status") == STATUS_SCRAPPED:
            raise EquipmentError(f"机械「{entry.get('机械编号')}」已报废，无需重复申请")
        entry["status"] = STATUS_SCRAPPED
        self._sync_flags(entry)
        return self.decorate(entry)

    def dispatch_board(self) -> dict[str, Any]:
        """调度看板：已报废机械剔除；禁排机械排在前面，其余按到期紧迫程度排序。

        看板字段直接取自 decorate()，与台账共用同一口径，杜绝两边保养日不一致。
        """
        rows = [self.decorate(row) for row in self.store.rows(MODULE)]
        scrapped = [row for row in rows if row.get("status") == STATUS_SCRAPPED]
        schedulable_rows = [row for row in rows if row.get("status") != STATUS_SCRAPPED]

        def sort_key(row: dict[str, Any]) -> tuple[int, int]:
            blocked = 0 if not row.get("可调度") else 1
            return blocked, int(row.get("距保养天数") if row.get("距保养天数") is not None else 10**6)

        schedulable_rows.sort(key=sort_key)
        blocked = [row for row in schedulable_rows if not row.get("可调度")]
        over_age = [row for row in schedulable_rows if row.get("超龄提示")]
        return {
            "today": date.today().isoformat(),
            "items": schedulable_rows,
            "summary": {
                "在册机械": len(rows),
                "参与排班": len(schedulable_rows),
                "可调度": len(schedulable_rows) - len(blocked),
                "禁止调度": len(blocked),
                "超龄提示": len(over_age),
                "已报废剔除": len(scrapped),
            },
        }

    # ---------- 核心口径：下次保养日 / 调度判定 ----------

    def _latest_maintenance(self, code: str) -> dict[str, Any] | None:
        """取该机械的上次保养：日期最大的一次；同一天只认第一回（id 最小）。"""
        records = [row for row in self.store.rows(MAINTENANCE_MODULE) if row.get("机械编号") == code]
        if not records:
            return None
        records.sort(key=lambda row: (str(row.get("保养日期", "")), -int(row.get("id", 0))), reverse=True)
        return records[0]

    def decorate(self, row: dict[str, Any], today: date | None = None) -> dict[str, Any]:
        """给台账行补上保养日、机龄、调度结论等派生字段；所有读口径都从这里出。"""
        today = today or date.today()
        data = dict(row)
        rules = self.rule_map()
        machine_type = str(row.get("机械类型") or "")
        rule = rules.get(machine_type)

        data["保养周期天数"] = rule["保养周期天数"] if rule else None
        data["提醒提前天数"] = rule["提醒提前天数"] if rule else None
        data["年限上限"] = rule["年限上限年数"] if rule else None

        purchase = parse_date(row.get("购置日期"), "购置日期")
        age_years = completed_years(purchase, today) if purchase else None
        data["机龄"] = age_years

        latest = self._latest_maintenance(str(row.get("机械编号", "")))
        last_date = parse_date(latest.get("保养日期"), "保养日期") if latest else None
        data["上次保养"] = last_date.isoformat() if last_date else "—"

        base_date = last_date or purchase
        if base_date and rule:
            next_date = base_date + timedelta(days=rule["保养周期天数"])
            days_left = (next_date - today).days
            data["下次保养日"] = next_date.isoformat()
            data["距保养天数"] = days_left
        else:
            next_date = None
            days_left = None
            data["下次保养日"] = "—"
            data["距保养天数"] = None

        data["保养口径"], data["可调度"], reason = self._maintenance_verdict(
            status=str(row.get("status") or ""),
            next_date=next_date,
            days_left=days_left,
            warn_days=rule["提醒提前天数"] if rule else None,
            has_rule=rule is not None,
        )

        over_age_warning = None
        if age_years is not None and rule and age_years > rule["年限上限年数"]:
            over_age_warning = (
                f"机械已超龄：机龄 {age_years} 年，超过{machine_type}上限 {rule['年限上限年数']} 年，建议安排更新"
            )
        data["超龄"] = over_age_warning is not None
        data["超龄提示"] = over_age_warning

        if data["可调度"]:
            data["调度说明"] = "可调度"
            if over_age_warning:
                data["调度说明"] = f"可调度（超龄提示：{over_age_warning}）"
        else:
            data["调度说明"] = reason
        return data

    @staticmethod
    def _maintenance_verdict(
        *,
        status: str,
        next_date: date | None,
        days_left: int | None,
        warn_days: int | None,
        has_rule: bool,
    ) -> tuple[str, bool, str]:
        if status == STATUS_SCRAPPED:
            return "已报废", False, "机械已报废，不参与排班"
        if status == STATUS_IN_MAINTENANCE:
            return "保养中", False, "机械正在保养，暂不可调度"
        if not has_rule:
            return "阈值缺失", False, f"该机械类型尚未配置保养阈值，无法判定保养周期"
        if next_date is None or days_left is None:
            return "无法核算", False, "缺少购置日期与保养记录，算不出下次保养日，暂不调度"
        warn_days = warn_days if warn_days is not None else 5
        if days_left < 0:
            return "已超期", False, f"保养已超期 {-days_left} 天（下次保养日 {next_date.isoformat()}），禁止调度"
        if days_left <= warn_days:
            return "临近保养", False, (
                f"距下次保养仅剩 {days_left} 天（下次保养日 {next_date.isoformat()}），"
                f"不足 {warn_days} 天，禁止调度"
            )
        return "保养正常", True, ""

    def recompute_all(self) -> int:
        """判定标准调整后重算在册机械的派生口径与异常标记，返回涉及的机械台数。"""
        for row in self.store.rows(MODULE):
            self._sync_flags(row)
        return len(self.store.rows(MODULE))

    def _sync_flags(self, row: dict[str, Any]) -> None:
        """把动态口径落到 pending/abnormal，供运营概览汇总；报废一律不算待处理。"""
        decorated = self.decorate(row)
        if row.get("status") == STATUS_SCRAPPED:
            row["pending"] = False
            row["abnormal"] = False
            return
        row["pending"] = decorated["保养口径"] in {"临近保养", "已超期", "无法核算", "阈值缺失", "保养中"}
        row["abnormal"] = decorated["保养口径"] == "已超期"

    # ---------- 权限 ----------

    @staticmethod
    def _require_admin(identity: dict[str, str]) -> None:
        if identity.get("role") != ROLE_ADMIN:
            raise EquipmentError(
                f"只有管理员才能调整保养口径与类型阈值，当前身份是「{identity.get('role')}」",
                status_code=403,
            )

    @staticmethod
    def _require_team_admin(entry: dict[str, Any], identity: dict[str, str]) -> None:
        """只有本班组管理员才能改动该机械的保养记录，跨班组直接拦下。"""
        if identity.get("role") != ROLE_ADMIN:
            raise EquipmentError(
                f"只有本班组管理员才能登记保养，当前身份是「{identity.get('role')}」",
                status_code=403,
            )
        if identity.get("team") != entry.get("所属班组"):
            raise EquipmentError(
                f"跨班组改动被拦下：机械「{entry.get('机械编号')}」归属{entry.get('所属班组')}，"
                f"当前账号属于{identity.get('team')}",
                status_code=403,
            )

    # ---------- 辅助 ----------

    def _find_by_code(self, code: str) -> dict[str, Any]:
        entry = next((row for row in self.store.rows(MODULE) if row.get("机械编号") == code), None)
        if entry is None:
            raise EquipmentError(f"机械编号「{code}」不在台账中", status_code=404)
        return entry


def completed_years(past: date, today: date) -> int:
    """按整年算机龄：未到本年同月同日不计一年。"""
    return today.year - past.year - ((today.month, today.day) < (past.month, past.day))


service = EquipmentService()
