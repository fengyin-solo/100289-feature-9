"""园林机械接口：机械台账、保养记录、保养判定标准与调度看板。

跨班组权限校验放在服务层；路由层只负责把操作人身份（姓名/角色/班组）从请求体
透传下去。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.equipment import EquipmentService

router = APIRouter(prefix="/api/equipment", tags=["园林机械"])

service = EquipmentService()

LIST_FIELDS = [
    "机械编号", "机械名称", "机械类型", "所属班组", "规格型号", "购置日期",
    "上次保养", "下次保养日", "操作人员", "机械状态", "保养判定", "距下次保养天数",
    "超龄提示",
]
STATUSES = ["可用", "使用中", "保养中", "已报废"]


def _operator(payload: EntryPayload | None = None) -> dict[str, str]:
    """从请求体读取操作人身份；缺省时视为无权限的匿名操作。"""
    values = payload.values if payload is not None else {}
    return {
        "name": str(values.get("操作人") or values.get("operatorName") or "").strip(),
        "role": str(values.get("角色") or values.get("role") or "").strip(),
        "team": str(values.get("班组") or values.get("team") or "").strip(),
    }


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按机械编号或名称检索"),
    eq_type: str | None = Query(default=None, description="按机械类型过滤"),
    team: str | None = Query(default=None, description="按所属班组过滤"),
    status: str | None = Query(default=None, description="可用、使用中、保养中、已报废"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """机械台账列表：保养日与判定标记由服务层统一计算，看板与台账同源。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(
        keyword=keyword, eq_type=eq_type, team=team, status=status, page=page, size=size
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/types")
def list_types() -> dict[str, Any]:
    """各机械类型的保养周期与使用年限上限。"""
    return {"items": service.list_rules()}


@router.get("/dispatch-board")
def dispatch_board(team: str | None = None) -> dict[str, Any]:
    """调度看板：已报废机械不出现，临近/超期保养的机械标注缘由且不允许调度。"""
    return {"items": service.dispatch_board(team=team)}


@router.get("/maintenance")
def list_maintenance(
    code: str | None = None, team: str | None = None, only_valid: bool = False
) -> dict[str, Any]:
    """保养记录流水：可按机械编号、班组过滤，默认包含被作废的重复记录。"""
    return {"items": service.list_maintenance(code=code, team=team, only_valid=only_valid)}


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出园林机械台账：返回全量数据（含派生的保养判定字段）。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "equipment", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条园林机械明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"园林机械 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条园林机械，缺字段或类型未配置阈值时说明原因。"""
    entry, problems = service.create_entry(payload.values)
    if problems:
        return ActionResult(ok=False, message="；".join(problems))
    return ActionResult(ok=True, message="园林机械已登记，下次保养日已按类型周期算出", entry=entry)


@router.post("/maintenance", response_model=ActionResult)
def add_maintenance(payload: EntryPayload) -> ActionResult:
    """登记保养记录：仅本班组管理员可改；同机同日重复保养只认第一回。"""
    record, message = service.add_maintenance(payload.values, _operator(payload))
    if record is None:
        return ActionResult(ok=False, message=message)
    ok = bool(record.get("有效", True))
    return ActionResult(ok=ok, message=message, entry=record)


@router.put("/types", response_model=ActionResult)
def update_rules(payload: EntryPayload) -> ActionResult:
    """调整各类型保养周期/年限阈值，调整后全量重算已有保养记录。"""
    raw_rules = payload.values.get("rules")
    if not isinstance(raw_rules, list):
        return ActionResult(ok=False, message="请提交 rules 列表，每项含机械类型/保养周期天数/使用年限上限")
    rules, message = service.update_rules(raw_rules, _operator(payload))
    if rules is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry={"items": rules})


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条园林机械执行安排保养、调度使用、申请报废；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action, _operator(payload))
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
