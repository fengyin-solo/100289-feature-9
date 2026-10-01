"""园林机械保养口径的自检脚本：python -m scripts.check_equipment

不依赖测试框架，直接断言九条业务规则，任一不成立就非零退出。
"""
from __future__ import annotations

from datetime import date, timedelta

from app.seed import SEED_ROWS
from app.services.equipment import (
    ROLE_ADMIN,
    STATUS_SCRAPPED,
    EquipmentError,
    EquipmentService,
)
from app.store import Store

ADMIN_A = {"name": "一班管理员", "team": "一班", "role": ROLE_ADMIN}
ADMIN_B = {"name": "二班管理员", "team": "二班", "role": ROLE_ADMIN}
OP_A = {"name": "一班小王", "team": "一班", "role": "操作人员"}


def fresh_service() -> EquipmentService:
    store = Store()
    return EquipmentService(store)


def main() -> None:
    svc = fresh_service()

    # 1. 下次保养日 = 上次保养 + 类型周期；从未保养的从购置日期起算。
    mower = next(r for r in svc.store.rows("equipment") if r["机械编号"] == "EQUI-0001")
    view = svc.decorate(mower)
    expect_next = (date.today() - timedelta(days=10) + timedelta(days=30)).isoformat()
    assert view["下次保养日"] == expect_next, f"割草机下次保养日应为 {expect_next}，实际 {view['下次保养日']}"
    assert view["可调度"] is True and view["保养口径"] == "保养正常"

    driller = next(r for r in svc.store.rows("equipment") if r["机械编号"] == "EQUI-0006")
    driller_view = svc.decorate(driller)
    assert driller_view["上次保养"] == "—", "从未保养的机械上次保养应显示 —"
    expect_drill_next = (date.today() - timedelta(days=5) + timedelta(days=45)).isoformat()
    assert driller_view["下次保养日"] == expect_drill_next, "从未保养时应以购置日期起算下次保养日"

    # 2. 不足 5 天禁排并说明缘由。
    hedge = next(r for r in svc.store.rows("equipment") if r["机械编号"] == "EQUI-0002")
    hedge_view = svc.decorate(hedge)
    assert hedge_view["可调度"] is False and hedge_view["保养口径"] == "临近保养"
    assert "不足 5 天" in hedge_view["调度说明"], hedge_view["调度说明"]

    # 3. 已超期禁排。
    saw = next(r for r in svc.store.rows("equipment") if r["机械编号"] == "EQUI-0003")
    saw_view = svc.decorate(saw)
    assert saw_view["可调度"] is False and saw_view["保养口径"] == "已超期"
    assert "已超期" in saw_view["调度说明"]
    try:
        svc.dispatch(int(saw["id"]), ADMIN_A)
    except EquipmentError as exc:
        assert "禁止调度" in exc.message
    else:
        raise AssertionError("超期机械不应允许调度")

    # 4. 超龄另作提示，但不拦调度。
    brush = next(r for r in svc.store.rows("equipment") if r["机械编号"] == "EQUI-0004")
    brush_view = svc.decorate(brush)
    assert brush_view["超龄"] is True and "上限 6 年" in brush_view["超龄提示"]
    assert brush_view["可调度"] is True, "超龄只提示，不应拦截调度"
    _, note = svc.dispatch(int(brush["id"]), ADMIN_B)
    assert "超龄" in note

    # 5. 已报废不参与排班；保养中的也不能调度。
    board = svc.dispatch_board()
    assert all(item["status"] != STATUS_SCRAPPED for item in board["items"]), "看板不应出现已报废机械"
    assert board["summary"]["已报废剔除"] == 1
    assert board["summary"]["参与排班"] == 5
    # 临近(EQUI-0002) + 超期(EQUI-0003) + 保养中(EQUI-0006) = 3 台禁排
    assert board["summary"]["禁止调度"] == 3, board["summary"]
    scrapped = next(r for r in svc.store.rows("equipment") if r["机械编号"] == "EQUI-0005")
    assert svc.decorate(scrapped)["可调度"] is False
    in_maintenance = next(r for r in svc.store.rows("equipment") if r["机械编号"] == "EQUI-0006")
    assert svc.decorate(in_maintenance)["可调度"] is False
    assert "正在保养" in svc.decorate(in_maintenance)["调度说明"]

    # 6. 阈值按类型区分；调整后重算已有记录。
    svc.update_rule("绿篱机", {"保养周期天数": 60}, ADMIN_A)
    hedge_view2 = svc.decorate(hedge)
    expect_changed = (date.today() - timedelta(days=23) + timedelta(days=60)).isoformat()
    assert hedge_view2["下次保养日"] == expect_changed, "阈值调整后应重算已有机械的下次保养日"
    assert hedge_view2["可调度"] is True, "周期放宽到 60 天后原临近保养的机械应恢复可调度"

    # 7. 非管理员、跨班组改保养记录都被拦下。
    try:
        svc.register_maintenance({"机械编号": "EQUI-0001", "保养日期": date.today().isoformat()}, OP_A)
    except EquipmentError as exc:
        assert exc.status_code == 403 and "管理员" in exc.message
    else:
        raise AssertionError("非管理员不应能登记保养")
    try:
        svc.register_maintenance({"机械编号": "EQUI-0001", "保养日期": date.today().isoformat()}, ADMIN_B)
    except EquipmentError as exc:
        assert exc.status_code == 403 and "跨班组" in exc.message
    else:
        raise AssertionError("跨班组管理员不应能改他班机械的保养记录")

    # 8. 同机同日重复保养只认第一回：重复登记被拒，已有的重复脏数据不影响口径。
    today = date.today().isoformat()
    svc.register_maintenance({"机械编号": "EQUI-0001", "保养日期": today, "保养内容": "首保"}, ADMIN_A)
    try:
        svc.register_maintenance({"机械编号": "EQUI-0001", "保养日期": today, "保养内容": "再保一次"}, ADMIN_A)
    except EquipmentError as exc:
        assert "只认第一回" in exc.message
    else:
        raise AssertionError("同机同日重复保养必须被拦下")
    latest = svc._latest_maintenance("EQUI-0001")
    assert latest is not None and latest["保养内容"] == "首保"
    # 种子里 EQUI-0004 同天两条，只认 id 最小的一条。
    latest4 = svc._latest_maintenance("EQUI-0004")
    assert latest4["id"] == 4 and latest4["保养内容"] == "更换打草绳、空滤清理"

    # 9. 看板与台账口径一致：同一台机械两边的下次保养日必须相同。
    board = svc.dispatch_board()
    ledger = {row["机械编号"]: row["下次保养日"] for row in svc.list_entries(size=100)[0]}
    board_map = {row["机械编号"]: row["下次保养日"] for row in board["items"]}
    for code, day in board_map.items():
        assert ledger[code] == day, f"{code} 看板保养日 {day} 与台账 {ledger[code]} 不一致"

    # 附：调度看板禁排排序 —— 临近/超期的排前面。
    blocked_flags = [not item["可调度"] for item in svc.dispatch_board()["items"]]
    assert blocked_flags == sorted(blocked_flags, reverse=True), "禁排机械应排在看板最前"

    # 附：种子与配置表数量自洽。
    assert len(SEED_ROWS["equipment_type_rule"]) == 5
    print("equipment rules OK")


if __name__ == "__main__":
    main()
