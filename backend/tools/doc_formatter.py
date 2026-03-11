"""
文档格式化工具：将各章节内容按标准模板组装成最终 Markdown 文档。
"""
from datetime import datetime


def assemble_doc(
    game_title: str,
    sec_gameplay: str,
    sec_worldview: str,
    sec_art: str,
    sec_tech: str,
    session_id: str,
    version: int = 1,
) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    return f"""# 🎮 {game_title} H5 游戏设计方案

> **任务 ID:** RLG-{session_id[:8].upper()}  
> **版本:** v{version}.0  
> **生成时间:** {today}  
> **状态:** 待确认

---

## 一、玩法设计

{sec_gameplay}

---

## 二、世界观设定

{sec_worldview}

---

## 三、美术资源方案

{sec_art}

---

## 四、技术方案

{sec_tech}

---

*本文档由 Roguelike Generator AI 自动生成*
"""
