"""
意图解析辅助工具：将用户自然语言映射到结构化修改指令。
"""

CONFIRM_KEYWORDS = {"确认", "ok", "好", "通过", "没问题", "可以", "棒", "完美", "确定"}
SECTION_KEYWORDS = {
    "gameplay":  ["玩法", "卡牌", "关卡", "技能", "组合", "机制", "BOSS", "boss", "操作"],
    "worldview": ["世界观", "故事", "背景", "场景", "配色", "颜色", "风格", "主题", "叙事"],
    "art":       ["美术", "素材", "图片", "资源", "提示词", "绘图", "风格规范", "资产"],
    "tech":      ["技术", "代码", "框架", "架构", "Phaser", "TypeScript", "性能"],
}


def quick_classify(text: str) -> dict:
    """
    对用户输入做快速分类（作为 LLM 解析的 fallback）。
    返回与 intent_parser 相同结构的字典。
    """
    t = text.strip().lower()

    # 确认
    if any(kw in t for kw in CONFIRM_KEYWORDS):
        return {"action": "confirm", "target_section": None, "scope": None, "constraint": text}

    # 识别目标模块
    for section, keywords in SECTION_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            scope = "surgical" if len(text) < 30 else "rewrite"
            return {
                "action": "revise",
                "target_section": section,
                "target_subsection": None,
                "change_type": "modify",
                "scope": scope,
                "constraint": text,
            }

    return {
        "action": "revise",
        "target_section": "all",
        "scope": "rewrite",
        "constraint": text,
    }
