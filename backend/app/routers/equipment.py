"""园林机械接口：台账、保养记录、调度看板、类型阈值都收在这一组路由里。

身份通过三个请求头带入（前端会话固定发送）：X-Operator（姓名）、X-Team（班组）、X-Role（角色）。
缺省按“一班管理员”处理，方便本地直接联调。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import JSONResponse

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.equipment import EquipmentError, service

router = APIRouter(prefix="/api/equipment", tags=["园林机械"])

LIST_FIELDS = [
    "机械编号", "机械名称", "机械类型", "规格型号", "购置日期", "机龄",
    "上次保养", "下次保养日", "距保养天数", "保养口径",
    "所属班组", "操作人员", "机械状态", "调度说明",
]
STATUSES = ["可用", "使用中", "保养中", "已报废"]


def identity(
    x_operator: str = Header(default="一班管理员"),
    x_team: str = Header(default="一班"),
    x_role: str = Header(default="管理员"),
) -> dict[str, str]:
    return {"name": x_operator, "team": x_team, "role": x_role}


def _fail(exc: EquipmentError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按机械编号检索"),
    status: str | None = Query(default=None, description="可用、使用中、保养中、已报废"),
    machine_type: str | None = Query(default=None, description="按机械类型过滤"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按机械编号、状态、类型过滤台账；保养日与调度结论按统一口径实时算出。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(
        keyword=keyword, status=status, machine_type=machine_type, page=page, size=size
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/dispatch/board")
def dispatch_board() -> dict[str, Any]:
    """调度看板：已报废机械剔除，禁止调度的机械置顶并给出缘由，保养日与台账同口径。"""
    return service.dispatch_board()


@router.get("/maintenance/records")
def list_maintenance(keyword: str | None = Query(default=None, description="按机械编号检索保养记录")) -> dict[str, Any]:
    """保养记录流水：按保养日期倒序，只列出口径认可的有效记录。"""
    return {"items": service.list_maintenance(keyword=keyword)}


@router.get("/types")
def list_types() -> dict[str, Any]:
    """各机械类型的保养周期、年限上限与提前提醒阈值。"""
    return {"items": service.list_rules()}


@router.post("/types")
def create_type(payload: EntryPayload, who: dict[str, str] = identity) -> ActionResult:
    """新增一个机械类型的阈值（管理员限定）。"""
    try:
        rule = service.create_type(payload.values, who)
    except EquipmentError as exc:
        raise _fail(exc) from exc
    return ActionResult(ok=True, message=f"机械类型「{rule['机械类型']}」阈值已建立", entry=rule)


@router.put("/types/{type_name}", response_model=ActionResult)
def update_type(type_name: str, payload: EntryPayload, who: dict[str, str] = identity) -> ActionResult:
    """调整判定标准（周期/年限/提醒天数），保存后立即重算全部在册机械。"""
    try:
        rule, affected = service.update_rule(type_name, payload.values, who)
    except EquipmentError as exc:
        raise _fail(exc) from exc
    return ActionResult(
        ok=True,
        message=f"「{type_name}」阈值已调整，已按新口径重算 {affected} 台机械的保养日",
        entry=rule,
    )


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出园林机械清单：保养日等派生字段与台账页面完全一致。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "equipment", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条园林机械明细；不存在时给出可读的错误说明。"""
    try:
        return service.get_entry(entry_id)
    except EquipmentError as exc:
        raise _fail(exc) from exc


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload, who: dict[str, str] = identity) -> ActionResult:
    """登记一条园林机械，缺字段或类型未配置阈值时说明原因而不是静默丢弃。"""
    try:
        entry = service.create_entry(payload.values, who)
    except EquipmentError as exc:
        raise _fail(exc) from exc
    return ActionResult(ok=True, message="园林机械已登记，下次保养日已按类型周期算出", entry=entry)


@router.post("/maintenance/register", response_model=ActionResult)
def register_maintenance(payload: EntryPayload, who: dict[str, str] = identity) -> ActionResult:
    """登记保养：本班组管理员限定，跨班组拦截；同机同日重复保养只认第一回。"""
    try:
        record, entry = service.register_maintenance(payload.values, who)
    except EquipmentError as exc:
        raise _fail(exc) from exc
    return ActionResult(ok=True, message=f"机械「{record['机械编号']}」保养已登记，下次保养日重算为 {entry['下次保养日']}", entry=record)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload, who: dict[str, str] = identity) -> ActionResult:
    """对单台机械执行调度使用或申请报废；不满足保养口径的动作会被拦下并说明原因。

    保养登记是独立流水接口（POST /api/equipment/maintenance/register），
    因为它还要带保养日期、内容等字段，且口径是“只认第一回”。
    """
    action = str(payload.values.get("action") or "").strip()
    try:
        if action == "调度使用":
            entry, message = service.dispatch(entry_id, who)
        elif action == "申请报废":
            entry = service.scrap(entry_id, who)
            message = f"机械「{entry.get('机械编号')}」已报废，不再参与排班"
        else:
            return JSONResponse(
                status_code=400,
                content={"ok": False, "message": f"动作「{action}」不属于园林机械可执行范围（调度使用 / 申请报废）"},
            )
    except EquipmentError as exc:
        raise _fail(exc) from exc
    return ActionResult(ok=True, message=message, entry=entry)
