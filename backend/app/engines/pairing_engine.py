"""以 FBA 货件编号隔离或跨仓按 SKU 归集的防错校验与出纸队列编排引擎。"""

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

MIXED_SKU_KEY = "__MIXED_SKU__"
UNRECOGNIZED_SKU_KEY = "__UNRECOGNIZED_SKU__"


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


def _resolve_sku_bucket(fba_box: FbaBoxMeta | None) -> tuple[str, str]:
    """返回 (sku_key, display_label)。"""
    if fba_box is None:
        return UNRECOGNIZED_SKU_KEY, "未识别 SKU"
    if fba_box.is_mixed_sku:
        return MIXED_SKU_KEY, "混装箱 (Mixed SKU)"
    raw = (fba_box.sku_text or "").strip()
    if raw:
        return raw.upper(), raw
    return UNRECOGNIZED_SKU_KEY, "未识别 SKU"


def _make_label_item(
    *,
    kind: str,
    pair: PairingPairItem,
    fallback_sid: str,
    fallback_wh: str,
    copy_no: int,
    annotate_wh: bool,
) -> PrintQueueItem:
    box_meta = pair.fba_box if kind == "fba" else pair.carrier_box
    assert box_meta is not None
    wh = (pair.warehouse_code or fallback_wh or "").strip()
    sid = (pair.shipment_id or fallback_sid or "").strip()
    sku = (pair.sku_text or "").strip()
    prefix = "F" if kind == "fba" else "M"
    label = f"{prefix}{pair.box_index}·{wh}" if (annotate_wh and wh) else f"{prefix}{pair.box_index}"
    return PrintQueueItem(
        seq=0,
        kind="fba" if kind == "fba" else "carrier",
        shipment_id=sid,
        box_index=pair.box_index,
        copy_no=copy_no,
        page_index=box_meta.page_index,
        label=label,
        file_id=box_meta.file_id,
        warehouse_code=wh,
        sku_text=sku,
        source_file_name=box_meta.file_name,
        source_page_no=box_meta.page_index + 1,
    )


def _inject_separators(raw_items: list[PrintQueueItem], group: PairingGroup) -> list[PrintQueueItem]:
    """按 (kind段/仓库/货件) 变化点插入高对比分隔提示页并连续重排 seq。"""
    if not raw_items:
        return []
    out: list[PrintQueueItem] = []
    last_ctx: tuple[str, str, str] | None = None
    for item in raw_items:
        ctx = (item.warehouse_code or "-", item.shipment_id or "-", item.sku_text or group.display_label or "-")
        if ctx != last_ctx:
            wh_disp = item.warehouse_code or "未知仓点"
            sku_disp = item.sku_text or group.display_label or "-"
            out.append(
                PrintQueueItem(
                    seq=0,
                    kind=item.kind,
                    shipment_id=item.shipment_id,
                    box_index=item.box_index,
                    copy_no=0,
                    page_index=-1,
                    label=f"分隔·{wh_disp}",
                    file_id="",
                    warehouse_code=item.warehouse_code,
                    sku_text=item.sku_text,
                    source_file_name="",
                    source_page_no=0,
                    is_separator=True,
                    separator_title=f"仓库切换 · {wh_disp}",
                    separator_detail=f"SKU: {sku_disp} | 货件: {item.shipment_id}",
                )
            )
            last_ctx = ctx
        out.append(item)
    return out


def build_print_queue(
    group: PairingGroup,
    work_mode: str,
    order_mode: str,
    insert_separator_pages: bool = False,
) -> list[PrintQueueItem]:
    """根据作业模式、独立张数配比（如 FBA 2 + 箱唛 1）与出纸顺序生成最终有序队列。"""
    raw_items: list[PrintQueueItem] = []
    active_pairs = [p for p in group.pairs if p.selected and (p.fba_copies > 0 or p.carrier_copies > 0)]
    annotate_wh = group.group_kind == "sku" and len(group.warehouses) > 1
    fallback_sid = group.shipment_id
    fallback_wh = group.warehouses[0] if len(group.warehouses) == 1 else (group.warehouse_code or "")

    if work_mode == "fba_only":
        for p in active_pairs:
            if p.fba_box is None or p.fba_copies <= 0:
                continue
            for copy_no in range(1, p.fba_copies + 1):
                raw_items.append(
                    _make_label_item(
                        kind="fba", pair=p, fallback_sid=fallback_sid, fallback_wh=fallback_wh,
                        copy_no=copy_no, annotate_wh=annotate_wh,
                    )
                )
    elif work_mode == "carrier_only":
        for p in active_pairs:
            if p.carrier_box is None or p.carrier_copies <= 0:
                continue
            for copy_no in range(1, p.carrier_copies + 1):
                raw_items.append(
                    _make_label_item(
                        kind="carrier", pair=p, fallback_sid=fallback_sid, fallback_wh=fallback_wh,
                        copy_no=copy_no, annotate_wh=annotate_wh,
                    )
                )
    else:
        valid_pairs = [p for p in active_pairs if p.fba_box is not None and p.carrier_box is not None]
        if order_mode == "interleave":
            for p in valid_pairs:
                for round_no in range(1, max(p.fba_copies, p.carrier_copies) + 1):
                    if round_no <= p.fba_copies:
                        raw_items.append(
                            _make_label_item(
                                kind="fba", pair=p, fallback_sid=fallback_sid, fallback_wh=fallback_wh,
                                copy_no=round_no, annotate_wh=annotate_wh,
                            )
                        )
                    if round_no <= p.carrier_copies:
                        raw_items.append(
                            _make_label_item(
                                kind="carrier", pair=p, fallback_sid=fallback_sid, fallback_wh=fallback_wh,
                                copy_no=round_no, annotate_wh=annotate_wh,
                            )
                        )
        elif order_mode == "per_box_group":
            for p in valid_pairs:
                for copy_no in range(1, p.fba_copies + 1):
                    raw_items.append(
                        _make_label_item(
                            kind="fba", pair=p, fallback_sid=fallback_sid, fallback_wh=fallback_wh,
                            copy_no=copy_no, annotate_wh=annotate_wh,
                        )
                    )
                for copy_no in range(1, p.carrier_copies + 1):
                    raw_items.append(
                        _make_label_item(
                            kind="carrier", pair=p, fallback_sid=fallback_sid, fallback_wh=fallback_wh,
                            copy_no=copy_no, annotate_wh=annotate_wh,
                        )
                    )
        else:  # split_all
            for p in valid_pairs:
                for copy_no in range(1, p.fba_copies + 1):
                    raw_items.append(
                        _make_label_item(
                            kind="fba", pair=p, fallback_sid=fallback_sid, fallback_wh=fallback_wh,
                            copy_no=copy_no, annotate_wh=annotate_wh,
                        )
                    )
            for p in valid_pairs:
                for copy_no in range(1, p.carrier_copies + 1):
                    raw_items.append(
                        _make_label_item(
                            kind="carrier", pair=p, fallback_sid=fallback_sid, fallback_wh=fallback_wh,
                            copy_no=copy_no, annotate_wh=annotate_wh,
                        )
                    )

    final_items = _inject_separators(raw_items, group) if insert_separator_pages else raw_items
    for seq_idx, item in enumerate(final_items, 1):
        item.seq = seq_idx
    return final_items


def _build_shipment_groups(
    req: PairingRequest,
    assigned_carriers: list[CarrierBoxMeta],
) -> list[PairingGroup]:
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

    eff_default_fba = req.default_fba_copies if req.default_fba_copies is not None else req.default_copies
    eff_default_car = req.default_carrier_copies if req.default_carrier_copies is not None else req.default_copies

    for sid in all_sids:
        f_list = sorted(fba_by_sid.get(sid, []), key=lambda x: x.box_index)
        c_list = sorted(car_by_sid.get(sid, []), key=lambda x: x.box_index)
        f_map = {item.box_index: item for item in f_list}
        c_map = {item.box_index: item for item in c_list}
        box_indices = sorted(set(f_map.keys()) | set(c_map.keys()))

        f_wh = next((x.warehouse_code for x in f_list if x.warehouse_code), None)
        c_wh = next((x.warehouse_code for x in c_list if x.warehouse_code), None)
        group_wh = f_wh or c_wh

        pairs: list[PairingPairItem] = []
        for idx in box_indices:
            sel_key = f"{sid}:{idx}"
            fallback_box = req.box_copies.get(sel_key)
            raw_fba = req.box_fba_copies.get(sel_key, fallback_box if fallback_box is not None else eff_default_fba)
            raw_car = req.box_carrier_copies.get(sel_key, fallback_box if fallback_box is not None else eff_default_car)
            fba_copies = max(0, min(20, int(raw_fba)))
            car_copies = max(0, min(20, int(raw_car)))
            selected = req.selected_keys.get(sel_key, True)
            f_box = f_map.get(idx)
            c_box = c_map.get(idx)
            pair_wh = (f_box.warehouse_code if f_box else None) or (c_box.warehouse_code if c_box else None) or group_wh
            _, sku_disp = _resolve_sku_bucket(f_box)
            pair_sku = (
                "混装箱 (Mixed SKU)"
                if (f_box and f_box.is_mixed_sku)
                else ((f_box.sku_text or "").strip() or None if f_box else None)
            )
            if sku_disp == "未识别 SKU":
                pair_sku = None
            pairs.append(
                PairingPairItem(
                    box_index=idx,
                    shipment_id=sid,
                    warehouse_code=pair_wh,
                    sku_text=pair_sku,
                    pair_key=sel_key,
                    fba_box=f_box,
                    carrier_box=c_box,
                    selected=selected,
                    copies=max(fba_copies, car_copies),
                    fba_copies=fba_copies,
                    carrier_copies=car_copies,
                )
            )

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
            expected_n = max(
                [x.total_boxes for x in f_list] + [x.total_boxes for x in c_list] + [len(box_indices)]
            )
            if set(f_map.keys()) != set(range(1, expected_n + 1)) or set(c_map.keys()) != set(range(1, expected_n + 1)):
                if "箱数/箱号不一致" not in " ".join(issues):
                    issues.append(f"箱号序列未完整覆盖 1..{expected_n}")
            status = "mismatch_detail" if issues else "matched"

        groups.append(
            PairingGroup(
                shipment_id=sid,
                warehouse_code=group_wh,
                group_kind="shipment",
                display_label=sid,
                warehouses=[group_wh] if group_wh else [],
                shipment_ids=[sid],
                status=status,
                issues=issues,
                pairs=pairs,
            )
        )

    return groups


def _aggregate_sku_groups(shipment_groups: list[PairingGroup]) -> tuple[list[PairingGroup], list[dict[str, object]]]:
    """按 SKU 跨仓库/跨货件归集箱标，并在各组内按仓库稳定排序。"""
    buckets: dict[str, dict[str, object]] = {}

    for sg in shipment_groups:
        for pair in sg.pairs:
            sku_key, display_label = _resolve_sku_bucket(pair.fba_box)
            entry = buckets.setdefault(
                sku_key,
                {
                    "display_label": display_label,
                    "pairs": [],
                    "shipments": set(),
                    "warehouses": set(),
                    "issues": [],
                    "statuses": set(),
                },
            )
            entry["pairs"].append(pair)  # type: ignore[union-attr]
            entry["shipments"].add(sg.shipment_id)  # type: ignore[union-attr]
            if pair.warehouse_code:
                entry["warehouses"].add(pair.warehouse_code)  # type: ignore[union-attr]
            entry["statuses"].add(sg.status)  # type: ignore[union-attr]
            for iss in sg.issues:
                if iss not in entry["issues"]:  # type: ignore[operator]
                    entry["issues"].append(iss)  # type: ignore[union-attr]

    def _sort_bucket_key(item: tuple[str, dict[str, object]]) -> tuple[int, str]:
        k = item[0]
        if k == MIXED_SKU_KEY:
            return (1, k)
        if k == UNRECOGNIZED_SKU_KEY:
            return (2, k)
        return (0, k)

    sku_groups: list[PairingGroup] = []
    sku_summary: list[dict[str, object]] = []

    for sku_key, entry in sorted(buckets.items(), key=_sort_bucket_key):
        raw_pairs: list[PairingPairItem] = entry["pairs"]  # type: ignore[assignment]
        sorted_pairs = sorted(
            raw_pairs,
            key=lambda p: ((p.warehouse_code or "ZZZ"), p.shipment_id, p.box_index),
        )
        warehouses = sorted(entry["warehouses"])  # type: ignore[arg-type]
        shipments = sorted(entry["shipments"])  # type: ignore[arg-type]
        issues: list[str] = list(entry["issues"])  # type: ignore[arg-type]
        statuses: set[str] = entry["statuses"]  # type: ignore[assignment]

        if statuses == {"matched"}:
            status = "matched"
        elif statuses == {"missing_carrier"}:
            status = "missing_carrier"
        elif statuses == {"missing_fba"}:
            status = "missing_fba"
        else:
            status = "mismatch_detail"

        if sku_key == MIXED_SKU_KEY:
            issues = ["混装箱含多个 SKU，请逐箱核对后再贴标", *issues]

        display_label = str(entry["display_label"])
        sku_groups.append(
            PairingGroup(
                shipment_id=sku_key,
                warehouse_code=" / ".join(warehouses) if warehouses else None,
                group_kind="sku",
                display_label=display_label,
                warehouses=warehouses,
                shipment_ids=shipments,
                status=status,
                issues=issues,
                pairs=sorted_pairs,
            )
        )
        sku_summary.append(
            {
                "sku_key": sku_key,
                "display_label": display_label,
                "box_count": len(sorted_pairs),
                "warehouses": warehouses,
                "shipment_ids": shipments,
                "is_mixed": sku_key == MIXED_SKU_KEY,
                "is_unrecognized": sku_key == UNRECOGNIZED_SKU_KEY,
            }
        )

    return sku_groups, sku_summary


def _evaluate_group_printable(
    active: PairingGroup,
    work_mode: str,
    force_unlocked: bool,
) -> tuple[bool, list[str]]:
    can_print = False
    active_issues = list(active.issues)

    if work_mode == "fba_only":
        can_print = any(p.fba_box is not None and p.selected for p in active.pairs)
        active_issues = [] if can_print else [f"分组 {active.display_label or active.shipment_id} 无可打印的外箱标"]
    elif work_mode == "carrier_only":
        can_print = any(p.carrier_box is not None and p.selected for p in active.pairs)
        active_issues = [] if can_print else [f"分组 {active.display_label or active.shipment_id} 无可打印的货代箱唛"]
    else:
        if active.status == "matched":
            can_print = True
        elif active.status == "mismatch_detail":
            if active.group_kind == "sku" and all(p.fba_box and p.carrier_box for p in active.pairs):
                # 混装箱仅提示核对，若已全配齐且所属货件无阻塞错误仍放行，若有错配则受 force_unlocked 控制
                has_real_conflict = any(
                    not iss.startswith("混装箱含多个 SKU") for iss in active.issues
                )
                can_print = (not has_real_conflict) or force_unlocked
            elif force_unlocked:
                can_print = True

    return can_print, active_issues


def pair_and_validate(req: PairingRequest) -> PairingResponse:
    """按 FBA 编号隔离或跨仓按 SKU 归集校验，并编排有序打印队列。"""
    assigned_carriers, unassigned_carriers = _apply_manual_assignments(
        req.carrier_boxes, req.manual_assignments
    )
    shipment_groups = _build_shipment_groups(req, assigned_carriers)

    if not shipment_groups:
        return PairingResponse(
            groups=[],
            unassigned_carriers=unassigned_carriers,
            active_shipment_id=None,
            group_by=req.group_by,
            sku_summary=[],
            can_print=False,
            issues=["尚未导入任何可配对文件"],
            queue=[],
            total_sheets=0,
        )

    sku_groups, sku_summary = _aggregate_sku_groups(shipment_groups)
    target_groups = sku_groups if req.group_by == "sku" else shipment_groups

    req_sid = (req.active_shipment_id or "").strip().upper()
    active = next((g for g in target_groups if req_sid and g.shipment_id.upper() == req_sid), None)
    if active is None:
        active = next((g for g in target_groups if g.status == "matched"), target_groups[0])

    can_print, active_issues = _evaluate_group_printable(active, req.work_mode, req.force_unlocked)
    queue = (
        build_print_queue(
            active,
            req.work_mode,
            req.order_mode,
            insert_separator_pages=req.insert_separator_pages,
        )
        if can_print
        else []
    )
    if can_print and not queue:
        can_print = False
        active_issues.append("当前队列中没有已勾选的标签")

    return PairingResponse(
        groups=target_groups,
        unassigned_carriers=unassigned_carriers,
        active_shipment_id=active.shipment_id,
        group_by=req.group_by,
        sku_summary=sku_summary,
        can_print=can_print,
        issues=active_issues,
        queue=queue,
        total_sheets=len(queue),
    )
