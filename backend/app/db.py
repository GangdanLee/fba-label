"""SQLite 数据库初始化与参数化 CRUD 仓储。"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from app.config import get_db_path
from app.models.schemas import (
    CalibrationProfile,
    CanvasElement,
    CarrierRule,
    PrintBatchCreate,
    PrintBatchRecord,
    SkuTemplate,
    SkuTemplateUpsert,
)


def _utc_now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


@contextmanager
def get_conn(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    path = db_path or get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path | None = None) -> None:
    """初始化表结构与默认硬件校准/状态记录（严禁预置任何真实业务样本）。"""
    with get_conn(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS skus (
                id TEXT PRIMARY KEY,
                sku TEXT NOT NULL UNIQUE,
                fnsku TEXT NOT NULL,
                title_raw TEXT NOT NULL DEFAULT '',
                title_clean TEXT NOT NULL DEFAULT '',
                width_mm REAL NOT NULL DEFAULT 50.0,
                height_mm REAL NOT NULL DEFAULT 30.0,
                layout_type TEXT NOT NULL DEFAULT 'double',
                canvas_elements_json TEXT NOT NULL DEFAULT '[]',
                default_qty INTEGER NOT NULL DEFAULT 60,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS calibration_profiles (
                spec_key TEXT PRIMARY KEY,
                label_width_mm REAL NOT NULL,
                label_height_mm REAL NOT NULL,
                cols INTEGER NOT NULL DEFAULT 1,
                col_gap_mm REAL NOT NULL DEFAULT 0.0,
                row_gap_mm REAL NOT NULL DEFAULT 2.0,
                safe_width_mm REAL NOT NULL DEFAULT 98.0,
                safe_height_mm REAL NOT NULL DEFAULT 98.0,
                offset_x_mm REAL NOT NULL DEFAULT 0.0,
                offset_y_mm REAL NOT NULL DEFAULT 0.0,
                darkness INTEGER NOT NULL DEFAULT 8,
                print_speed INTEGER NOT NULL DEFAULT 4,
                preferred_channel TEXT NOT NULL DEFAULT 'tspl_raw',
                printer_name TEXT NOT NULL DEFAULT '',
                protocol TEXT NOT NULL DEFAULT 'tspl',
                dpi INTEGER NOT NULL DEFAULT 203,
                connection_type TEXT NOT NULL DEFAULT 'os_queue',
                network_host TEXT NOT NULL DEFAULT '',
                network_port INTEGER NOT NULL DEFAULT 9100
            );

            CREATE TABLE IF NOT EXISTS app_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS print_batches (
                id TEXT PRIMARY KEY,
                batch_type TEXT NOT NULL,
                shipment_id TEXT NOT NULL,
                warehouse_code TEXT NOT NULL DEFAULT '-',
                spec_key TEXT NOT NULL,
                total_units_or_boxes INTEGER NOT NULL,
                copies_per_box INTEGER NOT NULL DEFAULT 1,
                order_mode TEXT NOT NULL DEFAULT 'interleave',
                channel TEXT NOT NULL DEFAULT 'tspl_raw',
                summary TEXT NOT NULL,
                source_files_json TEXT NOT NULL DEFAULT '[]',
                overlay_elements_json TEXT NOT NULL DEFAULT '[]',
                snapshot_dir TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS carrier_rules (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                shipment_regex TEXT NOT NULL,
                warehouse_regex TEXT NOT NULL,
                ctn_regex TEXT NOT NULL,
                default_rotate INTEGER NOT NULL DEFAULT 0,
                enabled INTEGER NOT NULL DEFAULT 1
            );
            """
        )

        # 老版本数据库平滑幂等升级（补齐 v0.2.0 新增的多协议/DPI/网口字段）
        existing_cols = {str(r["name"]) for r in conn.execute("PRAGMA table_info(calibration_profiles)").fetchall()}
        migrations = [
            ("protocol", "TEXT NOT NULL DEFAULT 'tspl'"),
            ("dpi", "INTEGER NOT NULL DEFAULT 203"),
            ("connection_type", "TEXT NOT NULL DEFAULT 'os_queue'"),
            ("network_host", "TEXT NOT NULL DEFAULT ''"),
            ("network_port", "INTEGER NOT NULL DEFAULT 9100"),
        ]
        for col_name, col_def in migrations:
            if col_name not in existing_cols:
                conn.execute(f"ALTER TABLE calibration_profiles ADD COLUMN {col_name} {col_def}")

        # 注入默认纸卷规格校准档案
        default_profiles = [
            ("100x100_single", 100.0, 100.0, 1, 0.0, 2.0, 98.0, 98.0, 0.0, 0.0, 8, 4, "tspl_raw", "", "tspl", 203, "os_queue", "", 9100),
            ("50x30_double", 50.0, 30.0, 2, 2.0, 2.0, 48.0, 28.0, 0.0, 0.0, 8, 4, "tspl_raw", "", "tspl", 203, "os_queue", "", 9100),
        ]
        for prof in default_profiles:
            conn.execute(
                """
                INSERT OR IGNORE INTO calibration_profiles (
                    spec_key, label_width_mm, label_height_mm, cols, col_gap_mm, row_gap_mm,
                    safe_width_mm, safe_height_mm, offset_x_mm, offset_y_mm, darkness,
                    print_speed, preferred_channel, printer_name,
                    protocol, dpi, connection_type, network_host, network_port
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                prof,
            )

        conn.execute(
            "INSERT OR IGNORE INTO app_state (key, value, updated_at) VALUES (?, ?, ?)",
            ("last_printed_spec", "100x100_single", _utc_now_str()),
        )

        conn.execute(
            """
            INSERT OR IGNORE INTO carrier_rules (
                id, name, shipment_regex, warehouse_regex, ctn_regex, default_rotate, enabled
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "rule_default",
                "通用货代箱唛默认提取规则",
                r"\b(FBA[A-Z0-9]{6,12})\b",
                r"\b([A-Z]{3}\d)\b",
                r"(?:CTNS[:：\s]*|Box\s*)(\d+)\s*(?:/|of)\s*(\d+)",
                0,
                1,
            ),
        )


def get_app_state(key: str, default: str = "", db_path: Path | None = None) -> str:
    with get_conn(db_path) as conn:
        row = conn.execute("SELECT value FROM app_state WHERE key = ?", (key,)).fetchone()
        return str(row["value"]) if row else default


def set_app_state(key: str, value: str, db_path: Path | None = None) -> None:
    with get_conn(db_path) as conn:
        conn.execute(
            """
            INSERT INTO app_state (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, value, _utc_now_str()),
        )


def list_calibration_profiles(db_path: Path | None = None) -> list[CalibrationProfile]:
    with get_conn(db_path) as conn:
        rows = conn.execute("SELECT * FROM calibration_profiles ORDER BY spec_key").fetchall()
        return [CalibrationProfile(**dict(r)) for r in rows]


def upsert_calibration_profile(profile: CalibrationProfile, db_path: Path | None = None) -> CalibrationProfile:
    with get_conn(db_path) as conn:
        conn.execute(
            """
            INSERT INTO calibration_profiles (
                spec_key, label_width_mm, label_height_mm, cols, col_gap_mm, row_gap_mm,
                safe_width_mm, safe_height_mm, offset_x_mm, offset_y_mm, darkness,
                print_speed, preferred_channel, printer_name,
                protocol, dpi, connection_type, network_host, network_port
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(spec_key) DO UPDATE SET
                label_width_mm = excluded.label_width_mm,
                label_height_mm = excluded.label_height_mm,
                cols = excluded.cols,
                col_gap_mm = excluded.col_gap_mm,
                row_gap_mm = excluded.row_gap_mm,
                safe_width_mm = excluded.safe_width_mm,
                safe_height_mm = excluded.safe_height_mm,
                offset_x_mm = excluded.offset_x_mm,
                offset_y_mm = excluded.offset_y_mm,
                darkness = excluded.darkness,
                print_speed = excluded.print_speed,
                preferred_channel = excluded.preferred_channel,
                printer_name = excluded.printer_name,
                protocol = excluded.protocol,
                dpi = excluded.dpi,
                connection_type = excluded.connection_type,
                network_host = excluded.network_host,
                network_port = excluded.network_port
            """,
            (
                profile.spec_key,
                profile.label_width_mm,
                profile.label_height_mm,
                profile.cols,
                profile.col_gap_mm,
                profile.row_gap_mm,
                profile.safe_width_mm,
                profile.safe_height_mm,
                profile.offset_x_mm,
                profile.offset_y_mm,
                profile.darkness,
                profile.print_speed,
                profile.preferred_channel,
                profile.printer_name,
                profile.protocol,
                profile.dpi,
                profile.connection_type,
                profile.network_host,
                profile.network_port,
            ),
        )
    return profile


def delete_calibration_profile(spec_key: str, db_path: Path | None = None) -> bool:
    with get_conn(db_path) as conn:
        cur = conn.execute("DELETE FROM calibration_profiles WHERE spec_key = ?", (spec_key,))
        return cur.rowcount > 0


def list_sku_templates(db_path: Path | None = None) -> list[SkuTemplate]:
    with get_conn(db_path) as conn:
        rows = conn.execute("SELECT * FROM skus ORDER BY updated_at DESC").fetchall()
        result: list[SkuTemplate] = []
        for r in rows:
            els = [CanvasElement.model_validate(item) for item in json.loads(r["canvas_elements_json"])]
            result.append(
                SkuTemplate(
                    id=r["id"],
                    sku=r["sku"],
                    fnsku=r["fnsku"],
                    title_raw=r["title_raw"],
                    title_clean=r["title_clean"],
                    width_mm=r["width_mm"],
                    height_mm=r["height_mm"],
                    layout_type=r["layout_type"],
                    elements=els,
                    default_qty=r["default_qty"],
                    updated_at=r["updated_at"],
                )
            )
        return result


def upsert_sku_template(payload: SkuTemplateUpsert, db_path: Path | None = None) -> SkuTemplate:
    now = _utc_now_str()
    tpl_id = payload.id or f"sku_{uuid.uuid4().hex[:10]}"
    els_json = json.dumps([e.model_dump(by_alias=True) for e in payload.elements], ensure_ascii=False)
    with get_conn(db_path) as conn:
        conn.execute(
            """
            INSERT INTO skus (
                id, sku, fnsku, title_raw, title_clean, width_mm, height_mm,
                layout_type, canvas_elements_json, default_qty, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(sku) DO UPDATE SET
                fnsku = excluded.fnsku,
                title_raw = excluded.title_raw,
                title_clean = excluded.title_clean,
                width_mm = excluded.width_mm,
                height_mm = excluded.height_mm,
                layout_type = excluded.layout_type,
                canvas_elements_json = excluded.canvas_elements_json,
                default_qty = excluded.default_qty,
                updated_at = excluded.updated_at
            """,
            (
                tpl_id,
                payload.sku,
                payload.fnsku,
                payload.title_raw,
                payload.title_clean,
                payload.width_mm,
                payload.height_mm,
                payload.layout_type,
                els_json,
                payload.default_qty,
                now,
            ),
        )
        row = conn.execute("SELECT * FROM skus WHERE sku = ?", (payload.sku,)).fetchone()
        assert row is not None
        els = [CanvasElement.model_validate(item) for item in json.loads(row["canvas_elements_json"])]
        return SkuTemplate(
            id=row["id"],
            sku=row["sku"],
            fnsku=row["fnsku"],
            title_raw=row["title_raw"],
            title_clean=row["title_clean"],
            width_mm=row["width_mm"],
            height_mm=row["height_mm"],
            layout_type=row["layout_type"],
            elements=els,
            default_qty=row["default_qty"],
            updated_at=row["updated_at"],
        )


def delete_sku_template(sku_id: str, db_path: Path | None = None) -> bool:
    with get_conn(db_path) as conn:
        cur = conn.execute("DELETE FROM skus WHERE id = ?", (sku_id,))
        return cur.rowcount > 0


def create_print_batch(payload: PrintBatchCreate, db_path: Path | None = None) -> PrintBatchRecord:
    batch_id = f"batch_{uuid.uuid4().hex[:10]}"
    now = _utc_now_str()
    src_json = json.dumps(payload.source_files, ensure_ascii=False)
    ov_json = json.dumps([e.model_dump(by_alias=True) for e in payload.overlay_elements], ensure_ascii=False)
    with get_conn(db_path) as conn:
        conn.execute(
            """
            INSERT INTO print_batches (
                id, batch_type, shipment_id, warehouse_code, spec_key,
                total_units_or_boxes, copies_per_box, order_mode, channel,
                summary, source_files_json, overlay_elements_json, snapshot_dir, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                batch_id,
                payload.batch_type,
                payload.shipment_id,
                payload.warehouse_code,
                payload.spec_key,
                payload.total_units_or_boxes,
                payload.copies_per_box,
                payload.order_mode,
                payload.channel,
                payload.summary,
                src_json,
                ov_json,
                payload.snapshot_dir,
                now,
            ),
        )
    return PrintBatchRecord(
        id=batch_id,
        batch_type=payload.batch_type,
        shipment_id=payload.shipment_id,
        warehouse_code=payload.warehouse_code,
        spec_key=payload.spec_key,
        total_units_or_boxes=payload.total_units_or_boxes,
        copies_per_box=payload.copies_per_box,
        order_mode=payload.order_mode,
        channel=payload.channel,
        summary=payload.summary,
        source_files=payload.source_files,
        overlay_elements=payload.overlay_elements,
        snapshot_dir=payload.snapshot_dir,
        created_at=now,
    )


def list_print_batches(db_path: Path | None = None) -> list[PrintBatchRecord]:
    with get_conn(db_path) as conn:
        rows = conn.execute("SELECT * FROM print_batches ORDER BY created_at DESC, rowid DESC").fetchall()
        out: list[PrintBatchRecord] = []
        for r in rows:
            out.append(
                PrintBatchRecord(
                    id=r["id"],
                    batch_type=r["batch_type"],
                    shipment_id=r["shipment_id"],
                    warehouse_code=r["warehouse_code"],
                    spec_key=r["spec_key"],
                    total_units_or_boxes=r["total_units_or_boxes"],
                    copies_per_box=r["copies_per_box"],
                    order_mode=r["order_mode"],
                    channel=r["channel"],
                    summary=r["summary"],
                    source_files=json.loads(r["source_files_json"]),
                    overlay_elements=[CanvasElement.model_validate(e) for e in json.loads(r["overlay_elements_json"])],
                    snapshot_dir=r["snapshot_dir"],
                    created_at=r["created_at"],
                )
            )
        return out


def get_print_batch(batch_id: str, db_path: Path | None = None) -> PrintBatchRecord | None:
    with get_conn(db_path) as conn:
        r = conn.execute("SELECT * FROM print_batches WHERE id = ?", (batch_id,)).fetchone()
        if not r:
            return None
        return PrintBatchRecord(
            id=r["id"],
            batch_type=r["batch_type"],
            shipment_id=r["shipment_id"],
            warehouse_code=r["warehouse_code"],
            spec_key=r["spec_key"],
            total_units_or_boxes=r["total_units_or_boxes"],
            copies_per_box=r["copies_per_box"],
            order_mode=r["order_mode"],
            channel=r["channel"],
            summary=r["summary"],
            source_files=json.loads(r["source_files_json"]),
            overlay_elements=[CanvasElement.model_validate(e) for e in json.loads(r["overlay_elements_json"])],
            snapshot_dir=r["snapshot_dir"],
            created_at=r["created_at"],
        )


def update_print_batch_snapshot(batch_id: str, snapshot_path: str, db_path: Path | None = None) -> None:
    with get_conn(db_path) as conn:
        conn.execute("UPDATE print_batches SET snapshot_dir = ? WHERE id = ?", (snapshot_path, batch_id))


def delete_print_batch(batch_id: str, db_path: Path | None = None) -> PrintBatchRecord | None:
    rec = get_print_batch(batch_id, db_path=db_path)
    if rec is None:
        return None
    with get_conn(db_path) as conn:
        conn.execute("DELETE FROM print_batches WHERE id = ?", (batch_id,))
    return rec


def list_carrier_rules(include_disabled: bool = False, db_path: Path | None = None) -> list[CarrierRule]:
    sql = "SELECT * FROM carrier_rules"
    if not include_disabled:
        sql += " WHERE enabled = 1"
    sql += " ORDER BY CASE WHEN id = 'rule_default' THEN 1 ELSE 0 END, rowid DESC"
    with get_conn(db_path) as conn:
        rows = conn.execute(sql).fetchall()
        return [
            CarrierRule(
                id=r["id"],
                name=r["name"],
                shipment_regex=r["shipment_regex"],
                warehouse_regex=r["warehouse_regex"],
                ctn_regex=r["ctn_regex"],
                default_rotate=r["default_rotate"],
                enabled=bool(r["enabled"]),
            )
            for r in rows
        ]


def upsert_carrier_rule(rule: CarrierRule, db_path: Path | None = None) -> CarrierRule:
    rule_id = (rule.id or "").strip() or f"rule_{uuid.uuid4().hex[:8]}"
    with get_conn(db_path) as conn:
        conn.execute(
            """
            INSERT INTO carrier_rules (
                id, name, shipment_regex, warehouse_regex, ctn_regex, default_rotate, enabled
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                shipment_regex = excluded.shipment_regex,
                warehouse_regex = excluded.warehouse_regex,
                ctn_regex = excluded.ctn_regex,
                default_rotate = excluded.default_rotate,
                enabled = excluded.enabled
            """,
            (
                rule_id,
                rule.name.strip() or "自定义箱唛规则",
                rule.shipment_regex.strip(),
                rule.warehouse_regex.strip(),
                rule.ctn_regex.strip(),
                int(rule.default_rotate),
                1 if rule.enabled else 0,
            ),
        )
    return CarrierRule(
        id=rule_id,
        name=rule.name.strip() or "自定义箱唛规则",
        shipment_regex=rule.shipment_regex.strip(),
        warehouse_regex=rule.warehouse_regex.strip(),
        ctn_regex=rule.ctn_regex.strip(),
        default_rotate=int(rule.default_rotate),
        enabled=bool(rule.enabled),
    )


def delete_carrier_rule(rule_id: str, db_path: Path | None = None) -> bool:
    with get_conn(db_path) as conn:
        cur = conn.execute("DELETE FROM carrier_rules WHERE id = ?", (rule_id,))
        return cur.rowcount > 0
