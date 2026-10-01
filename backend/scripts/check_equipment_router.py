"""路由层自检：不依赖 fastapi，直接模拟路由函数的入参与头部，验证接口编排。

fastapi 在这里只负责参数注入与序列化，真正的口径都在 service 里，
所以用等价方式调用路由函数即可覆盖：头部身份、错误状态码、返回结构。
"""
from __future__ import annotations

from datetime import date

from fastapi import HTTPException  # type: ignore  # 若环境无 fastapi 则跳过本脚本

from app.routers import equipment as router
from app.services.equipment import service

ADMIN_A = {"name": "一班管理员", "team": "一班", "role": "管理员"}
ADMIN_B = {"name": "二班管理员", "team": "二班", "role": "管理员"}
OP_A = {"name": "一班小王", "team": "一班", "role": "操作人员"}


def expect_http(status: int, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except HTTPException as exc:
        assert exc.status_code == status, f"期望 {status}，实际 {exc.status_code}：{exc.detail}"
        return exc.detail
    raise AssertionError(f"{fn} 应抛出 HTTP {status}")


def main() -> None:
    # 列表与看板
    page = router.list_entries(page=1, size=20)
    assert page.total == 6 and len(page.items) == 6
    board = router.dispatch_board()
    assert board["summary"]["参与排班"] == 5
    assert board["summary"]["禁止调度"] >= 2  # 临近 + 超期
    assert board["summary"]["已报废剔除"] == 1
    assert board["items"][0]["可调度"] is False, "禁排机械须置顶"

    # 台账与看板保养日一致
    ledger = {item["机械编号"]: item["下次保养日"] for item in page.items}
    for item in board["items"]:
        assert ledger[item["机械编号"]] == item["下次保养日"]

    # 非管理员登记保养 → 403
    detail = expect_http(
        403,
        router.register_maintenance,
        type("P", (), {"values": {"机械编号": "EQUI-0001", "保养日期": date.today().isoformat()}})(),
        OP_A,
    )
    assert "管理员" in detail

    # 跨班组登记 → 403
    detail = expect_http(
        403,
        router.register_maintenance,
        type("P", (), {"values": {"机械编号": "EQUI-0003", "保养日期": date.today().isoformat()}})(),
        ADMIN_A,
    )
    assert "跨班组" in detail

    # 本班组管理员登记成功，且下次保养日重算
    payload = type("P", (), {"values": {"机械编号": "EQUI-0003", "保养日期": date.today().isoformat(), "保养内容": "全面检修"}})()
    result = router.register_maintenance(payload, ADMIN_B)
    assert result.ok and str(result.entry["保养日期"]) == date.today().isoformat()
    saw = service.get_entry(3)
    assert saw["保养口径"] == "保养正常" and saw["可调度"] is True

    # 同机同日再来一次 → 400 只认第一回
    detail = expect_http(400, router.register_maintenance, payload, ADMIN_B)
    assert "只认第一回" in detail

    # 超期时调度会被 400 拦下（这里对 EQUI-0002 临近保养验证）
    detail = expect_http(400, router.run_action, 2, type("P", (), {"values": {"action": "调度使用"}})(), ADMIN_A)
    assert "禁止调度" in detail

    # 报废动作跨班组 → 403
    expect_http(403, router.run_action, 1, type("P", (), {"values": {"action": "申请报废"}})(), ADMIN_B)
    # 非管理员调阈值 → 403
    expect_http(
        403,
        router.update_type,
        "油锯",
        type("P", (), {"values": {"保养周期天数": 30}})(),
        OP_A,
    )

    # 阈值调整 → 全量重算
    res = router.update_type("油锯", type("P", (), {"values": {"保养周期天数": 90, "年限上限年数": 10}})(), ADMIN_A)
    assert res.ok and "重算 6 台" in res.message
    assert service.get_entry(3)["保养周期天数"] == 90

    # 新增类型阈值 + 用该类型登记机械
    new_type = type("P", (), {"values": {"机械类型": "粉碎机", "保养周期天数": 40, "年限上限年数": 7, "提醒提前天数": 5}})()
    assert router.create_type(new_type, ADMIN_A).ok
    expect_http(403, router.create_type, new_type, OP_A)
    new_eq = type(
        "P",
        (),
        {"values": {"机械编号": "EQUI-0009", "机械名称": "树枝粉碎机", "机械类型": "粉碎机",
                    "规格型号": "WC-80", "购置日期": date.today().isoformat(),
                    "所属班组": "一班", "操作人员": "测试"}},
    )()
    assert router.create_entry(new_eq, ADMIN_A).ok
    # 缺字段
    bad = expect_http(
        400,
        router.create_entry,
        type("P", (), {"values": {"机械编号": "X"}})(),
        ADMIN_A,
    )
    assert "缺少必填字段" in bad

    # 保养记录列表包含“只认第一回”的去重信息（脏记录仍留痕，但 latest 不取它）
    records = router.list_maintenance(keyword="EQUI-0004")["items"]
    assert len([r for r in records if r["保养日期"] == records[0]["保养日期"]]) >= 1

    # 导出与台账同口径
    export = router.export_entries()
    assert export["total"] == 7
    print("equipment router OK")


if __name__ == "__main__":
    main()
