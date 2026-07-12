"""Local Gradio review interface for the asset-quality workflow."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .models import AssetRequest, ReviewDecision
from .policy import REVIEW_ISSUES
from .workflow import AssetWorkflow


def _paths(workflow: AssetWorkflow, asset_id: str) -> dict[str, str | None]:
    manifest = workflow.summary(asset_id)
    root = workflow.store.root(asset_id)
    artifacts = manifest.get("artifacts", {})
    return {
        "source": str(root / manifest["source_image"]),
        "mask_preview": str(root / "visual" / "sam3" / "preview.png") if (root / "visual" / "sam3" / "preview.png").is_file() else None,
        "glb": str(root / artifacts["glb"]) if artifacts.get("glb") else None,
        "sam3_report": str(root / artifacts["sam3_report"]) if artifacts.get("sam3_report") else None,
        "geometry_report": str(root / artifacts["geometry_report"]) if artifacts.get("geometry_report") else None,
        "proposal": str(root / artifacts["physics_proposal"]) if artifacts.get("physics_proposal") else None,
    }


def _view(workflow: AssetWorkflow, asset_id: str) -> tuple[Any, ...]:
    manifest = workflow.summary(asset_id)
    paths = _paths(workflow, asset_id)
    root = workflow.store.root(asset_id)
    def read(path: str | None) -> dict[str, Any] | None:
        return json.loads(Path(path).read_text(encoding="utf-8")) if path else None
    events = "\n".join(f"- `{event['status']}` — {event['message']}" for event in manifest["events"][-8:])
    return (
        asset_id,
        manifest,
        paths["source"],
        paths["mask_preview"],
        paths["glb"],
        {"sam3": read(paths["sam3_report"]), "geometry": read(paths["geometry_report"]), "physics_proposal": read(paths["proposal"])},
        events,
    )


def build_demo(workflow: AssetWorkflow):
    """Return a Gradio Blocks application without starting a server."""
    import gradio as gr

    material_choices = sorted(workflow._material_profiles())
    collision_choices = sorted(workflow._collision_profiles())
    with gr.Blocks(title="Mining Asset Quality Agent") as demo:
        gr.Markdown("# Mining Asset Quality Agent\n创建资产、审查视觉结果，并在批准后确认 USD 物理配置。")
        asset_state = gr.State("")
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
            model = gr.Model3D(label="SAM3D GLB 预览", clear_color=[0.1, 0.1, 0.1, 1.0])
        reports = gr.JSON(label="自动检查与物理提议")
        with gr.Group():
            gr.Markdown("## 视觉人工审查")
            approve = gr.Button("批准视觉资产", variant="primary")
            issue = gr.Radio(choices=REVIEW_ISSUES, value="shape_incorrect", label="问题类别")
            feedback = gr.Textbox(label="补充反馈（可选）", lines=2)
            revised_prompt = gr.Textbox(label="修订 Prompt（分割问题时可选）")
            candidate_index = gr.Number(label="SAM3 候选编号（可选）", precision=0)
            reject = gr.Button("提交反馈并执行受控修复")
        with gr.Group():
            gr.Markdown("## 物理配置确认")
            material = gr.Dropdown(choices=material_choices, value="ceramic" if "ceramic" in material_choices else material_choices[0], label="材质 profile")
            collision = gr.Dropdown(choices=collision_choices, value="open_container" if "open_container" in collision_choices else collision_choices[0], label="碰撞 profile")
            confirm = gr.Button("确认物理配置并生成 USD", variant="primary")

        outputs = [asset_state, asset_id, manifest, original, mask, model, reports, events]

        def create_asset(image_path, prompt_value, category_value, task_value, constraints_value):
            if not image_path or not prompt_value or not prompt_value.strip():
                raise gr.Error("RGB 图像和 Prompt 均为必填项")
            created = workflow.create_asset(Path(image_path), AssetRequest(prompt=prompt_value.strip(), asset_category=category_value or "", target_task=task_value or "", robot_constraints=constraints_value or ""))
            workflow.run_visual(created)
            return (created, *_view(workflow, created))

        def load_asset(value):
            if not value:
                raise gr.Error("请输入资产 ID")
            return (value, *_view(workflow, value))

        def approve_asset(value):
            if not value:
                raise gr.Error("请先创建或加载资产")
            workflow.submit_review(value, ReviewDecision(approved=True))
            return (value, *_view(workflow, value))

        def reject_asset(value, issue_value, feedback_value, prompt_value, candidate_value):
            if not value:
                raise gr.Error("请先创建或加载资产")
            index = int(candidate_value) if candidate_value is not None else None
            workflow.submit_review(value, ReviewDecision(approved=False, issue=issue_value, feedback=feedback_value or "", revised_prompt=prompt_value or "", candidate_index=index))
            return (value, *_view(workflow, value))

        def confirm_asset(value, material_value, collision_value):
            if not value:
                raise gr.Error("请先创建或加载资产")
            workflow.confirm_physics(value, material_value, collision_value)
            return (value, *_view(workflow, value))

        create.click(create_asset, [image, prompt, category, task, constraints], outputs, concurrency_limit=1, concurrency_id="asset_gpu")
        load.click(load_asset, [asset_id], outputs, queue=False)
        approve.click(approve_asset, [asset_state], outputs, concurrency_limit=1, concurrency_id="asset_gpu")
        reject.click(reject_asset, [asset_state, issue, feedback, revised_prompt, candidate_index], outputs, concurrency_limit=1, concurrency_id="asset_gpu")
        confirm.click(confirm_asset, [asset_state, material, collision], outputs, concurrency_limit=1, concurrency_id="asset_gpu")
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
