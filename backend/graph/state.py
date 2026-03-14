from typing import TypedDict, Annotated, Optional
from langgraph.graph.message import add_messages


def merge_dicts(a: dict, b: dict) -> dict:
    """合并两个字典，用于并行 Agent 同步写入同一字段时的 reducer。"""
    return {**a, **b}


def keep_last(a: str, b: str) -> str:
    """并行写入时保留最后一个非空值。"""
    return b if b else a


class GameDesignState(TypedDict):
    # 对话历史（add_messages 自动处理并发追加）
    messages: Annotated[list, add_messages]

    # 用户原始输入
    user_requirement: str

    # 结构化需求（需求分析 Agent 产出）
    structured_req: Optional[dict]

    # 各模块文档（独立存储，支持精准修订）
    sec_gameplay: Optional[str]
    sec_worldview: Optional[str]
    sec_art: Optional[str]
    sec_tech: Optional[str]

    # 合并后的完整文档
    final_doc: Optional[str]

    # 各章节版本号：四个并行 Agent 同时写入，使用 merge_dicts reducer
    versions: Annotated[dict, merge_dicts]

    # 当前阶段：并行 Agent 同时写入时保留最后一个
    current_stage: Annotated[str, keep_last]

    # 用户的修改意图（精准路由用）
    edit_intent: Optional[dict]

    # 是否最终确认
    confirmed: bool

    # 当前迭代轮次
    iteration_count: int

    # 生成的 H5 游戏代码（完整内联 HTML，向后兼容）
    game_code: Optional[str]

    # 多文件版游戏代码 {"data.js": ..., "game.js": ..., "index.html": ..., "style.css": ...}
    game_files: Optional[dict]

    # 生成的美术资源清单 {filename: url_path}
    art_assets: Optional[dict]

    # 美术阶段：0=未开始, 1=样本已生成待确认, 2=风格已确认, 3=全套已完成
    art_phase: int

    # 3张样本图 {filename: url_path}
    art_samples: Optional[dict]

    # 用户对风格的备注（确认时填写）
    art_style_notes: Optional[str]
