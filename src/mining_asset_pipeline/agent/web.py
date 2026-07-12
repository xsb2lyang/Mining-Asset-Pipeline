"""Local Gradio review interface for the asset-quality workflow."""

import argparse
import json
from pathlib import Path
from typing import Any

from .models import AssetRequest, ReviewDecision
from .policy import REVIEW_ISSUES
from .workflow import AssetWorkflow


_PROGRESS = {
    "created": ("1/6", "已创建资产目录，等待视觉生成"),
    "visual_running": ("2/6", "正在运行 SAM3 / SAM3D 视觉生成"),
    "review_required": ("3/6", "等待人工视觉审查"),
    "visual_approved": ("3/6", "视觉资产已批准，正在启动物理子代理审查"),
    "physics_review_running": ("4/6", "Physics Author 与 Physics Critic 正在生成、审查物理规格"),
    "physics_review_required": ("4/6", "旧任务等待物理确认；新任务不会进入此状态"),
    "usd_running": ("5/6", "物理规格已通过审查，正在转换 USD 并写入属性"),
    "complete": ("完成", "最终 USD 和报告已生成"),
    "failed": ("已中断", "请查看事件记录和对应工具日志"),
    "blocked": ("已阻塞", "物理子代理在限定轮数内无法收敛；未执行 USD 物理化"),
}

_PROGRESS_STEPS: list[str] = [
    "created",
    "visual_running",
    "review_required",
    "physics_review_running",
    "usd_running",
    "complete",
]

_STEP_LABELS: dict[str, str] = {
    "created": "创建",
    "visual_running": "视觉生成",
    "review_required": "视觉审查",
    "physics_review_running": "物理审查",
    "usd_running": "USD 化",
    "complete": "完成",
}

_TICK_INTERVAL = 0.5


def progress_markdown(manifest: dict[str, Any]) -> str:
    stage, description = _PROGRESS.get(manifest["status"], ("未知", "未知状态"))
    return f"## 当前进度：{stage}\n**阶段：** `{manifest['status']}`  \n**说明：** {description}"


def _render_progress_svg(manifest: dict[str, Any]) -> str:
    """Render a 6-step linear progress bar as inline SVG."""
    status = manifest["status"]
    failed = status in {"failed", "blocked"}

    if failed:
        events = manifest.get("events", [])
        prev_status = None
        for event in events:
            if event.get("status") in {"failed", "blocked"}:
                break
            prev_status = event.get("status")
        if prev_status in _PROGRESS_STEPS:
            active_idx = _PROGRESS_STEPS.index(prev_status)
        else:
            active_idx = _PROGRESS_STEPS.index("review_required") if status == "visual_approved" else 0
    elif status in _PROGRESS_STEPS:
        active_idx = _PROGRESS_STEPS.index(status)
    else:
        active_idx = _PROGRESS_STEPS.index("review_required") if status == "visual_approved" else 0

    cell_w = 130
    left_pad = 30
    total_w = left_pad * 2 + cell_w * len(_PROGRESS_STEPS)
    cy = 22

    rects: list[str] = []
    lines: list[str] = []
    for i, step in enumerate(_PROGRESS_STEPS):
        cx = left_pad + cell_w * i + cell_w // 2
        if i < active_idx:
            fill = "#16a34a"
        elif i == active_idx:
            fill = "#dc2626" if failed else "#16a34a"
        else:
            fill = "#e5e7eb"
        stroke = "#ffffff"
        rects.append(
            f'<g><circle cx="{cx}" cy="{cy}" r="14" fill="{fill}" stroke="{stroke}" stroke-width="2"/>'
            f'<text x="{cx}" y="{cy + 4}" text-anchor="middle" font-size="11" fill="#ffffff" font-weight="600">{i + 1}</text>'
            f'<text x="{cx}" y="{cy + 34}" text-anchor="middle" font-size="11" fill="#374151">{_STEP_LABELS[step]}</text></g>'
        )
        if i < len(_PROGRESS_STEPS) - 1:
            x1 = cx + 16
            x2 = left_pad + cell_w * (i + 1) + cell_w // 2 - 16
            line_fill = "#16a34a" if i < active_idx else "#e5e7eb"
            lines.append(
                f'<line x1="{x1}" y1="{cy}" x2="{x2}" y2="{cy}" stroke="{line_fill}" stroke-width="4"/>'
            )

    return (
        f'<svg viewBox="0 0 {total_w} 70" xmlns="http://www.w3.org/2000/svg" '
        f'style="display:block;width:100%;max-width:{total_w}px;height:auto;">'
        + "".join(lines)
        + "".join(rects)
        + "</svg>"
    )


def _tail_log(workflow: AssetWorkflow, asset_id: str, n: int = 30) -> str:
    """Return the tail of the most recent log artifact, or empty string."""
    try:
        root = workflow.store.root(asset_id).resolve()
    except (ValueError, FileNotFoundError):
        return ""
    manifest = workflow.summary(asset_id)
    artifacts = manifest.get("artifacts", {}) or {}
    candidates: list[Path] = []
    for key, value in artifacts.items():
        if not key.endswith("_log") or not isinstance(value, str):
            continue
        path = (root / value).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            continue
        if path.is_file():
            candidates.append(path)
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        return ""
    try:
        text = candidates[0].read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return "\n".join(text.splitlines()[-n:])


def _format_runtime_error(stage: str, asset_id: str, exc: BaseException, workflow: AssetWorkflow) -> str:
    """Build a friendly error message for gr.Error from a workflow RuntimeError."""
    manifest = workflow.summary(asset_id) if asset_id else None
    log_relpath = None
    if manifest:
        for key, value in (manifest.get("artifacts") or {}).items():
            if key.endswith("_log") and isinstance(value, str):
                log_relpath = value
                break
    msg = f"{stage} 失败：{exc}"
    if log_relpath:
        msg += f"\n日志路径：outputs/{asset_id}/{log_relpath}"
    return msg


def _scan_assets(workflow: AssetWorkflow) -> list[list[str]]:
    """List existing asset bundles under output_root."""
    rows: list[list[str]] = []
    root = workflow.store.output_root
    if not root.is_dir():
        return rows
    for bundle in sorted(root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        manifest_p = bundle / "manifest.json"
        if not manifest_p.is_file():
            continue
        try:
            m = json.loads(manifest_p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        request_p = bundle / "request.json"
        prompt = ""
        if request_p.is_file():
            try:
                prompt = str(json.loads(request_p.read_text(encoding="utf-8")).get("prompt", ""))
            except (json.JSONDecodeError, OSError):
                prompt = ""
        rows.append([
            bundle.name,
            str(m.get("status", "?")),
            str(m.get("created_at", "?")),
            prompt,
        ])
    return rows


def _paths(workflow: AssetWorkflow, asset_id: str) -> dict[str, str | None]:
    manifest = workflow.summary(asset_id)
    root = workflow.store.root(asset_id)
    artifacts = manifest.get("artifacts", {})
    return {
        "source": str(root / manifest["source_image"]),
        "mask_preview": str(root / "visual" / "sam3" / "preview.png") if (root / "visual" / "sam3" / "preview.png").is_file() else None,
        "mesh_preview": str(root / "visual" / "sam3d" / "preview.png") if (root / "visual" / "sam3d" / "preview.png").is_file() else None,
        "glb": str(root / artifacts["glb"]) if artifacts.get("glb") else None,
        "sam3_report": str(root / artifacts["sam3_report"]) if artifacts.get("sam3_report") else None,
        "geometry_report": str(root / artifacts["geometry_report"]) if artifacts.get("geometry_report") else None,
        "proposal": str(root / artifacts["physics_proposal"]) if artifacts.get("physics_proposal") else None,
        "physics_spec": str(root / artifacts["physics_spec"]) if artifacts.get("physics_spec") else None,
    }


def _view(workflow: AssetWorkflow, asset_id: str) -> tuple[Any, ...]:
    manifest = workflow.summary(asset_id)
    paths = _paths(workflow, asset_id)
    root = workflow.store.root(asset_id)

    def read(path: str | None) -> dict[str, Any] | None:
        return json.loads(Path(path).read_text(encoding="utf-8")) if path else None

    def read_yaml(path: str | None) -> dict[str, Any] | None:
        if not path:
            return None
        import yaml
        return yaml.safe_load(Path(path).read_text(encoding="utf-8"))

    events_lines: list[str] = []
    for event in manifest["events"][-8:]:
        events_lines.append(f"- `{event['status']}` — {event['message']}")
    if manifest["status"] == "failed" and manifest.get("error"):
        events_lines.append("")
        events_lines.append(f"**最近错误：** {manifest['error']}")
    events_md = "\n".join(events_lines) if events_lines else "（暂无事件）"

    review_paths = [
        root / value for key, value in manifest.get("artifacts", {}).items()
        if key.startswith("physics_review_") and isinstance(value, str)
    ]
    review_paths.sort()
    physics_reviews = [json.loads(path.read_text(encoding="utf-8")) for path in review_paths if path.is_file()]
    tail = _tail_log(workflow, asset_id) if manifest["status"] == "failed" else ""

    return (
        progress_markdown(manifest),
        _render_progress_svg(manifest),
        manifest,
        paths["source"],
        paths["mask_preview"],
        paths["mesh_preview"],
        paths["glb"],
        {
            "sam3": read(paths["sam3_report"]),
            "geometry": read(paths["geometry_report"]),
            "physics_proposal": read(paths["proposal"]),
            "physics_spec": read_yaml(paths["physics_spec"]),
            "physics_critic_reviews": physics_reviews,
        },
        events_md,
        tail,
    )


def asset_ui_update(workflow: AssetWorkflow, asset_id: str) -> tuple[Any, ...]:
    """Return the complete, stable output contract for asset-oriented UI events."""
    return (asset_id, asset_id, *_view(workflow, asset_id), _log_for_asset(workflow, asset_id))


def _log_for_asset(workflow: AssetWorkflow, asset_id: str, tail: int = 60) -> str:
    """Read all log artifacts under an asset bundle, most recent first."""
    try:
        root = workflow.store.root(asset_id).resolve()
    except (ValueError, FileNotFoundError):
        return ""
    manifest = workflow.summary(asset_id)
    artifacts = manifest.get("artifacts", {}) or {}
    candidates: list[Path] = []
    for key, value in artifacts.items():
        if not key.endswith("_log") or not isinstance(value, str):
            continue
        path = (root / value).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            continue
        if path.is_file():
            candidates.append(path)
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    blocks: list[str] = []
    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lines = text.splitlines()[-tail:]
        blocks.append(f"### {path.relative_to(root).as_posix()} (末尾 {len(lines)} 行)\n```\n" + "\n".join(lines) + "\n```")
    return "\n\n".join(blocks)


def build_demo(workflow: AssetWorkflow):
    """Return a Gradio Blocks application without starting a server."""
    import gradio as gr

    with gr.Blocks(title="Mining Asset Quality Agent") as demo:
        gr.Markdown("# Mining Asset Quality Agent\n创建资产、审查视觉结果。通过后由 Physics Author / Critic 自动审查规格并生成 USD。")
        asset_state = gr.State("")
        progress = gr.Markdown("## 当前进度：未加载资产")
        progress_svg = gr.HTML(value="", label="进度")
        with gr.Row():
            with gr.Column():
                image = gr.Image(label="输入 RGB", type="filepath", sources=["upload"])
                prompt = gr.Textbox(label="Prompt", lines=2)
                category = gr.Textbox(label="资产类别（可选）")
                task = gr.Textbox(label="目标任务（可选）")
                constraints = gr.Textbox(label="机器人约束（可选）", lines=2)
                create = gr.Button("创建并运行视觉流程", variant="primary")
            with gr.Column():
                asset_id = gr.Textbox(label="资产 ID", interactive=True)
                load = gr.Button("加载资产")
                manifest = gr.JSON(label="资产状态")
                events = gr.Markdown(label="执行记录")
        with gr.Row():
            original = gr.Image(label="原始图像", interactive=False)
            mask = gr.Image(label="SAM3 Mask 预览", interactive=False)
            mesh_preview = gr.Image(label="SAM3D 静态预览（审查主视图）", interactive=False)
        model = gr.Model3D(label="SAM3D GLB 交互预览（可鼠标拖拽旋转；WebGL 不兼容时忽略）", clear_color=[0.1, 0.1, 0.1, 1.0])
        reports = gr.JSON(label="自动检查、物理规格与子代理审查")
        with gr.Group():
            gr.Markdown("## 视觉人工审查")
            approve = gr.Button("批准视觉资产", variant="primary")
            issue = gr.Radio(choices=REVIEW_ISSUES, value="shape_incorrect", label="问题类别")
            feedback = gr.Textbox(label="补充反馈（可选）", lines=2)
            revised_prompt = gr.Textbox(label="修订 Prompt（分割问题时可选）")
            candidate_index = gr.Number(label="SAM3 候选编号（可选）", precision=0)
            reject = gr.Button("提交反馈并执行受控修复")
        with gr.Group():
            gr.Markdown("## 自动物理规格审查\n视觉批准后，Physics Author 会写入 `physics/physics_spec.yaml`，Physics Critic 会逐轮校验；只有通过后才会执行 USD 物理化。")
        with gr.Accordion("运行日志与失败诊断", open=False):
            with gr.Row():
                refresh_btn = gr.Button("刷新日志")
                auto_refresh = gr.Checkbox(value=True, label="自动刷新日志")
            log_stream = gr.Textbox(
                label="日志（最近写入优先）",
                lines=20,
                interactive=False,
                max_lines=600,
                autoscroll=True,
            )
            error_panel = gr.Markdown(label="失败时显示的 log 末尾")
            log_timer = gr.Timer(value=_TICK_INTERVAL, active=True)
        with gr.Accordion("已有资产", open=False):
            asset_list = gr.Dataframe(headers=["asset_id", "status", "created_at", "prompt"], interactive=False, label="outputs/ 下的资产")
            list_refresh = gr.Button("刷新列表")

        asset_outputs = [
            asset_state, asset_id, progress, progress_svg, manifest, original,
            mask, mesh_preview, model, reports, events, error_panel, log_stream,
        ]

        def _safe_create(image_path, prompt_value, category_value, task_value, constraints_value):
            if not image_path or not prompt_value or not prompt_value.strip():
                raise gr.Error("RGB 图像和 Prompt 均为必填项")
            asset_id_value = ""
            try:
                asset_id_value = workflow.create_asset(Path(image_path), AssetRequest(
                    prompt=prompt_value.strip(),
                    asset_category=category_value or "",
                    target_task=task_value or "",
                    robot_constraints=constraints_value or "",
                ))
            except (ValueError, RuntimeError, FileNotFoundError) as exc:
                raise gr.Error(f"创建资产失败：{exc}")
            yield asset_ui_update(workflow, asset_id_value)
            try:
                workflow.run_visual(asset_id_value)
            except (RuntimeError, ValueError) as exc:
                yield asset_ui_update(workflow, asset_id_value)
                raise gr.Error(_format_runtime_error("视觉生成", asset_id_value, exc, workflow))
            yield asset_ui_update(workflow, asset_id_value)

        def _safe_load(value):
            if not value:
                raise gr.Error("请输入资产 ID")
            try:
                return asset_ui_update(workflow, value)
            except (ValueError, FileNotFoundError, json.JSONDecodeError) as exc:
                raise gr.Error(f"加载资产失败：{exc}")

        def _safe_approve(value):
            if not value:
                raise gr.Error("请先创建或加载资产")
            try:
                workflow.begin_physics_review(value)
                yield asset_ui_update(workflow, value)
                workflow.run_physics_pipeline(value)
            except (RuntimeError, ValueError) as exc:
                yield asset_ui_update(workflow, value)
                raise gr.Error(_format_runtime_error("视觉审查", value, exc, workflow))
            yield asset_ui_update(workflow, value)

        def _safe_reject(value, issue_value, feedback_value, prompt_value, candidate_value):
            if not value:
                raise gr.Error("请先创建或加载资产")
            index = int(candidate_value) if candidate_value is not None else None
            try:
                workflow.submit_review(value, ReviewDecision(
                    approved=False,
                    issue=issue_value,
                    feedback=feedback_value or "",
                    revised_prompt=prompt_value or "",
                    candidate_index=index,
                ))
            except (RuntimeError, ValueError) as exc:
                raise gr.Error(_format_runtime_error("反馈修复", value, exc, workflow))
            return asset_ui_update(workflow, value)

        def _refresh_log(value, enabled=True):
            if not value or not enabled:
                return gr.skip()
            return _log_for_asset(workflow, value)

        def _refresh_list():
            return _scan_assets(workflow)

        def _on_select_asset(evt: gr.SelectData):
            if not evt.index:
                return ""
            row_index = evt.index[0]
            rows = _scan_assets(workflow)
            if 0 <= row_index < len(rows):
                return rows[row_index][0]
            return ""

        create.click(_safe_create, [image, prompt, category, task, constraints], asset_outputs, concurrency_limit=1, concurrency_id="asset_gpu")
        load.click(_safe_load, [asset_id], asset_outputs, queue=False)
        approve.click(_safe_approve, [asset_state], asset_outputs, concurrency_limit=1, concurrency_id="asset_gpu")
        reject.click(_safe_reject, [asset_state, issue, feedback, revised_prompt, candidate_index], asset_outputs, concurrency_limit=1, concurrency_id="asset_gpu")
        refresh_btn.click(_refresh_log, [asset_state], [log_stream])
        list_refresh.click(_refresh_list, outputs=[asset_list])
        asset_list.select(_on_select_asset, outputs=[asset_id])
        log_timer.tick(_refresh_log, [asset_state, auto_refresh], [log_stream])
        demo.load(_refresh_list, outputs=[asset_list])
    return demo.queue(default_concurrency_limit=1)


def main() -> int:
    parser = argparse.ArgumentParser(description="Launch the local Mining Asset Quality Agent review UI")
    parser.add_argument("--output-root", type=Path, default=Path("outputs"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7860)
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[3]
    workflow = AssetWorkflow(repo_root, args.output_root)
    build_demo(workflow).launch(server_name=args.host, server_port=args.port, share=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
