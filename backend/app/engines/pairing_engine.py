"""以 FBA 货件编号为核心的隔离配对、三维度校验与多套出纸编排引擎。"""

from __future__ import annotations

from app.models.schemas import (
    CarrierBoxMeta,
    FbaBoxMeta,
    PairingGroup,
    PairingPairItem,
    PairingRequest,
    PairingResponse,
    PrintQueueItem,
)


def _apply_manual_assignments(
    carriers: list[CarrierBoxMeta],
    assignments: dict[str, str],
) -> tuple[list[CarrierBoxMeta], list[CarrierBoxMeta]]:
    assigned: list[CarrierBoxMeta] = []
    unassigned: list[CarrierBoxMeta] = []
    for c in carriers:
        c_copy = c.model_copy(deep=True)
        key_page = f"{c_copy.file_id}:{c_copy.page_index}"
        manual_sid = assignments.get(key_page) or assignments.get(c_copy.file_id)
        if manual_sid:
            c_copy.assigned_shipment_id = manual_sid.strip().upper()
        if c_copy.effective_shipment_id:
            assigned.append(c_copy)
        else:
            unassigned.append(c_copy)
    return assigned, unassigned


def build_print_queue(
    group: PairingGroup,
    work_mode: str,
    order_mode: str,
) -> list[PrintQueueItem]:
    """根据作业模式与出纸顺序生成最终有序队列。"""
    queue: list[PrintQueueItem] = []
    seq = 1
    active_pairs = [p for p in group.pairs if p.selected and p.copies > 0]

    if work_mode == "fba_only":
        for p in active_pairs:
            if p.fba_box is None:
                continue
            for copy_no in range(1, p.copies + 1):
                queue.append(
                    PrintQueueItem(
                        seq=seq,
                        kind="fba",
                        shipment_id=group.shipment_id,
                        box_index=p.box_index,
                        copy_no=copy_no,
                        page_index=p.fba_box.page_index,
                        label=f"F{p.box_index}",
                        file_id=p.fba_box.file_id,
                    )
                )
                seq += 1
        return queue

    if work_mode == "carrier_only":
        for p in active_pairs:
            if p.carrier_box is None:
                continue
            for copy_no in range(1, p.copies + 1):
                queue.append(
                    PrintQueueItem(
                        seq=seq,
                        kind="carrier",
                        shipment_id=group.shipment_id,
                        box_index=p.box_index,
                        copy_no=copy_no,
                        page_index=p.carrier_box.page_index,
                        label=f"M{p.box_index}",
                        file_id=p.carrier_box.file_id,
                    )
                )
                seq += 1
        return queue

    # paired 成对模式
    valid_pairs = [p for p in active_pairs if p.fba_box is not None and p.carrier_box is not None]
    if order_mode == "interleave":
        for p in valid_pairs:
            assert p.fba_box and p.carrier_box
            for copy_no in range(1, p.copies + 1):
                queue.append(
                    PrintQueueItem(
                        seq=seq, kind="fba", shipment_id=group.shipment_id, box_index=p.box_index,
                        copy_no=copy_no, page_index=p.fba_box.page_index, label=f"F{p.box_index}", file_id=p.fba_box.file_id,
                    )
                )
                seq += 1
                queue.append(
                    PrintQueueItem(
                        seq=seq, kind="carrier", shipment_id=group.shipment_id, box_index=p.box_index,
                        copy_no=copy_no, page_index=p.carrier_box.page_index, label=f"M{p.box_index}", file_id=p.carrier_box.file_id,
                    )
                )
                seq += 1
    elif order_mode == "per_box_group":
        for p in valid_pairs:
            assert p.fba_box and p.carrier_box
            for copy_no in range(1, p.copies + 1):
                queue.append(
                    PrintQueueItem(
                        seq=seq, kind="fba", shipment_id=group.shipment_id, box_index=p.box_index,
                        copy_no=copy_no, page_index=p.fba_box.page_index, label=f"F{p.box_index}", file_id=p.fba_box.file_id,
                    )
                )
                seq += 1
            for copy_no in range(1, p.copies + 1):
                queue.append(
                    PrintQueueItem(
                        seq=seq, kind="carrier", shipment_id=group.shipment_id, box_index=p.box_index,
                        copy_no=copy_no, page_index=p.carrier_box.page_index, label=f"M{p.box_index}", file_id=p.carrier_box.file_id,
                    )
                )
                seq += 1
    else:  # split_all
        for p in valid_pairs:
            assert p.fba_box
            for copy_no in range(1, p.copies + 1):
                queue.append(
                    PrintQueueItem(
                        seq=seq, kind="fba", shipment_id=group.shipment_id, box_index=p.box_index,
                        copy_no=copy_no, page_index=p.fba_box.page_index, label=f"F{p.box_index}", file_id=p.fba_box.file_id,
                    )
                )
                seq += 1
        for p in valid_pairs:
            assert p.carrier_box
            for copy_no in range(1, p.copies + 1):
                queue.append(
                    PrintQueueItem(
                        seq=seq, kind="carrier", shipment_id=group.shipment_id, box_index=p.box_index,
                        copy_no=copy_no, page_index=p.carrier_box.page_index, label=f"M{p.box_index}", file_id=p.carrier_box.file_id,
                    )
                )
                seq += 1

    return queue


def pair_and_validate(req: PairingRequest) -> PairingResponse:
    """按 FBA 编号隔离多票文件、校验仓点/箱数/箱号并编排打印队列。"""
    assigned_carriers, unassigned_carriers = _apply_manual_assignments(
        req.carrier_boxes, req.manual_assignments
    )

    fba_by_sid: dict[str, list[FbaBoxMeta]] = {}
    for b in req.fba_boxes:
        sid = (b.shipment_id or "UNKNOWN_FBA").upper()
        fba_by_sid.setdefault(sid, []).append(b)

    car_by_sid: dict[str, list[CarrierBoxMeta]] = {}
    for c in assigned_carriers:
        sid = (c.effective_shipment_id or "").upper()
        if sid:
            car_by_sid.setdefault(sid, []).append(c)

    all_sids = sorted(set(fba_by_sid.keys()) | set(car_by_sid.keys()))
    groups: list[PairingGroup] = []

    for sid in all_sids:
        f_list = sorted(fba_by_sid.get(sid, []), key=lambda x: x.box_index)
        c_list = sorted(car_by_sid.get(sid, []), key=lambda x: x.box_index)
        f_map = {item.box_index: item for item in f_list}
        c_map = {item.box_index: item for item in c_list}
        box_indices = sorted(set(f_map.keys()) | set(c_map.keys()))

        pairs: list[PairingPairItem] = []
        for idx in box_indices:
            sel_key = f"{sid}:{idx}"
            copies = req.box_copies.get(sel_key, req.default_copies)
            selected = req.selected_keys.get(sel_key, True)
            pairs.append(
                PairingPairItem(
                    box_index=idx,
                    fba_box=f_map.get(idx),
                    carrier_box=c_map.get(idx),
                    selected=selected,
                    copies=max(1, int(copies)),
                )
            )

        f_wh = next((x.warehouse_code for x in f_list if x.warehouse_code), None)
        c_wh = next((x.warehouse_code for x in c_list if x.warehouse_code), None)
        issues: list[str] = []

        if not f_list and c_list:
            status = "missing_fba"
            issues.append(f"货件 {sid} 缺少亚马逊外箱标 PDF")
        elif f_list and not c_list:
            status = "missing_carrier"
            issues.append(f"货件 {sid} 尚缺同号货代箱唛 PDF")
        else:
            if f_wh and c_wh and f_wh != c_wh:
                issues.append(f"仓点冲突：外箱标为 {f_wh}，货代箱唛为 {c_wh}")
            if len(f_list) != len(c_list) or set(f_map.keys()) != set(c_map.keys()):
                issues.append(
                    f"箱数/箱号不一致：外箱标 {sorted(f_map.keys())}，货代箱唛 {sorted(c_map.keys())}"
                )
            # 校验是否完整覆盖 1..N
            expected_n = max(
                [x.total_boxes for x in f_list] + [x.total_boxes for x in c_list] + [len(box_indices)]
            )
            if set(f_map.keys()) != set(range(1, expected_n + 1)) or set(c_map.keys()) != set(range(1, expected_n + 1)):
                if f"箱数/箱号不一致" not in " ".join(issues):
                    issues.append(f"箱号序列未完整覆盖 1..{expected_n}")
            status = "mismatch_detail" if issues else "matched"

        groups.append(
            PairingGroup(
                shipment_id=sid,
                warehouse_code=f_wh or c_wh,
                status=status,
                issues=issues,
                pairs=pairs,
            )
        )

    if not groups:
        return PairingResponse(
            groups=[],
            unassigned_carriers=unassigned_carriers,
            active_shipment_id=None,
            can_print=False,
            issues=["尚未导入任何可配对文件"],
            queue=[],
            total_sheets=0,
        )

    # 优先选取请求指定的活动货件分组，未传入或未命中时再回退首个 matched 分组或 groups[0]
    req_sid = (req.active_shipment_id or "").strip().upper()
    active = next((g for g in groups if req_sid and g.shipment_id == req_sid), None)
    if active is None:
        active = next((g for g in groups if g.status == "matched"), groups[0])
    can_print = False
    active_issues = list(active.issues)

    if req.work_mode == "fba_only":
        can_print = any(p.fba_box is not None and p.selected for p in active.pairs)
        active_issues = [] if can_print else [f"货件 {active.shipment_id} 无可打印的外箱标"]
    elif req.work_mode == "carrier_only":
        can_print = any(p.carrier_box is not None and p.selected for p in active.pairs)
        active_issues = [] if can_print else [f"货件 {active.shipment_id} 无可打印的货代箱唛"]
    else:
        if active.status == "matched":
            can_print = True
        elif active.status == "mismatch_detail" and req.force_unlocked:
            can_print = True

    queue = build_print_queue(active, req.work_mode, req.order_mode) if can_print else []
    if can_print and not queue:
        can_print = False
        active_issues.append("当前队列中没有已勾选的标签")

    return PairingResponse(
        groups=groups,
        unassigned_carriers=unassigned_carriers,
        active_shipment_id=active.shipment_id,
        can_print=can_print,
        issues=active_issues,
        queue=queue,
        total_sheets=len(queue),
    )
